"""Reviewed immutable native packages; all pedigree inputs travel with the ROM.

A package holds a small permanent mapping, never a primer-to-species catalog.
Export does not invoke models, modify pixels, accept new generation output, or
change saves. It consumes retained accepted bytes plus reviewed GBA conversion.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from genetics.adventures import AdventureStore, validate_family
from genetics.expression import ExpressionBody
from genetics.primers import canonical, digest, hash_id, VirtualGenome
from genetics.roster import decode_png, gba_asset
from game_agents.adventure_story import StoryGraph, generate_story

ROOT = Path(__file__).resolve().parents[1]
NATIVE_SPECIES = (1576, 1577)
ASSET_NAMES = ("front.png", "back.png", "icon.png", "normal.pal")
MAX_FILE = 32 * 1024 * 1024


def decoded_pixels(raw: bytes, role: str) -> bytes:
    if role not in ("front", "back", "icon"):
        raise ValueError("unknown decoded artwork role")
    width, height = (32, 64) if role == "icon" else (64, 64)
    gba_asset(raw, width=width, height=height)
    _, _, _, _, chunks, rows = decode_png(raw)
    palette = chunks[b"PLTE"]
    return b"".join(b"\0\0\0\0" if i == 0 else palette[i * 3:i * 3 + 3] + b"\xff"
                    for row in rows for byte in row for i in (byte >> 4, byte & 15))


def sprite_diversity(left: bytes, right: bytes, role: str = "front") -> dict:
    a, b = decoded_pixels(left, role), decoded_pixels(right, role)
    visible = changed = intersection = union = 0
    for i in range(0, len(a), 4):
        pa, pb = a[i:i + 4], b[i:i + 4]
        va, vb = bool(pa[3]), bool(pb[3])
        union += va or vb
        intersection += va and vb
        if va or vb:
            visible += 1
            changed += pa != pb
    return {"exact_duplicate": a == b, "changed_visible_fraction": changed / max(1, visible),
            "silhouette_iou": intersection / max(1, union),
            "left_pixels_sha256": sha256(a).hexdigest(), "right_pixels_sha256": sha256(b).hexdigest()}


def publish(path: Path, data: bytes) -> None:
    """Atomic no-replace publication, safe for interrupted/concurrent retries."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".publish-", delete=False) as output:
            temporary = output.name
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                raise ValueError(f"Immutable package file already differs: {path}")
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            os.unlink(temporary)


def _palette(raw: bytes) -> bytes:
    try:
        lines = raw.decode("ascii").splitlines()
        if lines[:3] != ["JASC-PAL", "0100", "16"] or len(lines) != 19:
            raise ValueError("expected a sixteen-color JASC palette")
        colors = [tuple(map(int, line.split())) for line in lines[3:]]
        if any(len(color) != 3 or any(not 0 <= value <= 255 for value in color) for color in colors):
            raise ValueError("invalid palette channels")
        return bytes(value & 0xF8 for color in colors for value in color)
    except (UnicodeDecodeError, TypeError) as error:
        raise ValueError("invalid native palette") from error


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE:
        raise ValueError("missing, linked, empty or excessive package asset")
    return path.read_bytes()


def _json(blobs: dict, name: str):
    try:
        return json.loads(blobs[name])
    except (KeyError, ValueError) as error:
        raise ValueError(f"Missing or invalid required package data: {name}") from error


def _check_record(record: dict, raw: bytes, role: str, production: bool):
    if (not isinstance(record, dict) or set(record) != {"sha256", "size", "role", "provenance"}
            or record["sha256"] != sha256(raw).hexdigest() or record["size"] != len(raw)
            or record["role"] != role or not isinstance(record["provenance"], dict)):
        raise ValueError("accepted content record no longer binds retained bytes")
    provenance = record["provenance"]
    if role in ("profile", "source-art"):
        if provenance.get("mode") not in ("fixture", "external_model", "openrouter"):
            raise ValueError("explicit model or fixture provenance required")
        if production and provenance["mode"] == "fixture":
            raise ValueError("production package cannot present fixture expression or artwork")
        if provenance["mode"] != "fixture":
            if not isinstance(provenance.get("model"), str) or not provenance["model"]:
                raise ValueError("external generation model provenance is missing")
            hash_id(provenance.get("prompt_sha256"))
            if provenance["mode"] == "external_model" and not provenance.get("external_tool"):
                raise ValueError("external generation tool provenance is missing")


