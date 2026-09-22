#!/usr/bin/env python3
"""Independent map, tileset, pixel-scope and opacity guards for native batch one.

Run alongside verify-native-assets-v2.py, using the exact pre-integration source
as --baseline-game. This checker reads files only and makes no runtime claim.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import struct

from PIL import Image

PROPS = {
    "HelixResearchPost": ((2, 5, 2, 2), (8, 1, 1, 2), (9, 1, 1, 2)),
    "HelixLaboratory": ((3, 0, 2, 2), (1, 9, 1, 2)),
}
BACKDROP_METAS = {0x223, 0x298, 0x289, 0x28A}
TILESETS = {
    "gTileset_Building": "primary/building",
    "gTileset_GenericBuilding": "secondary/generic_building",
    "gTileset_Lab": "secondary/lab",
    "gTileset_HelixAssetsPost": "secondary/helix_assets_post",
    "gTileset_HelixAssetsLab": "secondary/helix_assets_lab",
}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def layouts(game):
    return json.loads((game / "data/layouts/layouts.json").read_text())["layouts"]


def map_data(game, name):
    header = json.loads((game / "data/maps" / name / "map.json").read_text())
    layout = next(item for item in layouts(game) if item["id"] == header["layout"])
    raw = (game / layout["blockdata_filepath"]).read_bytes()
    require(len(raw) == layout["width"] * layout["height"] * 2, "Map block geometry differs")
    return header, layout, struct.unpack("<" + "H" * (len(raw) // 2), raw)


def render_map(game, name):
    """Decode indexed tile refs independently of the converter's renderer."""
    _, layout, blocks = map_data(game, name)
    roots = [game / "data/tilesets" / TILESETS[layout[key]]
             for key in ("primary_tileset", "secondary_tileset")]
    sheets = [Image.open(folder / "tiles.png").copy() for folder in roots]
    require(all(image.mode == "P" for image in sheets), "Native sheets must be indexed")
    meta_data = [(folder / "metatiles.bin").read_bytes() for folder in roots]
    colors = []
    for slot in range(16):
        path = roots[int(slot >= 6)] / "palettes" / f"{slot:02}.pal"
        lines = path.read_text().splitlines()
        require(lines[:3] == ["JASC-PAL", "0100", "16"], "Invalid native palette")
        colors.append([tuple(map(int, line.split())) for line in lines[3:19]])
    image = Image.new("RGBA", (layout["width"] * 16, layout["height"] * 16))
    for cell, block in enumerate(blocks):
        meta = block & 1023
        refs = struct.unpack_from("<8H", meta_data[int(meta >= 512)], (meta % 512) * 16)
        for part, ref in enumerate(refs):
            tile = ref & 1023
            sheet = sheets[int(tile >= 512)]
            tile %= 512
            for y in range(8):
                for x in range(8):
                    sx = 7 - x if ref & 1024 else x
                    sy = 7 - y if ref & 2048 else y
                    index = sheet.getpixel(((tile % (sheet.width // 8)) * 8 + sx,
                                            (tile // (sheet.width // 8)) * 8 + sy))
                    if index:
                        image.putpixel(((cell % layout["width"]) * 16 + (part % 4 % 2) * 8 + x,
                                        (cell // layout["width"]) * 16 + (part % 4 // 2) * 8 + y),
                                       (*colors[ref >> 12][index], 255))
    return image


def check_map_graph(baseline, game):
    old, new = layouts(baseline), layouts(game)
    require(len(new) == len(old) + 1, "Exactly one appended laboratory layout is allowed")
    for before, after in zip(old, new):
        expected = dict(before)
        if before["id"] == "LAYOUT_HELIX_RESEARCH_POST":
            expected["secondary_tileset"] = "gTileset_HelixAssetsPost"
        require(after == expected, "Existing layout identity, order or unrelated binding changed")
        for key in ("blockdata_filepath", "border_filepath"):
            require((baseline / before[key]).read_bytes() == (game / after[key]).read_bytes(),
                    "Existing map blocks, collision, elevation or border changed")
    source = next(item for item in old if item["id"] == "LAYOUT_LITTLEROOT_TOWN_PROFESSOR_BIRCHS_LAB")
    expected = dict(source, id="LAYOUT_HELIX_ASSETS_LABORATORY", name="HelixAssetsLaboratory_Layout",
                    secondary_tileset="gTileset_HelixAssetsLab",
                    border_filepath="data/layouts/HelixAssetsLaboratory/border.bin",
                    blockdata_filepath="data/layouts/HelixAssetsLaboratory/map.bin")
    require(new[-1] == expected, "The appended laboratory clone differs from the existing room")
    for key in ("blockdata_filepath", "border_filepath"):
        require((baseline / source[key]).read_bytes() == (game / expected[key]).read_bytes(),
                "Cloned laboratory geometry changed")
    def source_maps(root):
        return {p.relative_to(root / "data/maps") for p in (root / "data/maps").rglob("*")
                if p.is_file() and (p.suffix == ".json" or p.name == "scripts.inc")}
    old_paths, new_paths = source_maps(baseline), source_maps(game)
    require(old_paths == new_paths, "Map definitions or scripts were added or removed")
    count = 0
    for path in sorted(old_paths):
        before, after = baseline / "data/maps" / path, game / "data/maps" / path
        if path == Path("HelixLaboratory/map.json"):
            original, actual = json.loads(before.read_text()), json.loads(after.read_text())
            original["layout"] = "LAYOUT_HELIX_ASSETS_LABORATORY"
            require(actual == original, "Laboratory events, scripts or properties changed")
        else:
            require(before.read_bytes() == after.read_bytes(), f"Unrelated map binding or script changed: {path}")
        count += path.name == "map.json"
    return count


def check_original_tilesets(baseline, game):
    original = {p.relative_to(baseline / "data/tilesets")
                for p in (baseline / "data/tilesets").rglob("*")
                if p.is_file() and p.suffix in (".png", ".pal", ".bin")}
    for path in original:
        target = game / "data/tilesets" / path
        require(target.is_file() and (baseline / "data/tilesets" / path).read_bytes() == target.read_bytes(),
                f"Shared original tileset changed: {path}")
    actual = {p.relative_to(game / "data/tilesets") for p in (game / "data/tilesets").rglob("*")
              if p.is_file() and p.suffix in (".png", ".pal", ".bin")}
    for path in actual - original:
        require(path.parts[:2] in (("secondary", "helix_assets_post"), ("secondary", "helix_assets_lab")),
                f"Unexpected additional tileset source: {path}")
    return len(original)


def check_c_bindings(baseline, game):
    for relative in ("include/tilesets.h", "src/data/tilesets/headers.h",
                     "src/data/tilesets/graphics.h", "src/data/tilesets/metatiles.h"):
        require((game / relative).read_bytes().startswith((baseline / relative).read_bytes()),
                f"Existing compiled tileset declarations changed: {relative}")
    headers = (game / "src/data/tilesets/headers.h").read_text()
    graphics = (game / "src/data/tilesets/graphics.h").read_text()
    metas = (game / "src/data/tilesets/metatiles.h").read_text()
    for suffix, folder in (("Post", "post"), ("Lab", "lab")):
        symbol = "HelixAssets" + suffix
        root = "data/tilesets/secondary/helix_assets_" + folder
        bodies = re.findall(r"const struct Tileset gTileset_" + symbol + r"\s*=\s*\{(.*?)\};", headers, re.S)
        require(len(bodies) == 1, "Missing or duplicate clone tileset declaration")
        fields = dict(re.findall(r"\.(\w+)\s*=\s*(\w+)", bodies[0]))
        require(fields == dict(isCompressed="TRUE", isSecondary="TRUE", callback="NULL",
                               tiles="gTilesetTiles_" + symbol, palettes="gTilesetPalettes_" + symbol,
                               metatiles="gMetatiles_" + symbol, metatileAttributes="gMetatileAttributes_" + symbol),
                "Clone tileset pointers or callback differ")
        tile_paths = re.findall(r"const u32 gTilesetTiles_" + symbol + r'\[\]\s*=\s*INCGFX_U32\("([^"]+)"', graphics)
        require(tile_paths == [root + "/tiles.png"], "Clone graphics path differs")
        palettes = re.findall(r"const u16 gTilesetPalettes_" + symbol + r"\[\]\[16\]\s*=\s*\{(.*?)\};", graphics, re.S)
        require(len(palettes) == 1 and re.findall(r'INCGFX_U16\("([^"]+)"', palettes[0]) ==
                [root + f"/palettes/{slot:02}.pal" for slot in range(16)], "Clone palette paths differ")
        for prefix, filename in (("gMetatiles_", "metatiles.bin"), ("gMetatileAttributes_", "metatile_attributes.bin")):
            paths = re.findall(r"const u16 " + prefix + symbol + r'\[\]\s*=\s*INCBIN_U16\("([^"]+)"', metas)
            require(paths == [root + "/" + filename], "Clone metatile/attribute path differs")


def check_render_scope(baseline, game):
    summaries = []
    for name, rectangles in PROPS.items():
        _, layout, cells = map_data(baseline, name)
        allowed = {(x, y) for xx, yy, w, h in rectangles
                   for y in range(yy, yy + h) for x in range(xx, xx + w)}
        if name == "HelixResearchPost":
            allowed |= {(i % layout["width"], i // layout["width"]) for i, cell in enumerate(cells)
                        if cell & 1023 in BACKDROP_METAS}
        old, new = render_map(baseline, name), render_map(game, name)
        require(old.size == new.size, "Rendered map dimensions changed")
        changed = set()
        for y in range(old.height):
            for x in range(old.width):
                before, after = old.getpixel((x, y)), new.getpixel((x, y))
                require(not (before[3] == 255 and after[3] != 255),
                        f"Opaque native scene became transparent: {name} pixel {(x, y)}")
                if before != after:
                    require((x // 16, y // 16) in allowed,
                            f"Rendered pixel outside reviewed cells changed: {name} pixel {(x, y)}")
                    changed.add((x // 16, y // 16))
        summaries.append(dict(map=name, allowed_cells=len(allowed), changed_cells=sorted(changed),
                              opaque_pixels_preserved=True, unrelated_pixels_exact=True))
    return summaries


def verify(baseline, game, conversion):
    baseline, game, conversion = baseline.resolve(), game.resolve(), conversion.resolve()
    require(baseline != game, "Use an independent pre-integration baseline")
    report = json.loads((conversion / "conversion.json").read_text())
    require(report["schema"] == 2 and report["native_background_repair"]["affected_map_cells"] == 66,
            "Use the reviewed successor conversion")
    result = dict(schema=1, result="passed-independent-map-scope-and-opacity-guards",
                  source_map_definitions_checked=check_map_graph(baseline, game),
                  original_shared_tileset_files_unchanged=check_original_tilesets(baseline, game))
    check_c_bindings(baseline, game)
    result.update(compiled_source_bindings_preserved=True, maps=check_render_scope(baseline, game),
                  conversion_sha256=digest(conversion / "conversion.json"),
                  checker_sha256=digest(Path(__file__)),
                  runtime_acceptance="Separate exact-ROM mGBA evidence is required; other environments are source-guarded.")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-game", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True)
    parser.add_argument("--conversion", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(verify(args.baseline_game, args.game, args.conversion), indent=2, sort_keys=True) + "\n"
    if args.output:
        with args.output.open("x") as stream:
            stream.write(output)
    print(output, end="")
