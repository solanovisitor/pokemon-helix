"""Synthetic wire validation and durable journal checks; no emulator required."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from companion.lab_service import LabService, parse
from genetics.lab_simulation import canonical

SESSION = "0123456789abcdef" * 2 + "-1"


def context(sequence=1, condition=1):
    body = (struct.pack("<II6H", 123, sequence, 1, 0x7003, condition, 1, 1, 0)
            + bytes(range(16)) + bytes(range(32)) + struct.pack("<I", 0x89abcdef))
    return body + struct.pack("<I", zlib.crc32(body))


def frame(raw, kind="REQ"):
    return f"LAB1|{kind}|{SESSION}|{raw.hex()}\n".encode("ascii")


class LabServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.journal = Path(self.directory.name) / "synthetic.sqlite"
        self.service = LabService(self.journal)

    def test_parser_accepts_both_supported_conditions(self):
        for condition in (1, 2):
            raw = context(condition=condition)
            self.assertEqual(parse(frame(raw)), ("REQ", SESSION, raw))

    def test_parser_rejects_unknown_corrupt_or_oversized_frames(self):
        raw = context()
        for value in (frame(raw)[:-1], b"x" * 641 + b"\n",
                      frame(raw, "WRITE"), frame(raw).replace(b"LAB1", b"LAB2"),
                      frame(raw[:-1] + bytes([raw[-1] ^ 1])),
                      frame(context(condition=3)), frame(context(sequence=0)),
                      frame(raw).replace(SESSION.encode(), b"not-a-session")):
            with self.subTest(frame_length=len(value)), self.assertRaises(ValueError):
                parse(value)

    def test_complete_result_survives_restart_with_exact_replay(self):
        first = self.service.job(SESSION, context())
        self.assertEqual(first["signal"], 11)
        second = LabService(self.journal).job(SESSION, context())
        self.assertEqual(canonical(first), canonical(second))
        with sqlite3.connect(self.journal) as db:
            rows = db.execute("SELECT result,cancelled FROM jobs").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0][0]), first)
        self.assertEqual(rows[0][1], 0)

    def test_changed_context_cannot_reuse_a_request_identity(self):
        self.service.job(SESSION, context())
        with self.assertRaisesRegex(ValueError, "changed context"):
            self.service.job(SESSION, context(condition=2))

    def test_cancellation_before_computation_survives_restart(self):
        self.assertIsNone(self.service.job(SESSION, context(), cancel=True))
        self.assertIsNone(LabService(self.journal).job(SESSION, context()))
        with sqlite3.connect(self.journal) as db:
            self.assertEqual(db.execute("SELECT result,cancelled FROM jobs").fetchall(), [(None, 1)])

    def test_cancellation_after_computation_blocks_future_replay(self):
        self.service.job(SESSION, context())
        self.assertIsNone(self.service.job(SESSION, context(), cancel=True))
        self.assertIsNone(LabService(self.journal).job(SESSION, context()))

    def test_altered_retained_result_is_rejected(self):
        self.service.job(SESSION, context())
        with sqlite3.connect(self.journal) as db:
            db.execute("UPDATE jobs SET result=?", ('{"signal":99}',))
        with self.assertRaisesRegex(ValueError, "corrupt or version changed"):
            LabService(self.journal).job(SESSION, context())

    def test_full_journal_refuses_new_jobs_without_evicting_replay(self):
        with patch("companion.lab_service.MAX_JOBS", 1):
            first = self.service.job(SESSION, context())
            with self.assertRaisesRegex(ValueError, "full"):
                self.service.job(SESSION, context(sequence=2))
            self.assertEqual(self.service.job(SESSION, context()), first)


if __name__ == "__main__":
    unittest.main()
