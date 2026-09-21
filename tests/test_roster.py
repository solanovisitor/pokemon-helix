"""Offline checks for reviewed packages and immutable compiled identities."""
from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from genetics.breeding import BreedingError, BreedingStore
from genetics.engine import run_experiment
from genetics.expression import fixture_expression
from genetics.models import SpeciesConfig
from genetics.reference import load_reference
from genetics.roster import RosterError, decode_png, export_completed, gba_asset, verify_package


def png(width=64, height=64, value=1, color_shift=0):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    palette = bytes((i * 8 + color_shift) % 256 for i in range(48))
    rows = [bytes([0]) + bytes([0 if y in (0, height - 1) or x == 0 else value * 17 for x in range(width // 2)]) for y in range(height)]
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 4, 3, 0, 0, 0))
            + chunk(b"PLTE", palette) + chunk(b"tRNS", b"\0") + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))


class RosterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = run_experiment(species=SpeciesConfig.from_reference(load_reference()), population_size=2, generations=1)["generation_requests"]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = BreedingStore(self.root / "store")
        source = self.root / "source.png"
        source.write_bytes(png())
        self.parents = [self.store.register_parent(j["context"], fixture_expression(j), source,
                        image_sha256=sha256(source.read_bytes()).hexdigest()) for j in self.jobs[:2]]
        for name, width in (("front", 64), ("back", 64), ("icon", 32)):
            (self.root / (name + ".png")).write_bytes(png(width, color_shift=8 if name == "icon" else 0))
        self.store.enqueue("child", self.parents, seed=22)
        self.store.work_expression("child")
        reservation = self.store.start_art("child", tool="fixture", model="fixture")
        self.store.accept_art("child", attempt_token=reservation["attempt"], image_path=source)

    def export(self, **options):
        values = dict(front=self.root / "front.png", back=self.root / "back.png", icon=self.root / "icon.png",
                      display_name="Auralin", review_note="Reviewed fixture sprites and transparent edges.")
        values.update(options)
        return export_completed(self.store, "child", self.root / "roster", **values)

    def test_export_reopen_exact_gba_bytes_and_separate_source_role(self):
        first = self.export()
        self.assertEqual(first["roster_id"], 2)
        self.assertEqual(first, self.export())
        package = Path(first["package_directory"])
        result = verify_package(package)
        self.assertEqual(result["source_art_role"], "retained_generation_result_not_game_sprite")
        self.assertEqual(len((package / "front.4bpp").read_bytes()), 2048)
        self.assertEqual(len((package / "icon.4bpp").read_bytes()), 1024)
        self.assertNotEqual((package / "palette.gbapal").read_bytes(), (package / "icon.gbapal").read_bytes())
        self.assertEqual(result["individual_id"], self.store.status("child")["individual_id"])

    def test_cannot_replace_accepted_assets_or_repair_corruption(self):
        result = self.export()
        (self.root / "front.png").write_bytes(png(value=2))
        with self.assertRaisesRegex(RosterError, "cannot be replaced"):
            self.export()
        package = Path(result["package_directory"])
        (package / "back.4bpp").write_bytes(bytes(2048))
        with self.assertRaisesRegex(RosterError, "checksum changed"):
            verify_package(package)

    def test_decodes_pixels_and_rejects_corrupt_stream_dimensions_transparency(self):
        for raw in (png()[:-2], png() + b"trailing", png()[:70] + b"broken" + png()[76:]):
            with self.assertRaises(RosterError):
                decode_png(raw)
        for raw in (png(32, 64), png(value=0), png(color_shift=1)):
            with self.assertRaises(RosterError):
                gba_asset(raw, width=64, height=64)
        (self.root / "back.png").write_bytes(png(color_shift=8))
        with self.assertRaisesRegex(RosterError, "same palette"):
            self.export()

    def test_append_only_slots_and_pending_child_rejected(self):
        first = self.export()
        self.store.enqueue("pending", self.parents, seed=23)
        with self.assertRaisesRegex(RosterError, "completed"):
            export_completed(self.store, "pending", self.root / "roster", front=self.root / "front.png",
                             back=self.root / "back.png", icon=self.root / "icon.png", display_name="Pending",
                             review_note="Reviewed pending fixtures.")
        self.store.work_expression("pending")
        reservation = self.store.start_art("pending", tool="fixture", model="fixture")
        self.store.accept_art("pending", attempt_token=reservation["attempt"], image_path=self.root / "source.png")
        next_one = export_completed(self.store, "pending", self.root / "roster", front=self.root / "front.png",
                                   back=self.root / "back.png", icon=self.root / "icon.png", display_name="Next",
                                   review_note="Reviewed pending fixtures.")
        self.assertEqual(next_one["roster_id"], 3)
        self.assertEqual(self.export(), first)
