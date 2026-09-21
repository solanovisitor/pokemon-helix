"""Routing upgrades cannot silently resume legacy or stale generation jobs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_agents import pokemon_generator as generator
from genetics.primers import canonical, digest
from test_pokemon_generator import dossier


def retain_legacy(queue, *, status="complete", mode="fixture"):
    selected = generator.PokemonDossier.model_validate(dossier())
    payload = {"schema": "helix-pokemon-generator-v1", "dossier": selected.model_dump(mode="json"),
               "mode": mode, "model": "none" if mode == "fixture" else "z-ai/glm-5.3-flash",
               "prompt_sha256": "bfa41bed8f40162d1e716d952f2b02828ff62be4d0c32d85a1efd20a9509030a",
               "max_calls": 4, "max_output_tokens": 1200}
    identity = digest(payload)
    candidate = generator.fixture_candidate(selected)
    candidate["mode"] = mode
    checksum = digest(candidate)
    queue.db.execute("UPDATE settings SET value=? WHERE key='generator_schema'", (payload["schema"],))
    queue.db.execute("INSERT INTO settings VALUES('generator_job',?)", (identity,))
    queue.db.execute("INSERT INTO jobs(id,adventure_id,owner_id,stage,payload,payload_sha256,status,"
                     "result_sha256,token,lease_until) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (identity, digest([payload["schema"], identity]), selected.individual.individual_id,
                      "profile", canonical(payload).decode(), identity, status,
                      checksum if status == "complete" else None, "synthetic-token", 1000))
    queue.db.commit()
    path = queue.path / "candidates" / (checksum + ".json")
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(canonical(candidate))
    return payload, path


class PokemonProducerPolicyTests(unittest.TestCase):
    def test_new_identity_binds_effective_policy_and_shared_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.PokemonGeneratorQueue(temporary)
            self.addCleanup(queue.close)
            plan = queue.plan(dossier(), mode="external_model", model="z-ai/glm-5.3-flash")
            row = queue.db.execute("SELECT * FROM jobs").fetchone()
            payload = json.loads(row["payload"])
            self.assertEqual(payload["schema"], "helix-pokemon-generator-v2")
            self.assertRegex(payload["producer_policy_sha256"], r"^[a-f0-9]{64}$")
            self.assertEqual(digest(payload), plan["job_id"])
            policy = payload["producer_policy_sha256"]
            with patch("companion.openrouter_policy.LOW_EFFORT_MODELS", frozenset()):
                self.assertNotEqual(policy, generator._producer_policy_sha256(payload["model"]))
            read_bytes = Path.read_bytes
            for relative in ("companion/openrouter_policy.py", "game_agents/deepagents_adapter.py"):
                selected = generator.ROOT / relative
                def changed(path):
                    return read_bytes(path) + (b"\n" if path == selected else b"")
                with self.subTest(relative=relative), patch.object(Path, "read_bytes", changed):
                    self.assertNotEqual(policy, generator._producer_policy_sha256(payload["model"]))

    def test_stale_pending_policy_fails_before_claim_or_provider_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.PokemonGeneratorQueue(temporary)
            self.addCleanup(queue.close)
            queue.plan(dossier(), mode="external_model", model="z-ai/glm-5.3-flash")
            before = tuple(queue.db.iterdump())
            with patch("companion.openrouter_policy.LOW_EFFORT_MODELS", frozenset()), \
                    patch("genetics.batches.BatchQueue.claim", side_effect=AssertionError("claim forbidden")), \
                    patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                for operation in (lambda: queue.run(live=True, key="synthetic"), lambda: queue.claim("worker")):
                    with self.assertRaisesRegex(ValueError, "producer policy"):
                        operation()
            self.assertEqual(tuple(queue.db.iterdump()), before)

    def test_current_completed_result_is_checked_against_policy_before_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.PokemonGeneratorQueue(temporary)
            self.addCleanup(queue.close)
            queue.plan(dossier())
            first = queue.run()
            path = Path(first["candidate_path"])
            before = path.read_bytes(), tuple(queue.db.iterdump())
            with patch.object(generator, "_producer_policy_sha256", return_value="0" * 64):
                with self.assertRaisesRegex(ValueError, "producer policy"):
                    queue.run()
            self.assertEqual((path.read_bytes(), tuple(queue.db.iterdump())), before)

    def test_complete_legacy_replay_is_read_only_and_revalidates_candidate(self):
        for mode in ("fixture", "external_model"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                queue = generator.PokemonGeneratorQueue(temporary)
                try:
                    payload, path = retain_legacy(queue, mode=mode)
                    before = path.read_bytes(), tuple(queue.db.iterdump())
                    with patch.object(generator, "SYSTEM_PROMPT", "Revised prompt."), \
                            patch("genetics.batches.BatchQueue.claim", side_effect=AssertionError("claim forbidden")), \
                            patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                        self.assertEqual(queue.plan(dossier(), mode=mode, model=payload["model"])["job_id"], digest(payload))
                        self.assertTrue(queue.run()["reused"])
                    self.assertEqual((path.read_bytes(), tuple(queue.db.iterdump())), before)
                    queue.close()
                    queue = generator.PokemonGeneratorQueue(temporary)
                    self.assertTrue(queue.run()["reused"])
                    path.write_bytes(b"{}")
                    with self.assertRaisesRegex(ValueError, "bytes/hash"):
                        queue.run()
                finally:
                    queue.close()

    def test_all_unfinished_legacy_states_refuse_before_claim_provider_or_ledger_write(self):
        for status in ("pending", "leased", "running", "unknown", "failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                queue = generator.PokemonGeneratorQueue(temporary)
                try:
                    payload, path = retain_legacy(queue, status=status, mode="external_model")
                    before = path.read_bytes(), tuple(queue.db.iterdump())
                    with patch("genetics.batches.BatchQueue.claim", side_effect=AssertionError("claim forbidden")), \
                            patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                        for operation in (lambda: queue.run(live=True, key="synthetic"),
                                          lambda: queue.claim("worker"),
                                          lambda: queue.plan(dossier(), mode="external_model", model=payload["model"])):
                            with self.assertRaisesRegex(ValueError, "legacy Pokemon requests are read-only"):
                                operation()
                    self.assertEqual((path.read_bytes(), tuple(queue.db.iterdump())), before)
                finally:
                    queue.close()

    def test_legacy_lease_cannot_authorize_external_call_or_complete_after_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.PokemonGeneratorQueue(temporary)
            self.addCleanup(queue.close)
            payload, path = retain_legacy(queue, status="leased", mode="external_model")
            before = tuple(queue.db.iterdump())
            for operation in (lambda: queue.begin_external(digest(payload), "synthetic-token", digest(payload), now=100),
                              lambda: queue.complete(digest(payload), "synthetic-token", path.stem, now=100)):
                with self.assertRaisesRegex(ValueError, "legacy Pokemon requests are read-only"):
                    operation()
            self.assertEqual(tuple(queue.db.iterdump()), before)

    def test_legacy_caps_and_new_policy_forgery_fail_even_with_recomputed_job_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.PokemonGeneratorQueue(temporary)
            self.addCleanup(queue.close)
            queue.plan(dossier())
            row = dict(queue.db.execute("SELECT * FROM jobs").fetchone())
            payload = json.loads(row["payload"])
            for changes in ({"producer_policy_sha256": "0" * 64}, {"max_calls": 99}, {"schema": "unknown"}):
                changed = deepcopy(payload)
                changed.update(changes)
                forged = {**row, "payload": canonical(changed).decode(), "id": digest(changed), "payload_sha256": digest(changed)}
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "producer policy"):
                    generator._validated_payload(forged)


if __name__ == "__main__":
    unittest.main()
