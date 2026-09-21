"""Exercise the public entry point with synthetic configuration and no services."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from companion.demo import DEFAULT_PREDICTIONS, load_predictions, run_demo

ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    def test_module_outputs_complete_identical_json(self):
        command = [sys.executable, "-m", "companion.demo", "--json"]
        first = subprocess.check_output(command, cwd=ROOT)
        second = subprocess.check_output(command, cwd=ROOT)
        self.assertEqual(first, second)
        report = json.loads(first)
        self.assertTrue(report["synthetic"])
        self.assertEqual([row["signal"] for row in report["observations"]], [11, 50])
        self.assertEqual([row["span"] for row in report["observations"]], [3, 8])
        for row in report["observations"]:
            self.assertEqual(row["request"]["bindings"]["individual_id"], "public-demo-no-pokemon")
            self.assertEqual(len(row["result_sha256"]), 64)

    def test_example_matches_default(self):
        self.assertEqual(load_predictions(ROOT / "examples/lab-demo.toml"), DEFAULT_PREDICTIONS)

    def test_wrong_prediction_preserves_observation(self):
        first = run_demo(DEFAULT_PREDICTIONS)
        wrong = run_demo({"sheltered": "sensitive", "exposed": "stable"})
        for expected, observed in zip(first["observations"], wrong["observations"]):
            self.assertEqual(expected["values"], observed["values"])
            self.assertFalse(observed["prediction_match"])
            self.assertNotEqual(expected["result_sha256"], observed["result_sha256"])

    def test_config_rejects_extra_or_invalid_data(self):
        for content in (
            '[predictions]\nsheltered="stable"\nexposed="sensitive"\naction="edit"',
            '[predictions]\nsheltered="stable"',
            '[predictions]\nsheltered=true\nexposed="sensitive"',
            '[predictions]\nsheltered="perfect"\nexposed="sensitive"',
            '[credentials]\ntoken="synthetic-placeholder"',
            '[predictions',
            "#" * 4097,
        ):
            with self.subTest(content=content[:80]), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "demo.toml"
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_predictions(path)

    def test_cli_invalid_config_is_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "demo.toml"
            path.write_text('[predictions]\nsheltered="unknown"\nexposed="stable"')
            result = subprocess.run([sys.executable, "-m", "companion.demo", "--config", str(path)],
                                    cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("predictions must be stable or sensitive", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