def _verify_content(manifest: dict, blobs: dict) -> None:
    adventure, family, story = (_json(blobs, name) for name in ("adventure.json", "family.json", "story.json"))
    if adventure["adventure_id"] != manifest["adventure_id"] or adventure["creation_mode"] != manifest["creation_mode"]:
        raise ValueError("adventure manifest mismatch")
    if (adventure.get("creation_mode") not in ("os_csprng", "deterministic_fixture")
            or not isinstance(family, list) or not 3 <= len(family) <= 64):
        raise ValueError("unsupported adventure creation mode or family capacity")
    people = validate_family(adventure, family)
    if not 3 <= len(people) <= 64:
        raise ValueError("a prepared family requires its bounded complete pedigree")
    graph = StoryGraph.model_validate(story)
    expected = generate_story(bytes.fromhex(adventure["seed"]), primer_id=graph.primer_id, signal_score=graph.signal_score)
    if (graph != expected or graph.compiled_variant != manifest["variant"]
            or graph.structure_fingerprint() != manifest["story_structure_sha256"]
            or graph.primer_id not in {primer["primer_id"] for primer in adventure["primers"]}):
        raise ValueError("compiled story does not bind the seeded accepted grammar")
    production = adventure["creation_mode"] == "os_csprng"
    acceptance = _json(blobs, "acceptance.json")
    if set(acceptance) != {"story", "individuals"} or set(acceptance["individuals"]) != set(people):
        raise ValueError("accepted pedigree inventory mismatch")
    _check_record(acceptance["story"], blobs["story.json"], "story", production)
    required = {"adventure.json", "family.json", "story.json", "acceptance.json", "icon-palette.pal"}
    for identity, individual in people.items():
        stem = f"individuals/{identity}"
        required.update(f"{stem}/{name}" for name in ("profile.json", "source.png", "context.json"))
        profile, context = _json(blobs, f"{stem}/profile.json"), _json(blobs, f"{stem}/context.json")
        records = acceptance["individuals"][identity]
        if set(records) != {"profile", "source-art"}:
            raise ValueError("profile and actual source artwork are required for every parent")
        _check_record(records["profile"], blobs[f"{stem}/profile.json"], "profile", production)
        _check_record(records["source-art"], blobs[f"{stem}/source.png"], "source-art", production)
        decode_png(blobs[f"{stem}/source.png"])
        parent_ids = individual["parents"] or []
        parents = [{"individual_id": parent_id,
                    "profile": _json(blobs, f"individuals/{parent_id}/profile.json"),
                    "image_sha256": acceptance["individuals"][parent_id]["source-art"]["sha256"]}
                   for parent_id in parent_ids]
        expected_context = {"schema_version": 1, "adventure_id": adventure["adventure_id"], "individual": individual,
                            "reference": adventure["reference"],
                            "primers": [next(primer for primer in adventure["primers"] if primer["primer_id"] == item["primer_id"] and primer["version"] == item["version"])
                                        for item in individual["primer_ancestry"]],
                            "parents": parents,
                            "interpretation": "Model-mediated fictional expression; no fixed allele-to-color, score, morphology or battle-stat mapping."}
        if context != expected_context:
            raise ValueError("profile context does not contain the exact genome and both parent inputs")
        ExpressionBody.model_validate(profile["expression"])
        if (profile["individual_id"] != identity or profile["adventure_id"] != adventure["adventure_id"]
                or profile["genome_sha256"] != individual["genome_sha256"]
                or profile["context_sha256"] != digest(context)
                or profile["provenance"] != records["profile"]["provenance"]
                or profile["provenance"]["context_sha256"] != digest(context)
                or profile["parent_profile_sha256"] != [acceptance["individuals"][p]["profile"]["sha256"] for p in parent_ids]
                or profile["parent_image_sha256"] != [acceptance["individuals"][p]["source-art"]["sha256"] for p in parent_ids]
                or records["source-art"]["provenance"]["profile_sha256"] != records["profile"]["sha256"]):
            raise ValueError("profile/source identity, genome, parent or context binding changed")
    if manifest["resident_capacity"] != 2 or len(manifest["native_mapping"]) != 2:
        raise ValueError("native package supports exactly two permanent appearance slots")
    seen, personalities = set(), set()
    icon_colors = _palette(blobs["icon-palette.pal"])
    if icon_colors != _palette((ROOT / "game/graphics/pokemon/icon_palettes/pal3.pal").read_bytes()):
        raise ValueError("retained icon palette differs from compiled palette 3")
    for slot, mapping in enumerate(manifest["native_mapping"], 1):
        identity = mapping["individual_id"]
        individual = people.get(identity)
        if individual is None or mapping["species"] != NATIVE_SPECIES[slot - 1]:
            raise ValueError("invalid native identity/species mapping")
        if (identity in seen or type(mapping["personality"]) is not int or mapping["personality"] in personalities
                or not 0 < mapping["personality"] < 2 ** 32):
            raise ValueError("duplicate native identity/personality")
        seen.add(identity)
        personalities.add(mapping["personality"])
        expected_pixel_origin = ("retained external source" if production else "retained fixture source") + "; reviewed conversion; decoded final RGB555 pixels"
        if (mapping["pixel_provenance"] != expected_pixel_origin
                or not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", mapping["name"])
                or mapping["genome_sha256"] != individual["genome_sha256"]
                or mapping["profile_sha256"] != acceptance["individuals"][identity]["profile"]["sha256"]
                or mapping["source_sha256"] != acceptance["individuals"][identity]["source-art"]["sha256"]):
            raise ValueError("native genome/profile/source/name binding changed")
        if individual["primer_ancestry"] != [{"primer_id": graph.primer_id, "version": individual["primer_ancestry"][0]["version"]}]:
            raise ValueError("two-individual proof requires one shared story primer")
        required.update(f"slot-{slot}/{name}" for name in (*ASSET_NAMES, "conversion.json"))
        conversion = _json(blobs, f"slot-{slot}/conversion.json")
        if (conversion["source_sha256"] != mapping["source_sha256"] or conversion["icon_palette_index"] != 3
                or set(conversion["files"]) != set(ASSET_NAMES)):
            raise ValueError("conversion must bind the retained actual individual source and palette 3")
        front_colors = None
        for name in ASSET_NAMES:
            raw = blobs[f"slot-{slot}/{name}"]
            if sha256(raw).hexdigest() != conversion["files"][name]:
                raise ValueError("converted artwork changed after review")
            if name == "normal.pal":
                if _palette(raw) != front_colors:
                    raise ValueError("normal.pal differs from the front/back PNG palette")
                continue
            role = name[:-4]
            decoded = decoded_pixels(raw, role)
            if sha256(decoded).hexdigest() != mapping["pixels_sha256"][role]:
                raise ValueError("decoded native pixels mismatch")
            _, _, _, _, chunks, _ = decode_png(raw)
            colors = chunks[b"PLTE"]
            if role == "front":
                front_colors = colors
            elif role == "back" and colors != front_colors:
                raise ValueError("native front/back palette mismatch")
            elif role == "icon" and colors != icon_colors:
                raise ValueError("native icon must use compiled palette 3")
    first_id, child_id = (mapping["individual_id"] for mapping in manifest["native_mapping"])
    if first_id not in (people[child_id]["parents"] or []):
        raise ValueError("prepared family slots must be parent first and inherited offspring second")
    child_profile = _json(blobs, f"individuals/{child_id}/profile.json")
    expected_signal = child_profile["expression"]["scores"]["aurora_sensitivity"] * 15 // 100
    if graph.signal_score != expected_signal:
        raise ValueError("accepted story signal must match the selected child's model expression")
    if set(blobs) != required:
        raise ValueError("package must contain exactly its required complete content inventory")
    diversity = {role: sprite_diversity(blobs[f"slot-1/{role}.png"], blobs[f"slot-2/{role}.png"], role)
                 for role in ("front", "back", "icon")}
    if any(result["exact_duplicate"] for result in diversity.values()):
        raise ValueError("same-primer individuals require distinct decoded artwork in every native role")
    if diversity != manifest["diversity"]:
        raise ValueError("decoded artwork diversity evidence changed")


