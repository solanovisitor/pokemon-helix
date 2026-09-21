"""Append-only three-individual combat package over a retained v1 family.

The base package is copied byte-for-byte without its build. New battle rules,
the third accepted parent's reviewed art and prepared ledger are separately
bound; no model output, save or historical package is replaced.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re

from genetics.adventure_package import (ASSET_NAMES, ROOT, _palette, _read,
    decoded_pixels, publish, sprite_diversity, verify_package)
from genetics.primers import canonical, digest, hash_id
from genetics.roster import decode_png


def art_directory(package: Path, slot: int) -> Path:
    manifest = json.loads((package / "manifest.json").read_bytes())
    return package / ("base" if manifest["schema_version"] == 2 and slot < 3 else "") / f"slot-{slot}"


def verify_individual_package(directory: Path | str) -> dict:
    from genetics.battle_profiles import validate_battle_profile
    directory = Path(directory)
    manifest = json.loads(_read(directory / "manifest.json"))
    if (manifest.get("schema_version") != 2 or manifest.get("resident_capacity") != 3
            or manifest.get("package_sha256") != digest({k: v for k, v in manifest.items() if k != "package_sha256"})):
        raise ValueError("invalid individual-combat package binding")
    base = verify_package(directory / "base")
    if (base["schema_version"] != 1 or base["package_sha256"] != manifest["predecessor_package_sha256"]
            or any(base[key] != manifest[key] for key in ("adventure_id", "variant", "creation_mode", "story_structure_sha256"))):
        raise ValueError("combat migration must retain its exact predecessor")
    if not isinstance(manifest.get("review_note"), str) or not 16 <= len(manifest["review_note"]) <= 4096:
        raise ValueError("bounded concrete visual review required")
    inventory = manifest["files"]
    for name, checksum in inventory.items():
        if not re.fullmatch(r"[a-z0-9_-]+(?:/[a-z0-9_.-]+)*\.[a-z0-9]+", name) or ".." in name:
            raise ValueError("invalid combat content path")
        if any((directory / p).is_symlink() for p in Path(name).parents):
            raise ValueError("linked content directory")
        if sha256(_read(directory / name)).hexdigest() != hash_id(checksum):
            raise ValueError("combat content checksum changed")
    present = {p.relative_to(directory).as_posix() for p in directory.rglob("*")
               if (p.is_file() or p.is_symlink()) and p.relative_to(directory).parts[0] != "build"}
    if present != set(inventory) | {"manifest.json"}:
        raise ValueError("unlisted or missing combat package content")
    people = {p["id"]: p for p in json.loads((directory / "base/family.json").read_bytes())}
    mappings = manifest["native_mapping"]
    if len(mappings) != 3 or len({m["individual_id"] for m in mappings}) != 3:
        raise ValueError("three distinct resident individuals required")
    if len({m["personality"] for m in mappings}) != 3:
        raise ValueError("native personalities must not collide")
    for slot, mapping in enumerate(mappings):
        if slot < 2 and {k: v for k, v in mapping.items() if k != "battle_profile_sha256"} != base["native_mapping"][slot]:
            raise ValueError("existing native mapping cannot change during migration")
        if mapping["species"] != 1576 + slot or mapping["individual_id"] not in people:
            raise ValueError("unsupported native mapping")
        identity = mapping["individual_id"]
        expression_raw = (directory / f"base/individuals/{identity}/profile.json").read_bytes()
        profile = json.loads((directory / f"profiles/{identity}.json").read_bytes())
        validate_battle_profile(profile, individual=people[identity], expression=json.loads(expression_raw),
                                expression_sha256=sha256(expression_raw).hexdigest())
        if profile["profile_sha256"] != mapping["battle_profile_sha256"]:
            raise ValueError("battle profile mapping changed")
    first, child, wild = mappings
    if set(people[child["individual_id"]]["parents"]) != {first["individual_id"], wild["individual_id"]}:
        raise ValueError("wild individual must be the retained child's other parent")
    if (not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", wild["name"])
            or type(wild["personality"]) is not int or not 0 < wild["personality"] < 2**32):
        raise ValueError("invalid wild native fields")
    stem = directory / f"base/individuals/{wild['individual_id']}"
    if (wild["genome_sha256"] != people[wild["individual_id"]]["genome_sha256"]
            or wild["profile_sha256"] != sha256((stem / "profile.json").read_bytes()).hexdigest()
            or wild["source_sha256"] != sha256((stem / "source.png").read_bytes()).hexdigest()):
        raise ValueError("wild identity content binding changed")
    conversion = json.loads((directory / "slot-3/conversion.json").read_bytes())
    if conversion["source_sha256"] != wild["source_sha256"] or conversion["icon_palette_index"] != 3 or set(conversion["files"]) != set(ASSET_NAMES):
        raise ValueError("wild art conversion binding changed")
    colors = None
    for name in ASSET_NAMES:
        raw = _read(directory / "slot-3" / name)
        if sha256(raw).hexdigest() != conversion["files"][name]:
            raise ValueError("reviewed wild artwork changed")
        if name == "normal.pal":
            if _palette(raw) != colors:
                raise ValueError("wild front/back palette mismatch")
            continue
        role = name[:-4]
        if sha256(decoded_pixels(raw, role)).hexdigest() != wild["pixels_sha256"][role]:
            raise ValueError("wild decoded pixels changed")
        palette = decode_png(raw)[4][b"PLTE"]
        if role == "front": colors = palette
        elif role == "back" and colors != palette: raise ValueError("wild back palette mismatch")
        elif role == "icon" and palette != _palette((directory / "base/icon-palette.pal").read_bytes()):
            raise ValueError("wild icon palette mismatch")
    diversity = {}
    for other in (1, 2):
        for role in ("front", "back", "icon"):
            result = sprite_diversity((directory / f"base/slot-{other}/{role}.png").read_bytes(),
                                      (directory / f"slot-3/{role}.png").read_bytes(), role)
            if result["exact_duplicate"]: raise ValueError("wild appearance duplicates retained family")
            diversity[f"{other}-3/{role}"] = result
    if diversity != manifest["diversity"]: raise ValueError("wild diversity review changed")
    ledger = json.loads((directory / "ledger.json").read_bytes())
    _validate_ledger(ledger, manifest, people, directory)
    required = {"base/manifest.json", *["base/" + n for n in base["files"]], "ledger.json",
                *[f"profiles/{m['individual_id']}.json" for m in mappings],
                *[f"slot-3/{n}" for n in (*ASSET_NAMES, "conversion.json")]}
    if set(inventory) != required: raise ValueError("unexpected combat package inventory")
    return manifest


def _validate_ledger(ledger, manifest, people, directory):
    # Detailed frozen-event validation is shared with the durable ledger.
    from genetics.progression_ledger import validate_manifest
    validate_manifest(ledger)
    if ledger["adventure_id"] != manifest["adventure_id"] or len(ledger["encounters"]) != 1 or len(ledger["birth_events"]) != 1:
        raise ValueError("exactly one encounter and birth are supported")
    first, child, wild = manifest["native_mapping"]
    encounter, birth = ledger["encounters"][0], ledger["birth_events"][0]
    if birth["status"] != "prepared" or birth["receipt"] is not None:
        raise ValueError("new native package requires a prepared, unconsumed birth")
    if (encounter["individual_id"] != wild["individual_id"] or birth["child_individual_id"] != child["individual_id"]
            or birth["birth_intent"] != people[child["individual_id"]]["intent_id"]
            or [p["individual_id"] for p in birth["parents"]] != people[child["individual_id"]]["parents"]
            or {p["individual_id"] for p in birth["parents"]} != {first["individual_id"], wild["individual_id"]}):
        raise ValueError("ledger does not bind the native family")
    adventure = json.loads((directory / "base/adventure.json").read_bytes())
    def binding(identity):
        stem = directory / f"base/individuals/{identity}"
        return {"individual_id": identity, "individual_sha256": digest(people[identity]),
                "genome_sha256": people[identity]["genome_sha256"],
                "primer_ancestry": people[identity]["primer_ancestry"],
                "reference_sha256": digest(adventure["reference"]),
                "expression_sha256": sha256((stem / "profile.json").read_bytes()).hexdigest(),
                "source_art_sha256": sha256((stem / "source.png").read_bytes()).hexdigest()}
    if birth["child_binding"] != binding(child["individual_id"]):
        raise ValueError("birth binding changed")
    for parent in birth["parents"]:
        if parent["binding"] != binding(parent["individual_id"]):
            raise ValueError("birth parent binding changed")
    expected_encounter = binding(wild["individual_id"]) | {"battle_profile_sha256": wild["battle_profile_sha256"], "battle_profile_version": "aurora-expression-battle-v1"}
    if encounter["binding"] != expected_encounter or encounter["initial_owner"] != {"kind": "wild", "key": None}:
        raise ValueError("encounter expression, genome, art or combat binding changed")


def export_individual_package(base_directory, output, *, wild_art, wild_name, ledger, profiles, review_note):
    base_directory, output, wild_art = map(Path, (base_directory, output, wild_art))
    if output.resolve().is_relative_to(base_directory.resolve()):
        raise ValueError("new package output must stay outside its immutable predecessor")
    base = verify_package(base_directory)
    people = {p["id"]: p for p in json.loads((base_directory / "family.json").read_bytes())}
    first, child = base["native_mapping"]
    wild_id = next(p for p in people[child["individual_id"]]["parents"] if p != first["individual_id"])
    blobs = {"base/manifest.json": (base_directory / "manifest.json").read_bytes(),
             **{"base/" + name: (base_directory / name).read_bytes() for name in base["files"]},
             **{f"slot-3/{name}": _read(wild_art / name) for name in (*ASSET_NAMES, "conversion.json")},
             "ledger.json": canonical(ledger),
             **{f"profiles/{identity}.json": canonical(profile) for identity, profile in profiles.items()}}
    personality = int.from_bytes(sha256(b"aurora/native-personality/v1\0" + bytes.fromhex(wild_id)).digest()[:4], "little") or 1
    wild = {"individual_id": wild_id, "name": wild_name, "species": 1578, "personality": personality,
            "genome_sha256": people[wild_id]["genome_sha256"],
            "profile_sha256": sha256(blobs[f"base/individuals/{wild_id}/profile.json"]).hexdigest(),
            "source_sha256": sha256(blobs[f"base/individuals/{wild_id}/source.png"]).hexdigest(),
            "pixel_provenance": first["pixel_provenance"],
            "pixels_sha256": {role: sha256(decoded_pixels(blobs[f"slot-3/{role}.png"], role)).hexdigest() for role in ("front", "back", "icon")}}
    mappings = [{**m, "battle_profile_sha256": profiles[m["individual_id"]]["profile_sha256"]} for m in (first, child, wild)]
    manifest = {"schema_version": 2, "resident_capacity": 3, "predecessor_package_sha256": base["package_sha256"],
                **{k: base[k] for k in ("adventure_id", "variant", "creation_mode", "story_structure_sha256")},
                "native_mapping": mappings, "review_note": review_note,
                "diversity": {f"{slot}-3/{role}": sprite_diversity(blobs[f"base/slot-{slot}/{role}.png"], blobs[f"slot-3/{role}.png"], role)
                              for slot in (1, 2) for role in ("front", "back", "icon")},
                "files": {name: sha256(raw).hexdigest() for name, raw in sorted(blobs.items())}}
    manifest["package_sha256"] = digest(manifest)
    # Verify a staging directory before publishing any accepted output.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="helix-package-validation-") as temporary:
        stage = Path(temporary)
        for name, raw in blobs.items(): publish(stage / name, raw)
        publish(stage / "manifest.json", canonical(manifest) + b"\n")
        verify_individual_package(stage)
    for name, raw in blobs.items(): publish(output / name, raw)
    publish(output / "manifest.json", canonical(manifest) + b"\n")
    return verify_individual_package(output)


def combat_content_header(manifest, directory):
    from genetics.adventure_package import content_header
    from genetics.battle_profiles import native_battle_fields
    directory = Path(directory)
    def array(value): return "{" + ",".join(f"0x{b:02x}" for b in bytes.fromhex(hash_id(value))) + "}"
    header = content_header({**manifest, "schema_version": 1, "native_mapping": manifest["native_mapping"][:2]}).decode().removesuffix("#endif\n")
    third = manifest["native_mapping"][2]
    lines = [header, "#define AURORA_COMBAT_ENABLED 1", "#define AURORA_COMBAT_PROFILE_VERSION 1",
             f"#define AURORA_COMBAT_PREDECESSOR_PACKAGE_BYTES {array(manifest['predecessor_package_sha256'])}",
             f"#define AURORA_ADVENTURE_THIRD_ID_BYTES {array(third['individual_id'])}",
             f"#define AURORA_ADVENTURE_THIRD_PERSONALITY 0x{third['personality']:08x}",
             f'#define AURORA_ADVENTURE_THIRD_NAME "{third["name"]}"']
    for slot, mapping in enumerate(manifest["native_mapping"]):
        profile = json.loads((directory / f"profiles/{mapping['individual_id']}.json").read_bytes())
        fields = native_battle_fields(profile)
        initializer = "{" + ",".join("{" + ",".join(map(str, fields[key])) + "}" for key in ("base_stats", "types", "moves")) + "}"
        lines += [f"#define AURORA_COMBAT_PROFILE_{slot} {initializer}",
                  f"#define AURORA_COMBAT_PROFILE_HASH_{slot}_BYTES {array(profile['profile_sha256'])}"]
    ledger = json.loads((directory / "ledger.json").read_bytes())
    birth, encounter = ledger["birth_events"][0], ledger["encounters"][0]
    lines += [f"#define AURORA_COMBAT_BIRTH_EVENT_BYTES {array(birth['event_id'])}",
              f"#define AURORA_COMBAT_ENCOUNTER_EVENT_BYTES {array(encounter['event_id'])}",
              "#define AURORA_COMBAT_BREEDING_XP 125"]
    for slot in (0, 2):
        parent = next(p for p in birth["parents"] if p["individual_id"] == manifest["native_mapping"][slot]["individual_id"])
        lines.append(f"#define AURORA_COMBAT_REWARD_{slot}_BYTES {array(parent['reward_key'])}")
    return ("\n".join(lines) + "\n#endif\n").encode()


def verify_compiled_combat(manifest, directory, report, rom):
    """Check compiled identity, balancing and event bytes before accepting a build."""
    from genetics.battle_profiles import native_battle_fields
    import struct
    directory = Path(directory)
    types = {"TYPE_NORMAL": 1, "TYPE_WATER": 12, "TYPE_ICE": 16, "TYPE_PSYCHIC": 15}
    moves = {"MOVE_TACKLE": 33, "MOVE_WATER_GUN": 55, "MOVE_QUICK_ATTACK": 98,
             "MOVE_CONFUSION": 93, "MOVE_SWIFT": 129, "MOVE_GROWL": 45, "MOVE_HARDEN": 106}
    def check(symbol, expected):
        address = report["symbols"][symbol] - 0x08000000
        if address < 0 or rom[address:address + len(expected)] != expected:
            raise ValueError("compiled combat content differs: " + symbol)
    mappings = manifest["native_mapping"]
    check("gAuroraCombatIds", bytes.fromhex("".join(m["individual_id"] for m in mappings)))
    check("gAuroraCombatProfileHashes", bytes.fromhex("".join(m["battle_profile_sha256"] for m in mappings)))
    packed = b""
    for mapping in mappings:
        profile = json.loads((directory / f"profiles/{mapping['individual_id']}.json").read_bytes())
        fields = native_battle_fields(profile)
        packed += struct.pack("<8B4H", *fields["base_stats"], *[types[t] for t in fields["types"]], *[moves[m] for m in fields["moves"]])
    check("gAuroraCombatProfiles", packed)
    ledger = json.loads((directory / "ledger.json").read_bytes())
    birth = ledger["birth_events"][0]
    rewards = [next(p["reward_key"] for p in birth["parents"] if p["individual_id"] == mappings[slot]["individual_id"]) for slot in (0,2)]
    check("gAuroraCombatEventIds", bytes.fromhex(ledger["encounters"][0]["event_id"] + birth["event_id"] + "".join(rewards)))
    check("sPredecessorPackage", bytes.fromhex(manifest["predecessor_package_sha256"]))
