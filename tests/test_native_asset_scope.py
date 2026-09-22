"""Synthetic regressions for scope leakage and transparent native backdrops.

Run with: uv run --offline --with pillow==11.3.0 python -m unittest
tests.test_native_asset_scope -v. No ROM, catalog download or save is needed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest

try:
    from PIL import Image
except ImportError:
    Image = None

if Image is not None:
    spec = importlib.util.spec_from_file_location(
        "native_scope", Path(__file__).resolve().parents[1] / "scripts/verify-native-assets-scope-v1.py")
    scope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scope)


@unittest.skipIf(Image is None, "Use uv run --with pillow==11.3.0 for native art scope tests")
class NativeAssetScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="helix-native-scope-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base, self.game = self.root / "before", self.root / "after"
        self.layouts = []
        for name, layout_id, w, h, secondary in (
            ("HelixResearchPost", "LAYOUT_HELIX_RESEARCH_POST", 12, 10, "gTileset_GenericBuilding"),
            ("HelixLaboratory", "LAYOUT_LITTLEROOT_TOWN_PROFESSOR_BIRCHS_LAB", 13, 13, "gTileset_Lab"),
            ("OtherRoom", "LAYOUT_OTHER_ROOM", 2, 2, "gTileset_GenericBuilding"),
        ):
            folder = "LittlerootTown_ProfessorBirchsLab" if name == "HelixLaboratory" else name
            layout = dict(id=layout_id, name=folder + "_Layout", width=w, height=h,
                          primary_tileset="gTileset_Building", secondary_tileset=secondary,
                          border_filepath=f"data/layouts/{folder}/border.bin",
                          blockdata_filepath=f"data/layouts/{folder}/map.bin", layout_version="emerald")
            self.layouts.append(layout)
            # A protected opaque wall cell is outside every approved prop/floor.
            blocks = [0x3224] * w + [0x3223] * (w * (h - 1))
            self.write(self.base / layout["blockdata_filepath"], struct.pack("<" + "H" * len(blocks), *blocks))
            self.write(self.base / layout["border_filepath"], struct.pack("<H", 0x224))
            self.json(self.base / "data/maps" / name / "map.json",
                      dict(id="MAP_" + name, layout=layout_id, object_events=[], bg_events=[],
                           warp_events=[], coord_events=[]))
            self.write(self.base / "data/maps" / name / "scripts.inc", b".byte 0\n")
        self.json(self.base / "data/layouts/layouts.json", {"layouts": self.layouts})
        for folder in ("primary/building", "secondary/generic_building", "secondary/lab"):
            root = self.base / "data/tilesets" / folder
            image = Image.new("P", (128, 256), 0)
            image.putpalette([0, 0, 0, 240, 192, 136, 224, 200, 48] + [0] * 759)
            for y in range(8):
                for x in range(8):
                    image.putpixel((8 + x, y), 1)
                    image.putpixel((16 + x, y), 2)
            root.mkdir(parents=True)
            image.save(root / "tiles.png")
            metas = bytearray(struct.pack("<8H", *([0x6201] * 4 + [0x6200] * 4)) * 512)
            struct.pack_into("<4H", metas, 0x23 * 16, *([0x6202] * 4))
            self.write(root / "metatiles.bin", metas)
            self.write(root / "metatile_attributes.bin", b"\0" * 1024)
            for slot in range(16):
                self.write(root / f"palettes/{slot:02}.pal",
                           ("JASC-PAL\n0100\n16\n0 0 0\n240 192 136\n224 200 48\n" + "0 0 0\n" * 13).encode())
        shutil.copytree(self.base, self.game)
        for before, after in (("generic_building", "helix_assets_post"), ("lab", "helix_assets_lab")):
            shutil.copytree(self.game / "data/tilesets/secondary" / before,
                            self.game / "data/tilesets/secondary" / after)
        post_meta = self.game / "data/tilesets/secondary/helix_assets_post/metatiles.bin"
        data = bytearray(post_meta.read_bytes())
        struct.pack_into("<4H", data, 0x23 * 16, *([0x6201] * 4))
        post_meta.write_bytes(data)
        candidate = json.loads(json.dumps(self.layouts))
        candidate[0]["secondary_tileset"] = "gTileset_HelixAssetsPost"
        clone = dict(candidate[1], id="LAYOUT_HELIX_ASSETS_LABORATORY", name="HelixAssetsLaboratory_Layout",
                     secondary_tileset="gTileset_HelixAssetsLab",
                     border_filepath="data/layouts/HelixAssetsLaboratory/border.bin",
                     blockdata_filepath="data/layouts/HelixAssetsLaboratory/map.bin")
        for field in ("blockdata_filepath", "border_filepath"):
            self.write(self.game / clone[field], (self.base / candidate[1][field]).read_bytes())
        candidate.append(clone)
        self.json(self.game / "data/layouts/layouts.json", {"layouts": candidate})
        header = self.game / "data/maps/HelixLaboratory/map.json"
        data = json.loads(header.read_text())
        data["layout"] = clone["id"]
        self.json(header, data)

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    @classmethod
    def json(cls, path, value):
        cls.write(path, (json.dumps(value, indent=2) + "\n").encode())

    def test_scoped_opaque_backdrop_and_cloned_layout_pass(self):
        self.assertEqual(scope.check_map_graph(self.base, self.game), 3)
        self.assertEqual(scope.check_original_tilesets(self.base, self.game), 57)
        result = scope.check_render_scope(self.base, self.game)
        self.assertTrue(all(item["opaque_pixels_preserved"] for item in result))

    def test_transparent_lower_refs_are_rejected_even_inside_allowed_floor(self):
        path = self.game / "data/tilesets/secondary/helix_assets_post/metatiles.bin"
        data = bytearray(path.read_bytes())
        struct.pack_into("<4H", data, 0x23 * 16, *([0x6200] * 4))
        path.write_bytes(data)
        with self.assertRaisesRegex(AssertionError, "Opaque native scene became transparent"):
            scope.check_render_scope(self.base, self.game)

    def test_clone_assigned_to_another_map_is_rejected(self):
        path = self.game / "data/maps/OtherRoom/map.json"
        header = json.loads(path.read_text())
        header["layout"] = "LAYOUT_HELIX_ASSETS_LABORATORY"
        self.json(path, header)
        with self.assertRaisesRegex(AssertionError, "Unrelated map binding or script changed"):
            scope.check_map_graph(self.base, self.game)

    def test_opaque_pixel_change_outside_allowed_cells_is_rejected(self):
        path = self.game / "data/tilesets/secondary/helix_assets_post/tiles.png"
        image = Image.open(path).copy()
        image.putpixel((8, 0), 2)
        image.save(path)
        with self.assertRaisesRegex(AssertionError, "outside reviewed cells"):
            scope.check_render_scope(self.base, self.game)

    def test_shared_original_tileset_mutation_is_rejected(self):
        path = self.game / "data/tilesets/secondary/generic_building/metatile_attributes.bin"
        path.write_bytes(b"\x01" + path.read_bytes()[1:])
        with self.assertRaisesRegex(AssertionError, "Shared original tileset changed"):
            scope.check_original_tilesets(self.base, self.game)

    def test_existing_layout_order_change_is_rejected(self):
        path = self.game / "data/layouts/layouts.json"
        data = json.loads(path.read_text())
        data["layouts"][0], data["layouts"][1] = data["layouts"][1], data["layouts"][0]
        self.json(path, data)
        with self.assertRaisesRegex(AssertionError, "Existing layout identity, order"):
            scope.check_map_graph(self.base, self.game)

    def test_collision_change_is_rejected(self):
        path = self.game / "data/layouts/HelixResearchPost/map.bin"
        data = bytearray(path.read_bytes())
        value = struct.unpack_from("<H", data, 24)[0]
        struct.pack_into("<H", data, 24, value ^ 0x0400)
        path.write_bytes(data)
        with self.assertRaisesRegex(AssertionError, "collision"):
            scope.check_map_graph(self.base, self.game)

    def test_lab_event_mutation_is_rejected(self):
        path = self.game / "data/maps/HelixLaboratory/map.json"
        data = json.loads(path.read_text())
        data["object_events"].append(dict(x=1, y=2, script="NewEvent"))
        self.json(path, data)
        with self.assertRaisesRegex(AssertionError, "Laboratory events"):
            scope.check_map_graph(self.base, self.game)


if __name__ == "__main__":
    unittest.main()