def verify_package(directory: Path | str) -> dict:
    directory = Path(directory)
    try:
        manifest = json.loads(_read(directory / "manifest.json"))
        if manifest.get("schema_version") == 2:
            from genetics.individual_package import verify_individual_package
            return verify_individual_package(directory)
        if (manifest.get("schema_version") != 1
                or manifest.get("package_sha256") != digest({k: v for k, v in manifest.items() if k != "package_sha256"})):
            raise ValueError("invalid adventure package binding")
        hash_id(manifest["adventure_id"])
        if not isinstance(manifest["review_note"], str) or not 16 <= len(manifest["review_note"]) <= 4096:
            raise ValueError("explicit bounded visual review note required")
        blobs = {}
        for name, checksum in manifest["files"].items():
            if not re.fullmatch(r"[a-z0-9_-]+(?:/[a-z0-9_.-]+)*\.[a-z0-9]+", name) or ".." in name:
                raise ValueError("invalid package content path")
            path = directory / name
            if any((directory / parent).is_symlink() for parent in Path(name).parents):
                raise ValueError("linked package directories are not portable")
            blobs[name] = _read(path)
            if sha256(blobs[name]).hexdigest() != hash_id(checksum):
                raise ValueError("package asset checksum changed")
        present = {p.relative_to(directory).as_posix() for p in directory.rglob("*")
                   if (p.is_file() or p.is_symlink()) and p.relative_to(directory).parts[0] != "build"}
        if present != set(blobs) | {"manifest.json"}:
            raise ValueError("unlisted or missing package content")
        if sum(map(len, blobs.values())) > 128 * 1024 * 1024:
            raise ValueError("prepared package exceeds the bounded content budget")
        _verify_content(manifest, blobs)
        return manifest
    except (KeyError, TypeError, StopIteration, IndexError) as error:
        raise ValueError("malformed or incomplete adventure package") from error


