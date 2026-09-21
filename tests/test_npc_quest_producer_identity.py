"""Producer drift and read-only v2 compatibility; no live inference or old writes."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from game_agents import npc_quest_generator as generator
from genetics.primers import canonical, digest


def legacy_request(seed, mode="fixture"):
    # Independent historical wire contract, not the current producer helper.
    return {
        "schema_version": 1, "generator": "helix-npc-quest-generator-v2",
        "seed": seed, "mode": mode, "model": "none" if mode == "fixture" else "test/model",
        "template": "helix-quiet-garden-v1",
        "template_sha256": "fab69779f6e33ac398440e931d1188c860ba02cffd10097584e0a4cb91251add",
        "runtime_action": "none", "private_context": "none",
        "max_agent_invocations": 0 if mode == "fixture" else 1,
        "max_provider_invocations": 0 if mode == "fixture" else 4,
        "max_output_tokens_per_call": 0 if mode == "fixture" else 1200,
    }


def legacy_candidate(seed=27, mode="fixture"):
    req = legacy_request(seed, mode)
    candidate = generator.assemble(
        generator.request(seed, mode=mode, model=req["model"]), generator.fixture_narrative(seed))
    candidate["request"] = req
    candidate["candidate_id"] = digest(req)[:24]
    return candidate


def retain_legacy(queue, candidate, status="complete"):
    """Create an isolated historical database fixture without legacy generation."""
    req = candidate["request"]
    identity = digest(req)
    checksum = digest(candidate)
    queue.db.execute(
        "INSERT INTO jobs(id,adventure_id,owner_id,stage,payload,payload_sha256,status,"
        "result_sha256,token,lease_until) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (identity, identity, identity, "npc-quest", canonical(req).decode(), identity,
         status, checksum if status == "complete" else None, "synthetic-token", 1000))
    queue.db.commit()
    result = queue.path / "results" / (checksum + ".json")
    result.parent.mkdir(exist_ok=True)
    result.write_bytes(canonical(candidate))
    return result


class ProducerIdentityTests(unittest.TestCase):
    def test_new_request_is_v3_deterministic_and_contains_only_policy_digest(self):
        req = generator.request(27)
        self.assertEqual(req, generator.request(27))
        self.assertEqual(req["generator"], "helix-npc-quest-generator-v3")
        self.assertRegex(req["producer_sha256"], r"^[a-f0-9]{64}$")
        context = canonical(generator.approved_context(req)).decode()
        for term in ("veilwarden", "fixture secret is amber", "segredo de teste e ambar", "_RESTRICTED_SENTENCES"):
            self.assertNotIn(term, context)
        self.assertNotIn("dependencies", req)

    def test_prompt_schema_context_and_output_cap_changes_invalidate_identity(self):
        original = generator.request(27)
        schema = generator.JointProposal.model_json_schema()
        schema["description"] = "A revised explicit producer schema."
        with patch.object(generator, "SYSTEM_PROMPT", generator.SYSTEM_PROMPT + " Revised prompt."):
            self.assertNotEqual(original, generator.request(27))
        with patch.object(generator.JointProposal, "model_json_schema", return_value=schema):
            self.assertNotEqual(original, generator.request(27))
        with patch.object(generator, "CONTEXT_CONSTRAINTS", (*generator.CONTEXT_CONSTRAINTS, "New public constraint.")):
            self.assertNotEqual(original, generator.request(27))
        with patch.object(generator, "MAX_OUTPUT_BYTES", generator.MAX_OUTPUT_BYTES - 1):
            self.assertNotEqual(original, generator.request(27))

    def test_custom_guard_font_converter_and_adapter_bytes_are_bound(self):
        original = generator.request(27)
        read_bytes = Path.read_bytes
        for relative in ("game_agents/public_lore.py", "game_agents/expansion_contract.py",
                         "game_agents/deepagents_adapter.py", "examples/native-text-metrics.json"):
            selected = generator.ROOT / relative
            def changed(path):
                raw = read_bytes(path)
                return raw + b"\n" if path == selected else raw
            with self.subTest(dependency=relative), patch.object(Path, "read_bytes", changed):
                self.assertNotEqual(original, generator.request(27))

    def test_width_validation_uses_the_same_current_metrics_bytes_as_identity(self):
        original = generator.request(27)
        width = generator._native_widths()["W"]
        metrics_path = generator.ROOT / "examples/native-text-metrics.json"
        changed_metrics = json.loads(metrics_path.read_bytes())
        changed_metrics["widths"]["W"] = width + 1
        read_bytes = Path.read_bytes
        def changed(path):
            return canonical(changed_metrics) if path == metrics_path else read_bytes(path)
        with patch.object(Path, "read_bytes", changed):
            self.assertEqual(generator._native_widths()["W"], width + 1)
            self.assertNotEqual(original, generator.request(27))
        self.assertEqual(generator._native_widths()["W"], width)

    def test_stale_pending_v3_fails_before_claim_or_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.NpcQuestQueue(temporary)
            try:
                queue.plan(generator.request(27, mode="deepagents", model="test/model"))
                before = tuple(queue.db.iterdump())
                with patch.object(generator, "SYSTEM_PROMPT", "Revised producer prompt."), \
                        patch("genetics.batches.BatchQueue.claim", side_effect=AssertionError("claim forbidden")), \
                        patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                    with self.assertRaisesRegex(ValueError, "input drift"):
                        queue.run(key="synthetic-test-key")
                    with self.assertRaisesRegex(ValueError, "input drift"):
                        queue.claim("worker")
                self.assertEqual(tuple(queue.db.iterdump()), before)
            finally:
                queue.close()

    def test_completed_v3_is_revalidated_before_reuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.NpcQuestQueue(temporary)
            try:
                queue.plan(generator.request(27))
                candidate = queue.run()
                path = queue.path / "results" / (digest(candidate) + ".json")
                before = path.read_bytes(), tuple(queue.db.iterdump())
                with patch.object(generator, "SYSTEM_PROMPT", "Revised producer prompt."), \
                        patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                    with self.assertRaisesRegex(ValueError, "input drift"):
                        queue.run()
                self.assertEqual((path.read_bytes(), tuple(queue.db.iterdump())), before)
            finally:
                queue.close()

    def test_completed_replay_returns_exact_verified_bytes_without_second_read(self):
        # A concurrent replacement between verification and a second read must
        # not turn a checked cache hit into unvalidated public output.
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as temporary:
                queue = generator.NpcQuestQueue(temporary)
                try:
                    if legacy:
                        candidate = legacy_candidate()
                        path = retain_legacy(queue, candidate)
                    else:
                        queue.plan(generator.request(27))
                        candidate = queue.run()
                        path = queue.path / "results" / (digest(candidate) + ".json")
                    poisoned = deepcopy(candidate)
                    poisoned["narrative"]["npcs"][0]["name"] = "VEILWARDEN"
                    with self.assertRaises(ValueError):
                        generator.validate_candidate(poisoned)
                    reads = []
                    read_bytes = Path.read_bytes
                    def replaced(path_to_read):
                        if path_to_read == path:
                            reads.append(path_to_read)
                            return canonical(candidate if len(reads) == 1 else poisoned)
                        return read_bytes(path_to_read)
                    before = tuple(queue.db.iterdump())
                    with patch.object(Path, "read_bytes", replaced):
                        self.assertEqual(queue.run(), candidate)
                    self.assertEqual(reads, [path])
                    self.assertEqual(tuple(queue.db.iterdump()), before)
                    self.assertEqual(path.read_bytes(), canonical(candidate))
                finally:
                    queue.close()

    def test_independent_legacy_contract_reconstructs_exact_retained_v2_bytes(self):
        candidate = legacy_candidate()
        # Existing public fixture-27-v2 candidate, read independently during audit.
        self.assertEqual(sha256(canonical(candidate)).hexdigest(),
                         "fc6040119f388e48cff2006f35e3ebe081063cf4155db458e08ed254d1926b35")
        self.assertEqual(generator.validate_candidate(candidate), digest(candidate))

    def test_completed_v2_replay_preserves_results_ledger_and_export_version(self):
        for seed in (0, 27, 2**32 - 1):
            for mode in ("fixture", "deepagents"):
                with self.subTest(seed=seed, mode=mode), tempfile.TemporaryDirectory() as temporary:
                    queue = generator.NpcQuestQueue(Path(temporary) / "queue")
                    try:
                        candidate = legacy_candidate(seed, mode)
                        path = retain_legacy(queue, candidate)
                        before = path.read_bytes(), tuple(queue.db.iterdump())
                        with patch.object(generator, "SYSTEM_PROMPT", "A future producer prompt."), \
                                patch("genetics.batches.BatchQueue.claim", side_effect=AssertionError("claim forbidden")), \
                                patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                            self.assertEqual(queue.plan(candidate["request"]), digest(candidate["request"]))
                            self.assertEqual(queue.run(), candidate)
                        self.assertEqual((path.read_bytes(), tuple(queue.db.iterdump())), before)
                        output = Path(temporary) / "export"
                        manifest = generator.export_candidate(candidate, output)
                        self.assertEqual(manifest["generator"], "helix-npc-quest-generator-v2")
                        exported = {p.name: p.read_bytes() for p in output.iterdir()}
                        self.assertEqual(exported["candidate.json"], before[0])
                        self.assertEqual(generator.export_candidate(candidate, output), manifest)
                        self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, exported)
                    finally:
                        queue.close()

    def test_all_unfinished_v2_states_fail_without_claim_provider_or_ledger_write(self):
        candidate = legacy_candidate(27, "deepagents")
        for status in ("pending", "leased", "running", "unknown", "failed"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temporary:
                queue = generator.NpcQuestQueue(temporary)
                try:
                    path = retain_legacy(queue, candidate, status)
                    before = path.read_bytes(), tuple(queue.db.iterdump())
                    with patch("genetics.batches.BatchQueue.claim", side_effect=AssertionError("claim forbidden")), \
                            patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("provider forbidden")):
                        for operation in (lambda: queue.run(key="synthetic-test-key"),
                                          lambda: queue.claim("worker"),
                                          lambda: queue.plan(candidate["request"])):
                            with self.assertRaisesRegex(ValueError, "legacy v2 requests are read-only"):
                                operation()
                    self.assertEqual((path.read_bytes(), tuple(queue.db.iterdump())), before)
                finally:
                    queue.close()

    def test_v2_cannot_start_new_work_or_complete_an_old_lease(self):
        candidate = legacy_candidate(27, "deepagents")
        with self.assertRaisesRegex(ValueError, "legacy v2 requests are read-only"):
            generator.assemble(candidate["request"], candidate["narrative"])
        with self.assertRaisesRegex(ValueError, "legacy v2 requests are read-only"):
            generator.approved_context(candidate["request"])
        with tempfile.TemporaryDirectory() as temporary:
            queue = generator.NpcQuestQueue(temporary)
            try:
                with self.assertRaisesRegex(ValueError, "legacy v2 requests are read-only"):
                    queue.plan(candidate["request"])
                retain_legacy(queue, candidate, "leased")
                before = tuple(queue.db.iterdump())
                with self.assertRaisesRegex(ValueError, "legacy v2 requests are read-only"):
                    queue.complete(digest(candidate["request"]), "synthetic-token", digest(candidate), now=100)
                self.assertEqual(tuple(queue.db.iterdump()), before)
            finally:
                queue.close()

    def test_forged_legacy_caps_or_new_producer_digest_are_refused(self):
        candidate = legacy_candidate()
        for change in ({"max_provider_invocations": 99}, {"producer_sha256": "0" * 64},
                       {"generator": "helix-npc-quest-generator-v1"}):
            value = deepcopy(candidate)
            value["request"].update(change)
            value["candidate_id"] = digest(value["request"])[:24]
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "input drift"):
                generator.validate_candidate(value)
        current = generator.assemble(generator.request(27), generator.fixture_narrative(27))
        current["request"]["producer_sha256"] = "0" * 64
        current["candidate_id"] = digest(current["request"])[:24]
        with self.assertRaisesRegex(ValueError, "input drift"):
            generator.validate_candidate(current)


if __name__ == "__main__":
    unittest.main()
