"""Export the reviewed V2 native asset conversion into the public source bundle.

Run after integrate-native-assets-v2.py on a fresh public bootstrap. Existing public
fixture source must remain exact outside the conversion's declared files. This
does not create packages, copy accepted identities, or establish runtime success.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--conversion", type=Path, required=True)
    args = parser.parse_args()
    game = args.game.resolve()
    conversion = args.conversion.resolve()
    bundle = ROOT / "rom-source"
    spec = importlib.util.spec_from_file_location("public_bootstrap", ROOT / "scripts/bootstrap-game.py")
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    manifest = bootstrap.verify_bundle(bundle)
    receipt = json.loads((conversion / "conversion.json").read_text())
    if (receipt.get("schema") != 2 or receipt.get("dataset") != "todeschini/helix-assets"
            or receipt.get("revision") != "d7c825f2d15b0818d549b8367d1054cb53c23713"
            or receipt.get("config") != "gallery" or receipt.get("paid_calls") != 0
            or receipt.get("source_art_modified") is not False):
        raise ValueError("Unexpected conversion contract")
    if digest(ROOT / "scripts/integrate-native-assets-v2.py") != receipt["converter_sha256"]:
        raise ValueError("Converter changed since this conversion")
    upstream = subprocess.check_output(["git", "-C", str(game), "rev-parse", "HEAD"]).decode().strip()
    if upstream != manifest["upstream_revision"]:
        raise ValueError("Game must retain the pinned upstream revision")
    changed = receipt["overlay_files"]
    for name, expected in changed.items():
        source = bootstrap.safe(conversion / "overlay", name)
        target = bootstrap.safe(game, name)
        if digest(source) != expected or digest(target) != expected:
            raise ValueError("Conversion output changed: " + name)
    for name, expected in manifest["result_files"].items():
        if name not in changed and digest(bootstrap.safe(game, name)) != expected:
            raise ValueError("Unrelated public source changed: " + name)
    for name in ("helix_genesis", "aurora_adventure"):
        source = game / "include/constants" / (name + "_content.h")
        if "#define " + name.upper() + "_ENABLED 0" not in source.read_text():
            raise ValueError("Public packages must remain disabled")
    tracked = set(manifest["tracked_patch_paths"])
    overlay = set(manifest["overlay_paths"])
    for name in changed:
        result = subprocess.run(["git", "-C", str(game), "ls-files", "--error-unmatch", "--", name],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (tracked if result.returncode == 0 else overlay).add(name)
    actual_tracked = set(subprocess.check_output(
        ["git", "-C", str(game), "diff", "--name-only", "HEAD"]).decode().splitlines())
    if actual_tracked != tracked:
        raise ValueError("Tracked source changes exceed the explicit public bundle")
    patch = subprocess.check_output(["git", "-C", str(game), "diff", "--binary", "HEAD", "--", *sorted(tracked)])
    (bundle / "helix.patch").write_bytes(patch)
    for name in sorted(overlay):
        source = bootstrap.safe(game, name)
        destination = bootstrap.safe(bundle / "overlay", name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    manifest["tracked_patch_paths"] = sorted(tracked)
    manifest["overlay_paths"] = sorted(overlay)
    manifest["result_files"] = {name: digest(bootstrap.safe(game, name)) for name in sorted(tracked | overlay)}
    manifest["overlay_bytes"] = sum(bootstrap.safe(game, name).stat().st_size for name in overlay)
    inputs = set(manifest["bundle_files"]) | {"overlay/" + name for name in overlay}
    manifest["bundle_files"] = {name: {"bytes": bootstrap.safe(bundle, name).stat().st_size,
                                               "sha256": digest(bootstrap.safe(bundle, name))}
                                for name in sorted(inputs)}
    manifest["native_assets_batch1"] = {
        "conversion_version": 2,
        "dataset": receipt["dataset"], "config": receipt["config"], "revision": receipt["revision"],
        "conversion_sha256": digest(conversion / "conversion.json"),
        "converter_sha256": receipt["converter_sha256"],
        "designs": receipt["designs"], "positions": receipt["object_positions"],
        "native_changed_paths": sorted(changed),
        "public_runtime_acceptance": "not claimed; package gates remain disabled",
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    bootstrap.verify_bundle(bundle)
    print(json.dumps({"native_result_files": len(manifest["result_files"]),
                      "asset_conversion_paths": len(changed),
                      "manifest_sha256": digest(bundle / "manifest.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