def export_package(store: AdventureStore | Path | str, output: Path | str,
                   selections: list[dict], review_note: str) -> dict:
    """Freeze two reviewed playable slots plus all actual pedigree inputs."""
    owned = not isinstance(store, AdventureStore)
    store = AdventureStore.open(store) if owned else store
    try:
        if len(selections) != 2 or any(set(item) != {"individual_id", "name", "art_directory"} for item in selections):
            raise ValueError("select exactly two explicit individual/name/art_directory entries")
        people = {}
        def retain(identity):
            if identity in people:
                return
            person = store.individual(identity)
            people[identity] = person
            for parent_id in person["parents"] or []:
                retain(parent_id)
        for item in selections:
            retain(item["individual_id"])
        family = sorted(people.values(), key=lambda person: (person["generation"], person["id"]))
        graph = store.retained_story()
        if graph is None:
            raise ValueError("accept a validated story before preparing its ROM package")
        story_record = store.accepted(store.manifest["adventure_id"], "story")
        blobs = {"adventure.json": canonical(store.manifest), "family.json": canonical(family),
                 "story.json": store.object_bytes(story_record),
                 "icon-palette.pal": (ROOT / "game/graphics/pokemon/icon_palettes/pal3.pal").read_bytes()}
        acceptance = {"story": story_record, "individuals": {}}
        for individual in family:
            identity = individual["id"]
            profile, source = store.accepted(identity, "profile"), store.accepted(identity, "source-art")
            if profile is None or source is None:
                raise ValueError("retain accepted profile and actual source art for every parent and child")
            acceptance["individuals"][identity] = {"profile": profile, "source-art": source}
            stem = f"individuals/{identity}"
            blobs.update({f"{stem}/context.json": canonical(store.generation_context(identity)),
                          f"{stem}/profile.json": store.object_bytes(profile), f"{stem}/source.png": store.object_bytes(source)})
        blobs["acceptance.json"] = canonical(acceptance)
        mappings = []
        for slot, item in enumerate(selections, 1):
            directory = Path(item["art_directory"])
            for name in (*ASSET_NAMES, "conversion.json"):
                blobs[f"slot-{slot}/{name}"] = _read(directory / name)
            identity = item["individual_id"]
            # Personality is a native compatibility field; the manifest retains
            # the complete 256-bit identity and rejects mapping collisions.
            personality = int.from_bytes(sha256(b"aurora/native-personality/v1\0" + bytes.fromhex(identity)).digest()[:4], "little") or 1
            mappings.append({"individual_id": identity, "name": item["name"], "species": NATIVE_SPECIES[slot - 1],
                             "personality": personality, "genome_sha256": people[identity]["genome_sha256"],
                             "profile_sha256": acceptance["individuals"][identity]["profile"]["sha256"],
                             "source_sha256": acceptance["individuals"][identity]["source-art"]["sha256"],
                             "pixel_provenance": ("retained fixture source" if store.manifest["creation_mode"] == "deterministic_fixture" else "retained external source") + "; reviewed conversion; decoded final RGB555 pixels",
                             "pixels_sha256": {role: sha256(decoded_pixels(blobs[f"slot-{slot}/{role}.png"], role)).hexdigest()
                                               for role in ("front", "back", "icon")}})
        graph = StoryGraph.model_validate(graph)
        manifest = {"schema_version": 1, "adventure_id": store.manifest["adventure_id"],
                    "creation_mode": store.manifest["creation_mode"], "resident_capacity": 2,
                    "variant": graph.compiled_variant, "story_structure_sha256": graph.structure_fingerprint(),
                    "native_mapping": mappings, "review_note": review_note,
                    "diversity": {role: sprite_diversity(blobs[f"slot-1/{role}.png"], blobs[f"slot-2/{role}.png"], role)
                                  for role in ("front", "back", "icon")},
                    "files": {name: sha256(raw).hexdigest() for name, raw in sorted(blobs.items())}}
        manifest["package_sha256"] = digest(manifest)
        _verify_content(manifest, blobs)
        if not isinstance(review_note, str) or not 16 <= len(review_note) <= 4096:
            raise ValueError("explicit bounded visual review note required")
        output = Path(output)
        for name, raw in blobs.items():
            publish(output / name, raw)
        publish(output / "manifest.json", canonical(manifest) + b"\n")
        return verify_package(output)
    finally:
        if owned:
            store.close()


