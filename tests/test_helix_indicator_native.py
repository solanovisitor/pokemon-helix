"""Exact C/Python equivalence against independent Decimal/Fraction vectors.

The public overlay source and header are copied unchanged beside a minimal global.h
solely to supply the game's integer typedefs on a host C compiler.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from genetics.lab_simulation import indicator_signal, simulate

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests/fixtures/helix-indicator-hill-v1.json"
BINDINGS = {"request_id": "native-equivalence-v18", "save_lineage": "synthetic-branch",
            "individual_id": "synthetic-companion", "snapshot_sha256": "ab" * 32,
            "quest_revision": 7003}
STUB = """
#ifndef GUARD_GLOBAL_H
#define GUARD_GLOBAL_H
#include <stdint.h>
#include <stddef.h>
typedef uint8_t bool8;
typedef uint16_t u16;
typedef uint32_t u32;
#define TRUE 1
#define FALSE 0
#endif
"""
DRIVER = r"""
#include "helix_indicator_model.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>

int main(int argc, char **argv)
{
    struct HelixIndicatorAssayResult assay, before;
    u16 signal;
    u32 s, condition, prediction, i;
    const u32 invalid[] = {1001u, 65535u, 65536u, 100000u,
                          0x7fffffffu, 0x80000000u, 0xfffffffeu, 0xffffffffu};
    _Static_assert(sizeof(u32) == 4, "32-bit arithmetic");
    _Static_assert(sizeof(u16) == 2, "16-bit output");
    _Static_assert(sizeof(struct HelixIndicatorAssayResult) == 22, "bounded output");
    assert(argc == 2);
    if (!strcmp(argv[1], "domain"))
    {
        for (s = 0; s <= 1000; s++)
        {
            assert(HelixIndicatorSignal(s, &signal));
            printf("%u\n", signal);
        }
    }
    else if (!strcmp(argv[1], "assays"))
    {
        for (condition = 1; condition <= 2; condition++)
            for (prediction = 1; prediction <= 2; prediction++)
            {
                assert(HelixIndicatorAssay(condition, prediction, &assay));
                printf("%u %u %u %u %u %u %u %u %u %u %u\n",
                    assay.result, assay.stimuli[0], assay.stimuli[1], assay.stimuli[2],
                    assay.values[0], assay.values[1], assay.values[2],
                    assay.signal, assay.span, assay.control, assay.predictionMatch);
            }
    }
    else if (!strcmp(argv[1], "invalid"))
    {
        for (i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++)
        {
            signal = 0xa55a;
            assert(!HelixIndicatorSignal(invalid[i], &signal));
            assert(signal == 0xa55a);
        }
        for (s = 0; s <= 1000; s++)
            assert(!HelixIndicatorSignal(s, NULL));
        memset(&before, 0xa5, sizeof(before));
        for (s = 0; s <= 65535; s++)
        {
            if (s == 1 || s == 2) continue;
            for (i = 1; i <= 2; i++)
            {
                assay = before;
                assert(!HelixIndicatorAssay(s, i, &assay));
                assert(memcmp(&assay, &before, sizeof(assay)) == 0);
                assert(!HelixIndicatorAssay(i, s, &assay));
                assert(memcmp(&assay, &before, sizeof(assay)) == 0);
            }
        }
        for (condition = 1; condition <= 2; condition++)
            for (prediction = 1; prediction <= 2; prediction++)
                assert(!HelixIndicatorAssay(condition, prediction, NULL));
        puts("rejected=262136 null_signal=1001 boundary_signal=8 null_assay=4");
    }
    else return 2;
    return 0;
}
"""


class HelixIndicatorNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang") or shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a C compiler is required for indicator equivalence")
        cls.temporary = tempfile.TemporaryDirectory(prefix="helix-indicator-native-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        (cls.directory / "global.h").write_text(STUB)
        for source in (ROOT / "rom-source/overlay/src/helix_indicator_model.c",
                       ROOT / "rom-source/overlay/include/helix_indicator_model.h"):
            shutil.copyfile(source, cls.directory / source.name)
        (cls.directory / "driver.c").write_text(DRIVER)
        cls.binaries = []
        for optimization in ("-O0", "-O2"):
            binary = cls.directory / ("indicator" + optimization)
            result = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-fsanitize=undefined", "-fno-sanitize-recover=all", optimization,
                 str(cls.directory / "helix_indicator_model.c"),
                 str(cls.directory / "driver.c"), "-o", str(binary)],
                capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.binaries.append(binary)
        cls.vectors = json.loads(VECTORS.read_text())

    def run_c(self, mode):
        outputs = []
        for binary in self.binaries:
            result = subprocess.run([str(binary), mode], capture_output=True,
                                    text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1], "optimization-dependent result")
        return outputs[0]

    def test_all_1001_stimuli_match_frozen_independent_decimal_and_python(self):
        expected = self.vectors["signals"]
        self.assertEqual(len(expected), 1001)
        actual = [int(value) for value in self.run_c("domain").splitlines()]
        self.assertEqual(actual, expected)
        self.assertEqual(actual, [indicator_signal(s) for s in range(1001)])

    def test_frozen_vectors_rederive_with_fraction_and_decimal(self):
        with localcontext() as context:
            context.prec = 64
            for stimulus, expected in enumerate(self.vectors["signals"]):
                exact = Fraction(10) + Fraction(80 * stimulus**2, 500**2 + stimulus**2)
                rounded = exact + Fraction(1, 2)
                self.assertEqual(expected, rounded.numerator // rounded.denominator)
                signal = Decimal(10) + Decimal(80) * Decimal(stimulus)**2 / (
                    Decimal(500)**2 + Decimal(stimulus)**2)
                self.assertEqual(expected, int(signal.to_integral_value(rounding=ROUND_HALF_UP)))

    def test_all_protocols_and_predictions_equal_full_host_numeric_result(self):
        actual = [[int(value) for value in row.split()]
                  for row in self.run_c("assays").splitlines()]
        expected = []
        for condition in ("sheltered", "exposed"):
            for prediction in ("stable", "sensitive"):
                result = simulate(condition, prediction, BINDINGS)
                expected.append([result["result_code"], *result["stimuli"], *result["values"],
                                 result["signal"], result["span"], result["control"],
                                 int(result["prediction_match"])])
        self.assertEqual(actual, expected)
        self.assertEqual(actual, self.vectors["protocol_rows"])

    def test_unsupported_enums_nulls_and_overflow_boundaries_do_not_write(self):
        self.assertEqual(self.run_c("invalid").strip(),
                         "rejected=262136 null_signal=1001 boundary_signal=8 null_assay=4")

    def test_existing_python_model_and_canonical_receipts_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT / "genetics/lab_simulation.py").read_bytes()).hexdigest(),
                         self.vectors["v17_python_sha256"])
        receipts = [simulate(condition, prediction, BINDINGS)["result_sha256"]
                    for condition in ("sheltered", "exposed")
                    for prediction in ("stable", "sensitive")]
        self.assertEqual(receipts, self.vectors["v17_synthetic_receipt_sha256"])

    def test_analytic_bounds_monotonicity_and_rounding_transition_neighbors(self):
        values = self.vectors["signals"]
        self.assertEqual((values[0], values[500], values[1000]), (10, 50, 74))
        transitions = []
        for stimulus in range(1001):
            square = stimulus * stimulus
            self.assertLessEqual(square, 1_000_000)
            self.assertLessEqual(250_000 + square, 1_250_000)
            self.assertLessEqual(80 * square + (250_000 + square) // 2, 80_625_000)
            if stimulus:
                self.assertIn(values[stimulus] - values[stimulus - 1], (0, 1))
                if values[stimulus] != values[stimulus - 1]:
                    transitions.append(stimulus)
        self.assertEqual(len(transitions), 64)
        self.assertEqual(transitions, self.vectors["rounding_transition_stimuli"])


if __name__ == "__main__":
    unittest.main()
