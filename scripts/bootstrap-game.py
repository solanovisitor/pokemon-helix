"""Materialize reviewed native source on pinned upstream, preserving its history.

Default destination: game/. Never cleans/resets an existing checkout or builds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str) -> str:
    return subprocess.check_output(list(args)).decode().strip()


def safe(root: Path, path: str) -> Path:
    if type(path) is not str or not path or any(char in path for char in "\\\0\r\n"):
        raise ValueError("Unsafe manifest path")
    relative = PurePosixPath(path)
    if (relative.is_absolute() or relative.as_posix() != path or not relative.parts
            or any(part in (".", "..") or part.lower() == ".git" for part in relative.parts)):
        raise ValueError("Unsafe manifest path")
    result = root
    for part in relative.parts:
        result = result / part
        if result.is_symlink():
            raise ValueError("Symlink/path escape refused")
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Symlink/path escape refused")
    return result


def unique_json(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate manifest or marker key")
        result[key] = value
    return result


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(), object_pairs_hook=unique_json)


def verify_bundle(bundle: Path) -> dict:
    manifest = load_json(safe(bundle, "manifest.json"))
    if type(manifest) is not dict or manifest.get("schema") != "helix-native-overlay-v1":
        raise ValueError("Unknown manifest")
    revision = manifest.get("upstream_revision")
    if type(revision) is not str or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise ValueError("Manifest requires an exact upstream commit")
    if type(manifest.get("upstream_url")) is not str or not manifest["upstream_url"]:
        raise ValueError("Manifest requires an upstream repository")
    groups = []
    for key in ("tracked_patch_paths", "overlay_paths"):
        values = manifest.get(key)
        if type(values) is not list or any(type(value) is not str for value in values):
            raise ValueError("Invalid manifest path list")
        for value in values:
            safe(bundle, value)
        if len(set(values)) != len(values):
            raise ValueError("Duplicate manifest path")
        groups.append(set(values))
    tracked, overlay = groups
    if not tracked or tracked & overlay:
        raise ValueError("Patch and overlay paths must be distinct")
    results = manifest.get("result_files")
    if type(results) is not dict or set(results) != tracked | overlay:
        raise ValueError("Result manifest must cover every patch and overlay path")
    for value in results.values():
        if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Invalid result SHA-256")
    inputs = manifest.get("bundle_files")
    required = {"helix.patch"} | {"overlay/" + path for path in overlay}
    if type(inputs) is not dict or not required.issubset(inputs):
        raise ValueError("Bundle manifest must cover every consumed input")
    for path, expected in inputs.items():
        source = safe(bundle, path)
        if (type(expected) is not dict or type(expected.get("sha256")) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]) is None
                or not source.is_file() or digest(source) != expected["sha256"]):
            raise ValueError("Bundle mismatch: " + path)
        if "bytes" in expected and (type(expected["bytes"]) is not int
                                    or source.stat().st_size != expected["bytes"]):
            raise ValueError("Bundle size mismatch: " + path)
    for path in overlay:
        if inputs["overlay/" + path]["sha256"] != results[path]:
            raise ValueError("Overlay result mismatch: " + path)
    stats = subprocess.check_output(["git", "apply", "--numstat", "-z", str(bundle / "helix.patch")])
    patch_paths = set()
    for record in stats.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3 or not fields[2]:
            raise ValueError("Unsupported patch path or rename")
        path = fields[2].decode("utf-8")
        safe(bundle, path)
        patch_paths.add(path)
    if patch_paths != tracked:
        raise ValueError("Patch paths differ from the manifest")
    return manifest


def status(destination: Path) -> set[str]:
    raw = subprocess.check_output(["git", "-C", str(destination), "-c", "status.renames=false",
                                   "status", "--porcelain=v1", "-z", "--untracked-files=all"])
    return {value.decode("utf-8") for value in raw.split(b"\0") if value}


def ignored_paths(destination: Path, paths: list[str]) -> set[str]:
    if not paths:
        return set()
    result = subprocess.run(["git", "-C", str(destination), "check-ignore", "--no-index", "-z", "--stdin"],
                            input=("\0".join(paths) + "\0").encode(), capture_output=True)
    if result.returncode not in (0, 1):
        raise ValueError("Could not inspect upstream ignore rules")
    return {value.decode("utf-8") for value in result.stdout.split(b"\0") if value}


def bootstrap(bundle: Path, destination: Path, repository: str | None = None) -> None:
    bundle = bundle.resolve()
    destination = destination.absolute()
    manifest = verify_bundle(bundle)
    if destination.is_symlink():
        raise ValueError("Destination symlink refused")
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-checkout", "--no-hardlinks", "--",
                        repository or manifest["upstream_url"], str(destination)], check=True)
        subprocess.run(["git", "-C", str(destination), "checkout", "--detach",
                        manifest["upstream_revision"]], check=True)
    top = Path(run("git", "-C", str(destination), "rev-parse", "--show-toplevel")).resolve()
    if top != destination.resolve():
        raise ValueError("Destination must be the checkout root, not a subdirectory")
    if run("git", "-C", str(destination), "rev-parse", "HEAD") != manifest["upstream_revision"]:
        raise ValueError("Existing checkout must be at pinned upstream; it is never reset")
    marker = Path(run("git", "-C", str(destination), "rev-parse", "--absolute-git-dir")) / "helix-overlay.json"
    if marker.is_symlink():
        raise ValueError("Overlay marker symlink refused")
    manifest_hash = digest(bundle / "manifest.json")
    if marker.exists():
        retained = load_json(marker)
        if (type(retained) is not dict or retained.get("manifest_sha256") != manifest_hash
                or retained.get("upstream_revision") != manifest["upstream_revision"]):
            raise ValueError("Another overlay already applied")
        ignored = ignored_paths(destination, manifest["overlay_paths"])
        expected_status = ({" M " + path for path in manifest["tracked_patch_paths"]}
                           | {"?? " + path for path in manifest["overlay_paths"] if path not in ignored})
        if status(destination) != expected_status:
            raise ValueError("Existing overlay contains unrelated or staged changes; use a new destination")
        for path, expected in manifest["result_files"].items():
            result = safe(destination, path)
            if not result.is_file() or digest(result) != expected:
                raise ValueError("Edited overlay file: " + path)
        print("Verified existing overlay; no files changed.")
        return
    if status(destination):
        raise ValueError("Existing checkout contains changes; use a new destination")
    for path in manifest["tracked_patch_paths"]:
        safe(destination, path)
    for path in manifest["overlay_paths"]:
        if safe(destination, path).exists():
            raise ValueError("Overlay would replace upstream/existing file: " + path)
    patch = bundle / "helix.patch"
    subprocess.run(["git", "-C", str(destination), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(destination), "apply", str(patch)], check=True)
    for path in manifest["overlay_paths"]:
        target = safe(destination, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(safe(bundle / "overlay", path), target)
    for path, expected in manifest["result_files"].items():
        result = safe(destination, path)
        if not result.is_file() or digest(result) != expected:
            raise ValueError("Applied source mismatch: " + path)
    marker.write_text(json.dumps({"manifest_sha256": manifest_hash,
                                  "upstream_revision": manifest["upstream_revision"]}, indent=2) + "\n")
    print("Pinned upstream history and verified Helix overlay ready: " + str(destination))
    print("No ROM was built. Read rom-source/README.md before compiling.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "rom-source")
    parser.add_argument("--destination", type=Path, default=ROOT / "game")
    parser.add_argument("--repository", help="Optional local clone source for offline verification")
    args = parser.parse_args()
    try:
        bootstrap(args.bundle, args.destination, args.repository)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print("Bootstrap refused: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
