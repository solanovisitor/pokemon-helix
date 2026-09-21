"""Bootstrap safety checks against a tiny synthetic local Git repository."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bootstrap-game.py"


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="helix-bootstrap-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.upstream = self.root / "upstream"
        self.upstream.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Synthetic fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.upstream / "tracked.txt").write_text("upstream\n")
        (self.upstream / "untouched.txt").write_text("keep me\n")
        (self.upstream / ".gitignore").write_text("*.ignored\n")
        (self.upstream / "subdirectory").mkdir()
        (self.upstream / "subdirectory/.keep").write_text("")
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic baseline")
        self.revision = self.git("rev-parse", "HEAD").strip()
        self.bundle = self.root / "bundle"
        (self.bundle / "overlay/new").mkdir(parents=True)
        (self.bundle / "overlay/new/feature.txt").write_text("synthetic overlay\n")
        (self.upstream / "tracked.txt").write_text("patched\n")
        patch = subprocess.check_output(["git", "diff", "--binary"], cwd=self.upstream)
        (self.bundle / "helix.patch").write_bytes(patch)
        self.git("restore", "tracked.txt")
        self.manifest = {
            "schema": "helix-native-overlay-v1",
            "upstream_url": str(self.upstream),
            "upstream_revision": self.revision,
            "tracked_patch_paths": ["tracked.txt"],
            "overlay_paths": ["new/feature.txt"],
            "result_files": {"tracked.txt": digest(b"patched\n"),
                             "new/feature.txt": digest(b"synthetic overlay\n")},
            "bundle_files": {
                name: {"sha256": digest((self.bundle / name).read_bytes()),
                       "bytes": (self.bundle / name).stat().st_size}
                for name in ("helix.patch", "overlay/new/feature.txt")
            },
        }
        self.write_manifest()
        self.destination = self.root / "checkout"

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.upstream, stderr=subprocess.PIPE).decode()

    def write_manifest(self):
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest))

    def invoke(self, destination=None):
        return subprocess.run([sys.executable, str(SCRIPT), "--bundle", str(self.bundle),
                               "--destination", str(destination or self.destination),
                               "--repository", str(self.upstream)],
                              cwd=self.root, text=True, capture_output=True)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_refused(self, result, reason):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stderr)

    def test_bootstrap_preserves_history_and_is_idempotent(self):
        self.assert_success(self.invoke())
        self.assertEqual((self.destination / "tracked.txt").read_text(), "patched\n")
        self.assertEqual((self.destination / "new/feature.txt").read_text(), "synthetic overlay\n")
        head = subprocess.check_output(["git", "-C", str(self.destination), "rev-parse", "HEAD"]).decode().strip()
        self.assertEqual(head, self.revision)
        marker = self.destination / ".git/helix-overlay.json"
        before = marker.stat().st_mtime_ns
        result = self.invoke()
        self.assert_success(result)
        self.assertIn("Verified existing overlay", result.stdout)
        self.assertEqual(marker.stat().st_mtime_ns, before)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_existing_dirty_checkout_is_refused_without_changes(self):
        (self.upstream / "untouched.txt").write_text("user work\n")
        self.assert_refused(self.invoke(self.upstream), "contains changes")
        self.assertEqual((self.upstream / "tracked.txt").read_text(), "upstream\n")
        self.assertEqual((self.upstream / "untouched.txt").read_text(), "user work\n")
        self.assertFalse((self.upstream / "new").exists())

    def test_ignored_overlay_input_is_hashed_and_replayable(self):
        name = "new/graphic.ignored"
        content = b"synthetic native input\n"
        (self.bundle / "overlay" / name).write_bytes(content)
        self.manifest["overlay_paths"].append(name)
        self.manifest["result_files"][name] = digest(content)
        self.manifest["bundle_files"]["overlay/" + name] = {"sha256": digest(content), "bytes": len(content)}
        self.write_manifest()
        self.assert_success(self.invoke())
        self.assert_success(self.invoke())
        (self.destination / name).write_bytes(b"modified by user\n")
        self.assert_refused(self.invoke(), "Edited overlay file")

    def test_existing_plain_directory_is_not_replaced(self):
        self.destination.mkdir()
        (self.destination / "keep.txt").write_text("user work\n")
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(list(self.destination.iterdir()), [self.destination / "keep.txt"])

    def test_checkout_subdirectory_is_refused_without_writes(self):
        self.assert_refused(self.invoke(self.upstream / "subdirectory"), "checkout root")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertFalse((self.upstream / ".git/helix-overlay.json").exists())

    def test_different_upstream_revision_is_never_reset(self):
        self.git("commit", "--allow-empty", "-qm", "Different revision")
        current = self.git("rev-parse", "HEAD")
        self.assert_refused(self.invoke(self.upstream), "pinned upstream")
        self.assertEqual(self.git("rev-parse", "HEAD"), current)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_replay_refuses_unrelated_tracked_changes(self):
        self.assert_success(self.invoke())
        (self.destination / "untouched.txt").write_text("user work\n")
        self.assert_refused(self.invoke(), "unrelated or staged changes")
        self.assertEqual((self.destination / "untouched.txt").read_text(), "user work\n")

    def test_replay_refuses_unrelated_untracked_changes(self):
        self.assert_success(self.invoke())
        (self.destination / "extra.txt").write_text("user work\n")
        self.assert_refused(self.invoke(), "unrelated or staged changes")
        self.assertEqual((self.destination / "extra.txt").read_text(), "user work\n")

    def test_replay_refuses_edited_overlay(self):
        self.assert_success(self.invoke())
        (self.destination / "new/feature.txt").write_text("user work\n")
        self.assert_refused(self.invoke(), "Edited overlay file")

    def test_replay_refuses_another_manifest(self):
        self.assert_success(self.invoke())
        self.manifest["description"] = "a different version"
        self.write_manifest()
        self.assert_refused(self.invoke(), "Another overlay")

    def test_corrupt_input_is_refused_before_destination_creation(self):
        (self.bundle / "overlay/new/feature.txt").write_text("changed\n")
        self.assert_refused(self.invoke(), "Bundle mismatch")
        self.assertFalse(self.destination.exists())

    def test_missing_patch_checksum_is_refused(self):
        del self.manifest["bundle_files"]["helix.patch"]
        self.write_manifest()
        self.assert_refused(self.invoke(), "every consumed input")
        self.assertFalse(self.destination.exists())

    def test_missing_overlay_checksum_is_refused(self):
        del self.manifest["bundle_files"]["overlay/new/feature.txt"]
        self.write_manifest()
        self.assert_refused(self.invoke(), "every consumed input")
        self.assertFalse(self.destination.exists())

    def test_missing_result_checksum_is_refused(self):
        del self.manifest["result_files"]["new/feature.txt"]
        self.write_manifest()
        self.assert_refused(self.invoke(), "cover every patch and overlay")
        self.assertFalse(self.destination.exists())

    def test_unlisted_patch_file_is_refused(self):
        self.manifest["tracked_patch_paths"] = ["untouched.txt"]
        self.manifest["result_files"]["untouched.txt"] = self.manifest["result_files"].pop("tracked.txt")
        self.write_manifest()
        self.assert_refused(self.invoke(), "Patch paths differ")
        self.assertFalse(self.destination.exists())

    def test_manifest_path_traversal_is_refused(self):
        self.manifest["bundle_files"]["../outside.txt"] = {"sha256": "0" * 64}
        self.write_manifest()
        self.assert_refused(self.invoke(), "Unsafe manifest path")
        self.assertFalse(self.destination.exists())

    def test_bundle_symlink_escape_is_refused(self):
        source = self.bundle / "overlay/new/feature.txt"
        outside = self.root / "outside.txt"
        source.rename(outside)
        source.symlink_to(outside)
        self.assert_refused(self.invoke(), "Symlink/path escape")
        self.assertFalse(self.destination.exists())

    def test_destination_symlink_is_refused(self):
        self.destination.symlink_to(self.upstream, target_is_directory=True)
        self.assert_refused(self.invoke(), "Destination symlink")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_dangling_marker_symlink_cannot_write_outside_checkout(self):
        outside = self.root / "outside.json"
        (self.upstream / ".git/helix-overlay.json").symlink_to(outside)
        self.assert_refused(self.invoke(self.upstream), "marker symlink")
        self.assertFalse(outside.exists())
        self.assertEqual(self.git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
