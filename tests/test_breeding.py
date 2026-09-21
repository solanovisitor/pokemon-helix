from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.openrouter_policy import openrouter_policy_fingerprint
from genetics.breeding import BreedingError, BreedingStore
from genetics.engine import run_experiment
from genetics.expression import fixture_expression
from genetics.models import SpeciesConfig
from genetics.reference import load_reference

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfN8AAAAASUVORK5CYII=")


class BreedingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = run_experiment(species=SpeciesConfig.from_reference(load_reference()),
                                  population_size=2, generations=1)["generation_requests"]
        cls.profiles = [fixture_expression(job) for job in cls.jobs[:2]]

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "parent.png"
        self.source.write_bytes(PNG)
        self.store = BreedingStore(self.root / "store")
        self.parents = [self.store.register_parent(j["context"], p, self.source, image_sha256=sha256(PNG).hexdigest())
                        for j, p in zip(self.jobs, self.profiles)]

    def enqueue(self, key="egg-one"):
        return self.store.enqueue(key, self.parents, seed=20260920)

    def ready_for_art(self, key="egg-one"):
        self.enqueue(key)
        self.store.work_expression(key)
        return self.store.start_art(key, model="authored-test-image-v1", tool="fixture")

    def test_offline_intent_is_durable_idempotent_and_copies_parent_pixels(self):
        with patch("genetics.expression.build_opener") as network:
            first = self.enqueue()
            self.source.unlink()
            resumed = BreedingStore(self.store.directory)
            self.assertEqual(resumed.enqueue("egg-one", self.parents, seed=20260920), first)
            self.assertEqual(first["state"], "pending_expression")
            self.assertEqual(first["rom_adoption"], "requires_reviewed_export_and_rom_rebuild")
            self.assertEqual(resumed.work_expression("egg-one")["state"], "pending_art")
            network.assert_not_called()
        with self.assertRaisesRegex(BreedingError, "different breeding intent"):
            self.store.enqueue("egg-one", self.parents, seed=9)
        other = self.enqueue("egg-two")
        self.assertNotEqual(other["individual_id"], first["individual_id"])
        self.assertEqual(other["genotype"], first["genotype"])

    def test_inheritance_and_accepted_child_can_parent_another_generation(self):
        reservation = self.ready_for_art()
        result = self.store.accept_art("egg-one", attempt_token=reservation["attempt"], image_path=self.source)
        next_child = self.store.enqueue("grandchild", [result["individual_id"], self.parents[1]], seed=11)
        context = self.store.inspect("grandchild")["context"]
        self.assertEqual(context["individual"]["generation"], 2)
        self.assertEqual(next_child["parents"][0], result["individual_id"])
        self.assertEqual(self.store.work_expression("grandchild")["state"], "pending_art")
        request = self.store.inspect("grandchild")["art_request"]
        self.assertIn(result["individual_id"], request["prompt"])
        self.assertNotIn(str(self.root), request["prompt"])

    def test_live_worker_supplies_real_parent_pixels_profiles_and_one_bounded_call(self):
        self.enqueue()
        body = self.profiles[0].expression.model_dump()
        body["scores"]["curiosity"] = 74
        response = io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}]}).encode())
        with patch("genetics.expression.build_opener") as provider:
            provider.return_value.open.return_value = response
            self.store.work_expression("egg-one", mode="openrouter", key="SECRET_KEY", model="test/vision", timeout=9)
        call = provider.return_value.open.call_args
        self.assertEqual(call.kwargs["timeout"], 9)
        payload = json.loads(call.args[0].data)
        content = payload["messages"][1]["content"]
        self.assertEqual(sum(p["type"] == "image_url" for p in content), 2)
        self.assertEqual(payload["max_tokens"], 1500)
        self.assertIn(self.profiles[0].profile_id, content[0]["text"])
        self.assertNotIn(str(self.root), json.dumps(payload))
        saved = self.store.inspect("egg-one")
        self.assertEqual(saved["profile"]["expression"]["scores"]["curiosity"], 74)
        self.assertEqual(saved["profile"]["provenance"]["visual_context"], "profiles_and_pixels")
        policy = openrouter_policy_fingerprint("test/vision")
        self.assertEqual(saved["profile"]["provenance"]["provider_policy_sha256"], policy)
        self.assertEqual(saved["attempts"][0]["request"]["provider_policy_sha256"], policy)
        self.assertNotIn("SECRET_KEY", json.dumps(saved))
        self.assertNotIn(b"SECRET_KEY", self.store.database.read_bytes())
        self.assertEqual(provider.return_value.open.call_count, 1)

    def crashed_live_attempt(self, key):
        self.enqueue(key)
        body = self.profiles[0].expression.model_dump()
        response = io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(body)}}]}).encode())
        with patch("genetics.expression.build_opener") as provider, \
                patch.object(self.store, "recover_expression", side_effect=RuntimeError("synthetic crash")):
            provider.return_value.open.return_value = response
            with self.assertRaises(BreedingError):
                self.store.work_expression(key, mode="openrouter", key="synthetic", model="test/vision")
        self.assertEqual(provider.return_value.open.call_count, 1)
        attempt = self.store.inspect(key)["attempts"][0]
        path = self.store.directory / "attempts" / (attempt["token"] + ".json")
        return attempt, path

    def test_live_recovery_uses_reserved_policy_after_default_changes_without_reinvocation(self):
        attempt, path = self.crashed_live_attempt("policy-recovery")
        reserved = attempt["request"]["provider_policy_sha256"]
        before = path.read_bytes()
        with patch("companion.openrouter_policy.POLICY_VERSION", "future-policy"), \
                patch("genetics.expression.build_opener", side_effect=AssertionError("network forbidden")):
            self.assertNotEqual(openrouter_policy_fingerprint("test/vision"), reserved)
            resumed = BreedingStore(self.store.directory)
            self.assertEqual(resumed.recover_expression("policy-recovery")["state"], "pending_art")
        saved = self.store.inspect("policy-recovery")
        self.assertEqual(saved["profile"]["provenance"]["provider_policy_sha256"], reserved)
        self.assertEqual(len(saved["attempts"]), 1)
        self.assertEqual(path.read_bytes(), before)

    def test_policy_mismatches_refuse_recovery_but_legacy_absence_stays_valid(self):
        for variant in ("wrong-result", "missing-result", "missing-reservation", "legacy"):
            with self.subTest(variant=variant):
                key = "policy-" + variant
                attempt, path = self.crashed_live_attempt(key)
                profile = json.loads(path.read_bytes())
                if variant == "wrong-result":
                    profile["provenance"]["provider_policy_sha256"] = "0" * 64
                elif variant in {"missing-result", "legacy"}:
                    profile["provenance"].pop("provider_policy_sha256")
                if variant in {"missing-reservation", "legacy"}:
                    request = deepcopy(attempt["request"])
                    request.pop("provider_policy_sha256")
                    with self.store._transaction() as db:
                        db.execute("UPDATE attempts SET request=? WHERE token=?",
                                   (json.dumps(request), attempt["token"]))
                # Isolated historical/corruption fixture: preserve a valid profile
                # checksum so the reservation check, not hashing, decides it.
                identity_data = {name: value for name, value in profile.items() if name != "profile_id"}
                profile["profile_id"] = sha256(json.dumps(identity_data, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()
                path.write_text(json.dumps(profile))
                before = path.read_bytes()
                with patch("genetics.expression.build_opener", side_effect=AssertionError("network forbidden")):
                    if variant == "legacy":
                        self.assertEqual(self.store.recover_expression(key)["state"], "pending_art")
                        self.assertNotIn("provider_policy_sha256", self.store.inspect(key)["profile"]["provenance"])
                    else:
                        with self.assertRaisesRegex(BreedingError, "reserved invocation"):
                            self.store.recover_expression(key)
                        self.assertEqual(self.store.status(key)["state"], "expression_outcome_unknown")
                        self.assertIsNone(self.store.inspect(key)["profile"])
                        self.assertEqual(self.store.inspect(key)["attempts"][0]["state"], "outcome_unknown")
                self.assertEqual(path.read_bytes(), before)

    def test_unknown_network_outcome_is_not_replayed_after_restart(self):
        self.enqueue()
        with patch("genetics.breeding.generate_expression", side_effect=TimeoutError("PRIVATE_PROVIDER_TEXT")) as provider:
            with self.assertRaises(BreedingError) as error:
                self.store.work_expression("egg-one", mode="openrouter", key="SECRET", model="test/model")
            self.assertNotIn("PRIVATE_PROVIDER_TEXT", str(error.exception))
            resumed = BreedingStore(self.store.directory)
            self.assertEqual(resumed.status("egg-one")["state"], "expression_outcome_unknown")
            with self.assertRaises(BreedingError):
                resumed.work_expression("egg-one", mode="openrouter", key="SECRET", model="test/model")
            self.assertEqual(provider.call_count, 1)
        status = self.store.status("egg-one")
        with self.assertRaises(BreedingError):
            self.store.retry_unknown("egg-one", attempt_token=status["attempt"], confirm_worker_stopped=True,
                                     confirm_no_usable_result=False, reason="Provider outcome inspected.")
        self.store.retry_unknown("egg-one", attempt_token=status["attempt"], confirm_worker_stopped=True,
                                 confirm_no_usable_result=True, reason="Stopped worker; provider has no usable response.")
        self.assertEqual(self.store.work_expression("egg-one")["state"], "pending_art")
        self.assertEqual([a["state"] for a in self.store.inspect("egg-one")["attempts"]], ["abandoned", "accepted"])

    def test_crash_after_response_publication_recovers_exact_result_without_reinvocation(self):
        self.enqueue()
        with patch.object(self.store, "recover_expression", side_effect=RuntimeError("simulated crash")):
            with self.assertRaises(BreedingError):
                self.store.work_expression("egg-one")
        resumed = BreedingStore(self.store.directory)
        status = resumed.status("egg-one")
        with self.assertRaisesRegex(BreedingError, "recover it"):
            resumed.retry_unknown("egg-one", attempt_token=status["attempt"], confirm_worker_stopped=True,
                                  confirm_no_usable_result=True, reason="Must not discard saved result.")
        with patch("genetics.breeding.fixture_expression", wraps=fixture_expression) as fixture:
            self.assertEqual(resumed.recover_expression("egg-one")["state"], "pending_art")
            # The fixture validates frozen input bindings, with no provider call.
            self.assertEqual(fixture.call_count, 1)
        self.assertEqual(len(resumed.inspect("egg-one")["attempts"]), 1)

    def test_concurrent_workers_claim_only_one_expression_attempt(self):
        self.enqueue()
        def worker(_):
            try:
                return BreedingStore(self.store.directory).work_expression("egg-one")["state"]
            except BreedingError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertCountEqual(results, ["pending_art", "rejected"])
        self.assertEqual(len(self.store.inspect("egg-one")["attempts"]), 1)

    def test_concurrent_art_claims_reserve_only_one_invocation(self):
        self.enqueue()
        self.store.work_expression("egg-one")
        def worker(_):
            try:
                return BreedingStore(self.store.directory).start_art("egg-one", model="fixture", tool="fixture")["attempt"]
            except BreedingError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(results.count("rejected"), 1)
        attempts = self.store.inspect("egg-one")["attempts"]
        self.assertEqual(sum(a["stage"] == "art" for a in attempts), 1)

    def test_competing_art_results_accept_one_without_publishing_the_rejected_result(self):
        reservation = self.ready_for_art()
        candidate_paths = [self.root / "first.png", self.root / "second.png"]
        for index, path in enumerate(candidate_paths):
            path.write_bytes(PNG + str(index).encode())
        def worker(path):
            try:
                return BreedingStore(self.store.directory).accept_art(
                    "egg-one", attempt_token=reservation["attempt"], image_path=path)["image_sha256"]
            except BreedingError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, candidate_paths))
        self.assertEqual(results.count("rejected"), 1)
        accepted_hash = next(value for value in results if value != "rejected")
        resumed = BreedingStore(self.store.directory)
        self.assertEqual(resumed.status("egg-one")["image_sha256"], accepted_hash)
        self.assertEqual({path.stem for path in (self.store.directory / "objects").iterdir()},
                         {sha256(PNG).hexdigest(), accepted_hash})

    def test_art_claim_survives_restart_then_acceptance_is_permanent_and_idempotent(self):
        reservation = self.ready_for_art()
        resumed = BreedingStore(self.store.directory)
        with self.assertRaises(BreedingError):
            resumed.start_art("egg-one", model="new-model", tool="fixture")
        accepted = resumed.accept_art("egg-one", attempt_token=reservation["attempt"], image_path=self.source)
        self.assertEqual(accepted["state"], "completed")
        self.assertEqual(resumed.accept_art("egg-one", attempt_token=reservation["attempt"], image_path=self.source), accepted)
        replacement = self.root / "replacement.png"
        replacement.write_bytes(PNG + b"different bytes")
        with self.assertRaisesRegex(BreedingError, "cannot be replaced"):
            resumed.accept_art("egg-one", attempt_token=reservation["attempt"], image_path=replacement)
        self.source.unlink()
        self.assertEqual(BreedingStore(self.store.directory).status("egg-one"), accepted)

    def test_old_art_attempt_cannot_win_after_explicit_retry(self):
        first = self.ready_for_art()
        self.store.retry_unknown("egg-one", attempt_token=first["attempt"], confirm_worker_stopped=True,
                                 confirm_no_usable_result=True, reason="External tool was never invoked.")
        second = self.store.start_art("egg-one", model="fixture", tool="fixture")
        with self.assertRaisesRegex(BreedingError, "no longer"):
            self.store.accept_art("egg-one", attempt_token=first["attempt"], image_path=self.source)
        self.assertEqual(self.store.accept_art("egg-one", attempt_token=second["attempt"], image_path=self.source)["state"], "completed")

    def test_corrupt_parent_pixels_or_identity_refuse_generation(self):
        self.enqueue()
        path = self.store.directory / "objects" / (sha256(PNG).hexdigest() + ".image")
        path.write_bytes(PNG + b"changed")
        with self.assertRaisesRegex(BreedingError, "checksum changed"):
            self.store.work_expression("egg-one")
        self.assertEqual(self.store.status("egg-one")["state"], "pending_expression")
        context = deepcopy(self.jobs[0]["context"])
        context["individual"]["generation"] = 99
        with self.assertRaises(ValueError):
            self.store.register_parent(context, self.profiles[0], self.source, image_sha256=sha256(PNG).hexdigest())

    def test_invalid_live_configuration_does_not_claim_or_call(self):
        self.enqueue()
        with patch("genetics.breeding.generate_expression") as provider:
            for kwargs in ({"mode": "automatic"}, {"mode": {}}, {"mode": "openrouter"}, {"timeout": float("nan")},
                           {"timeout": 31}, {"timeout": 10**1000}):
                with self.assertRaises(BreedingError):
                    self.store.work_expression("egg-one", **kwargs)
            provider.assert_not_called()
        self.assertEqual(self.store.status("egg-one")["state"], "pending_expression")

    def test_malformed_intents_are_rejected_before_persistence(self):
        for parent_ids in (None, "ab", {}, [self.parents[0], {}], [self.parents[0], "x" * 1000],
                           [self.parents[0]], self.parents + [self.parents[0]]):
            with self.subTest(parents=parent_ids):
                with self.assertRaises(BreedingError):
                    self.store.enqueue("invalid", parent_ids, seed=1)
        for key in (None, {}, ["egg"], "x" * 65):
            with self.subTest(key=key):
                with self.assertRaises(BreedingError):
                    self.store.status(key)
        with self.assertRaisesRegex(BreedingError, "not registered"):
            self.store.status("invalid")
        for attempt in (None, {}, "x" * 1000):
            with self.subTest(attempt=attempt):
                with self.assertRaises(BreedingError):
                    self.store.accept_art("invalid", attempt_token=attempt, image_path=self.source)


if __name__ == "__main__":
    unittest.main()
