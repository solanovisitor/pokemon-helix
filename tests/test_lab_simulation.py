"""Exact arithmetic, replay, bounds, and tampering checks for the public assay."""
from __future__ import annotations

import copy
from fractions import Fraction
import hashlib
import random
import unittest

from genetics.lab_simulation import (MAX_REQUEST_BYTES, MAX_RESULT_BYTES,
                                    canonical, indicator_signal, simulate, verify_result)

BINDINGS = {"request_id": "synthetic-1", "save_lineage": "fixture-branch",
            "individual_id": "companion-a", "snapshot_sha256": "a1" * 32,
            "quest_revision": 7}


class LabSimulationTests(unittest.TestCase):
    def test_complete_domain_matches_exact_fraction_and_monotonicity(self):
        previous = -1
        for stimulus in range(1001):
            exact = Fraction(10) + Fraction(80 * stimulus**2, 500**2 + stimulus**2)
            expected = (exact + Fraction(1, 2)).numerator // (exact + Fraction(1, 2)).denominator
            actual = indicator_signal(stimulus)
            self.assertEqual(actual, expected)
            self.assertGreaterEqual(actual, previous)
            self.assertLess(actual, 90)
            previous = actual
        self.assertEqual([indicator_signal(s) for s in (0, 500, 1000)], [10, 50, 74])

    def test_frozen_vectors_and_controlled_equal_perturbation(self):
        first = simulate("sheltered", "stable", BINDINGS)
        second = simulate("exposed", "sensitive", BINDINGS)
        self.assertEqual((first["values"], first["signal"], first["span"], first["result_code"]),
                         ([10, 11, 13], 11, 3, 1))
        self.assertEqual((second["values"], second["signal"], second["span"], second["result_code"]),
                         ([46, 50, 54], 50, 8, 2))
        for result in (first, second):
            self.assertEqual(result["control"], 10)
            self.assertEqual([x - result["stimuli"][1] for x in result["stimuli"]], [-50, 0, 50])

    def test_prediction_only_changes_feedback_and_commitment(self):
        first = simulate("exposed", "stable", BINDINGS)
        second = simulate("exposed", "sensitive", BINDINGS)
        for key in ("values", "signal", "span", "control", "result_code", "interpretation"):
            self.assertEqual(first[key], second[key])
        self.assertFalse(first["prediction_match"])
        self.assertTrue(second["prediction_match"])

    def test_replay_rng_independence_and_input_ownership(self):
        value = copy.deepcopy(BINDINGS)
        first = simulate("sheltered", "stable", value)
        random.seed(731)
        for _ in range(19):
            random.random()
        self.assertEqual(first, simulate("sheltered", "stable", BINDINGS))
        self.assertEqual(value, BINDINGS)
        value["quest_revision"] = 8
        self.assertEqual(first["request"]["bindings"]["quest_revision"], 7)
        verify_result(first, "sheltered", "stable", BINDINGS)
        with self.assertRaises(ValueError):
            verify_result(first, "sheltered", "stable", value)

    def test_unknown_and_invalid_input_fail_closed(self):
        for value in (True, False, -1, 1001, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                indicator_signal(value)
        for patch in ({"request_id": "x" * 65}, {"request_id": "bad\ncommand"},
                      {"save_lineage": "naïve"}, {"individual_id": ""},
                      {"snapshot_sha256": "FF" * 32}, {"quest_revision": True},
                      {"quest_revision": 65536}, {"action": "edit_genome"}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                simulate("sheltered", "stable", BINDINGS | patch)
        for condition, prediction in (("unknown", "stable"), ("exposed", "perfect"),
                                      ([], "stable"), ("exposed", {})):
            with self.assertRaises(ValueError):
                simulate(condition, prediction, BINDINGS)

    def test_rehashed_physical_result_still_refused(self):
        result = simulate("exposed", "sensitive", BINDINGS)
        for patch in ({"signal": 51}, {"result_code": True}, {"arbitrary_effect": "reward"},
                      {"model": "helix-indicator-hill-v2"}, {"prediction_match": 1}):
            changed = result | patch
            changed.pop("result_sha256")
            changed["result_sha256"] = hashlib.sha256(canonical(changed)).hexdigest()
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                verify_result(changed, "exposed", "sensitive", BINDINGS)

    def test_maximum_valid_bindings_fit_payload(self):
        value = BINDINGS | {key: "x" * 64 for key in ("request_id", "save_lineage", "individual_id")}
        value["quest_revision"] = 65535
        result = simulate("sheltered", "sensitive", value)
        self.assertLessEqual(len(canonical(result["request"])), MAX_REQUEST_BYTES)
        self.assertLessEqual(len(canonical(result)), MAX_RESULT_BYTES)
        with self.assertRaises(ValueError):
            verify_result(result | {"extra": "x" * MAX_RESULT_BYTES}, "sheltered", "sensitive", value)


if __name__ == "__main__":
    unittest.main()