def content_header(manifest: dict) -> bytes:
    def array(value): return "{"+",".join(f"0x{b:02x}" for b in bytes.fromhex(hash_id(value)))+"}"
    lines=["#ifndef GUARD_CONSTANTS_AURORA_ADVENTURE_CONTENT_H","#define GUARD_CONSTANTS_AURORA_ADVENTURE_CONTENT_H",
           "// Generated from the immutable reviewed adventure package.","#define AURORA_ADVENTURE_ENABLED 1",
           f"#define AURORA_ADVENTURE_VARIANT {manifest['variant']}",
           f"#define AURORA_ADVENTURE_ID_BYTES {array(manifest['adventure_id'])}",
           f"#define AURORA_ADVENTURE_PACKAGE_BYTES {array(manifest['package_sha256'])}"]
    for label,mapping in zip(("FIRST","SECOND"),manifest["native_mapping"]):
        lines.extend([f"#define AURORA_ADVENTURE_{label}_ID_BYTES {array(mapping['individual_id'])}",
                      f"#define AURORA_ADVENTURE_{label}_PERSONALITY 0x{mapping['personality']:08x}",
                      f'#define AURORA_ADVENTURE_{label}_NAME "{mapping["name"]}"'])
    return ("\n".join(lines)+"\n#endif\n").encode()
