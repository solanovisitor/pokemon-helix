"""Reviewed, immutable compiled-roster packages; never runs models or edits pixels."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
from pathlib import Path
import re
import struct
import zlib

from genetics.breeding import BreedingError, BreedingStore, MAX_IMAGE, _publish, canonical, digest, read_bytes, read_json
from genetics.expression import ExpressionProfile
from genetics.models import Genotype


class RosterError(BreedingError):
    pass


def decode_png(raw: bytes) -> tuple[int, int, int, int, dict[bytes, bytes], list[bytes]]:
    """Bounded noninterlaced PNG decoding, including CRC, filters and stream end."""
    if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > MAX_IMAGE:
        raise RosterError("reviewed artwork must be a bounded PNG")
    chunks, compressed, position, ended = {}, bytearray(), 8, False
    idat_ended = False
    while position < len(raw):
        if position + 12 > len(raw) or ended:
            raise RosterError("truncated PNG or bytes after IEND")
        length, kind = struct.unpack(">I4s", raw[position:position + 8])
        end = position + length + 12
        if end > len(raw):
            raise RosterError("truncated PNG chunk")
        data = raw[position + 8:end - 4]
        if zlib.crc32(kind + data) != int.from_bytes(raw[end - 4:end], "big"):
            raise RosterError("PNG checksum changed")
        if position == 8 and kind != b"IHDR":
            raise RosterError("PNG requires IHDR first")
        if kind == b"IDAT":
            if idat_ended:
                raise RosterError("PNG IDAT chunks must be consecutive")
            compressed.extend(data)
        else:
            if compressed:
                idat_ended = True
            if kind in {b"IHDR", b"PLTE", b"tRNS", b"IEND"}:
                if kind in chunks:
                    raise RosterError("duplicate PNG chunk")
                chunks[kind] = data
            elif kind[:1].isupper():
                raise RosterError("unsupported critical PNG chunk")
        ended = kind == b"IEND"
        position = end
    try:
        width, height, bits, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[b"IHDR"])
    except (KeyError, struct.error):
        raise RosterError("invalid PNG header") from None
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if (not 1 <= width <= 4096 or not 1 <= height <= 4096 or channels is None
            or compression or filtering or interlace or chunks.get(b"IEND") != b""
            or bits not in ({1, 2, 4, 8} if color in {0, 3} else {8, 16})
            or not compressed):
        raise RosterError("unsupported PNG dimensions, encoding or termination")
    if color == 3 and (not 3 <= len(chunks.get(b"PLTE", b"")) <= 3 * (1 << bits)
                       or len(chunks[b"PLTE"]) % 3):
        raise RosterError("invalid indexed PNG palette")
    row_size = (width * channels * bits + 7) // 8
    expected = (row_size + 1) * height
    inflater = zlib.decompressobj()
    try:
        pixels = inflater.decompress(bytes(compressed), expected + 1)
    except zlib.error:
        raise RosterError("invalid PNG compressed data") from None
    if len(pixels) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise RosterError("invalid PNG decoded pixel length")
    rows, previous = [], bytes(row_size)
    step = max(1, (channels * bits + 7) // 8)
    for y in range(height):
        method = pixels[y * (row_size + 1)]
        if method > 4:
            raise RosterError("invalid PNG scanline filter")
        row = bytearray(pixels[y * (row_size + 1) + 1:(y + 1) * (row_size + 1)])
        for x in range(row_size):
            left, up, corner = row[x - step] if x >= step else 0, previous[x], previous[x - step] if x >= step else 0
            p = left + up - corner
            distances = abs(p - left), abs(p - up), abs(p - corner)
            paeth = (left, up, corner)[distances.index(min(distances))]
            row[x] = (row[x] + (0, left, up, (left + up) // 2, paeth)[method]) & 255
        rows.append(bytes(row))
        previous = row
    return width, height, bits, color, chunks, rows


def gba_asset(raw: bytes, *, width: int, height: int) -> tuple[bytes, bytes]:
    actual_w, actual_h, bits, color, chunks, rows = decode_png(raw)
    if (actual_w, actual_h, bits, color) != (width, height, 4, 3):
        raise RosterError("game PNG requires the specified dimensions and indexed 4-bit pixels")
    colors = chunks.get(b"PLTE", b"")
    if len(colors) != 48 or any(channel & 7 for channel in colors) or chunks.get(b"tRNS") != b"\0":
        raise RosterError("game PNG needs sixteen RGB555 colors and only transparent index zero")
    indexed = [[n for byte in row for n in (byte >> 4, byte & 15)] for row in rows]
    if not any(0 in row for row in indexed) or not any(any(row) for row in indexed):
        raise RosterError("game PNG must contain visible pixels and transparent background")
    if width == 32 and height == 64 and any(not any(any(row) for row in indexed[y:y + 32]) for y in (0, 32)):
        raise RosterError("both icon frames require visible pixels")
    tiles = bytes(indexed[y][x] | (indexed[y][x + 1] << 4)
                  for ty in range(0, height, 8) for tx in range(0, width, 8)
                  for y in range(ty, ty + 8) for x in range(tx, tx + 8, 2))
    palette = b"".join(struct.pack("<H", colors[i] >> 3 | (colors[i + 1] >> 3) << 5 | (colors[i + 2] >> 3) << 10)
                       for i in range(0, 48, 3))
    return tiles, palette


@contextmanager
def _lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".roster.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def verify_package(directory: Path | str) -> dict:
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    claimed = manifest.get("package_sha256")
    if claimed != digest({k: v for k, v in manifest.items() if k != "package_sha256"}):
        raise RosterError("roster package binding changed")
    if (manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), dict)
            or type(manifest.get("roster_id")) is not int or not 2 <= manifest["roster_id"] <= 65535
            or set(manifest["files"]) != {"source-art.png", "expression.json", "provenance.json", "front.png", "back.png", "icon.png",
                                        "front.4bpp", "back.4bpp", "icon.4bpp", "palette.gbapal", "icon.gbapal"}):
        raise RosterError("unsupported roster package")
    blobs = {}
    for name, checksum in manifest["files"].items():
        if not re.fullmatch(r"[a-z0-9_.-]+", name):
            raise RosterError("invalid package filename")
        blobs[name] = read_bytes(directory / name, MAX_IMAGE)
        if sha256(blobs[name]).hexdigest() != checksum:
            raise RosterError("roster asset checksum changed")
    try:
        decode_png(blobs["source-art.png"])
        for role, width, height in (("front", 64, 64), ("back", 64, 64), ("icon", 32, 64)):
            tiles, palette = gba_asset(blobs[role + ".png"], width=width, height=height)
            if tiles != blobs[role + ".4bpp"] or palette != blobs["icon.gbapal" if role == "icon" else "palette.gbapal"]:
                raise RosterError("roster PNG and GBA assets disagree")
        profile = ExpressionProfile.model_validate_json(blobs["expression.json"])
        if (profile.individual_id != manifest["individual_id"] or profile.profile_id != manifest["profile_id"]
                or profile.provenance.genome_sha256 != manifest["genome_sha256"]
                or profile.provenance.context_sha256 != manifest["context_sha256"]
                or sha256(Genotype.from_dict(manifest["genotype"]).pack()).hexdigest() != manifest["genome_sha256"]):
            raise RosterError("roster expression/genome binding changed")
        provenance = json.loads(blobs["provenance.json"])
        if (digest(provenance["context"]) != manifest["context_sha256"]
                or provenance["profile"] != profile.model_dump(mode="json")
                or provenance["artwork"]["image_sha256"] != manifest["files"]["source-art.png"]
                or manifest["source_art_sha256"] != manifest["files"]["source-art.png"]
                or provenance["context"]["individual"]["parents"] != manifest["parents"]
                or provenance["context"]["individual"]["generation"] != manifest["generation"]):
            raise RosterError("roster source or pedigree provenance changed")
    except KeyError:
        raise RosterError("roster package is missing required assets") from None
    return manifest


def export_completed(store: BreedingStore, request_key: str, roster_directory: Path | str, *,
                     front: Path | str, back: Path | str, icon: Path | str,
                     display_name: str, review_note: str, revision_id: str | None = None) -> dict:
    """Freeze reviewed game assets; source image acceptance alone is insufficient."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 -]{0,9}", display_name):
        raise RosterError("display name must fit ten GBA-safe characters")
    if not isinstance(review_note, str) or not 8 <= len(review_note.strip()) <= 512:
        raise RosterError("record a bounded note confirming visual review")
    if store.status(request_key)["state"] != "completed":
        raise RosterError("only completed breeding requests can enter the compiled roster")
    saved = store.inspect(request_key)
    if revision_id is not None:
        from genetics.edits import EditStore
        saved = EditStore(store).completed(revision_id)
        if saved["context"]["individual"]["id"] != store.status(request_key)["individual_id"]:
            raise RosterError("edit revision belongs to a different individual")
    individual = saved["context"]["individual"]
    profile = ExpressionProfile.model_validate(saved["profile"])
    blobs = {"source-art.png": read_bytes(saved["image_path"], MAX_IMAGE),
             "expression.json": canonical(saved["profile"]),
             "provenance.json": canonical({key: value for key, value in saved.items() if key != "image_path"})}
    decode_png(blobs["source-art.png"])
    palettes = []
    for role, path, width, height in (("front", front, 64, 64), ("back", back, 64, 64), ("icon", icon, 32, 64)):
        blobs[role + ".png"] = read_bytes(path, MAX_IMAGE)
        blobs[role + ".4bpp"], palette = gba_asset(blobs[role + ".png"], width=width, height=height)
        palettes.append(palette)
    if palettes[0] != palettes[1]:
        raise RosterError("front and back sprites must use the same palette")
    blobs["palette.gbapal"] = palettes[0]
    blobs["icon.gbapal"] = palettes[2]
    identity = individual["id"] + ("-" + revision_id if revision_id else "")
    directory = Path(roster_directory).resolve()
    with _lock(directory):
        entries = [verify_package(path.parent) for path in sorted(directory.glob("*/manifest.json"))]
        ids = [entry["roster_id"] for entry in entries]
        if sorted(ids) != list(range(2, 2 + len(ids))):
            raise RosterError("compiled roster slots must remain contiguous and append-only from two")
        prior = next((entry for entry in entries if entry["identity_key"] == identity), None)
        slot = prior["roster_id"] if prior else len(entries) + 2
        if slot > 65535:
            raise RosterError("compiled roster is full")
        manifest = {"schema_version": 1, "roster_id": slot, "identity_key": identity,
                    "individual_id": individual["id"], "revision_id": revision_id, "display_name": display_name,
                    "genotype": individual["genotype"], "genome_sha256": individual["genome_sha256"],
                    "parents": individual["parents"], "generation": individual["generation"],
                    "profile_id": profile.profile_id, "context_sha256": digest(saved["context"]),
                    "queue_request_key": request_key, "source_art_sha256": sha256(blobs["source-art.png"]).hexdigest(),
                    "source_art_role": "retained_generation_result_not_game_sprite",
                    "icon_palette_index": 3, "icon_palette_requirement": "caller_must_match_compiled_global_palette_3",
                    "review_note": review_note, "aurora_sensitivity": profile.expression.scores.aurora_sensitivity,
                    "files": {name: sha256(raw).hexdigest() for name, raw in blobs.items()}}
        manifest["package_sha256"] = digest(manifest)
        output = directory / f"{slot:05d}-{identity}"
        if prior is not None and prior != manifest:
            raise RosterError("accepted roster identity cannot be replaced; create an explicit edit revision")
        for name, raw in blobs.items():
            _publish(output / name, raw)
        _publish(output / "manifest.json", canonical(manifest) + b"\n")
        verify_package(output)
    return {"package_directory": str(output), **manifest}
