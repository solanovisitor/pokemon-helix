import copy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from game_agents.pokemon_generator import (
    PokemonCandidate, PokemonDossier, PokemonGeneratorQueue,
    fixture_candidate, validate_candidate,
)
from genetics.primers import digest
from genetics.universal import Genome
from test_roster import png


def dossier():
    return PokemonDossier.model_validate({
        "individual": {"individual_id": "12" * 16, "id_codec": "helix-native-id128-v1",
                       "genome": Genome(((0,) * 96, (1,) * 96)).to_dict(), "species": "Wingull",
                       "registration_sha256": "34" * 32},
        "origin": "synthetic_fixture", "constraints": ["Keep the recognizable native silhouette."],
    }).model_dump(mode="json")


class PokemonGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.queue = PokemonGeneratorQueue(self.directory / "queue")

    def tearDown(self):
        self.queue.close()
        self.tmp.cleanup()

    def test_fixture_restart_replay_is_identical_and_makes_no_network(self):
        request = dossier()
        original = copy.deepcopy(request)
        plan = self.queue.plan(request)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            first = self.queue.run()
            self.queue.close()
            self.queue = PokemonGeneratorQueue(self.directory / "queue")
            self.assertEqual(plan, self.queue.plan(request))
            second = self.queue.run()
        self.assertEqual(request, original)
        self.assertEqual(first["candidate_sha256"], second["candidate_sha256"])
        candidate = json.loads(Path(first["candidate_path"]).read_bytes())
        self.assertFalse(candidate["emitted_individual"])
        self.assertFalse(candidate["pixels_generated"])
        self.assertEqual(candidate["native_admission"], "none")
        self.assertEqual(candidate["individual_id"], request["individual"]["individual_id"])

    def test_changed_dossier_or_model_cannot_reuse_queue(self):
        self.queue.plan(dossier())
        changed = dossier()
        changed["individual"]["individual_id"] = "11" * 16
        with self.assertRaises(ValueError): self.queue.plan(changed)
        with self.assertRaises(ValueError): self.queue.plan(dossier(), mode="external_model", model="chosen/model")

    def test_all_genome_versions_are_separate_and_unknown_versions_fail(self):
        from genetics.models import Genotype
        from genetics.primers import VirtualGenome
        for codec, genome, length in (("aurora-id96-v1", Genotype(((0,) * 32,) * 2), 24),
                                      ("aurora-id256-v2", VirtualGenome(((0,) * 96,) * 2), 64),
                                      ("helix-id256-v3", Genome(((0,) * 96,) * 2), 64)):
            request = dossier()
            request["individual"].update(id_codec=codec, genome=genome.to_dict(), individual_id="1" * length)
            PokemonDossier.model_validate(request)
        request["individual"]["genome"]["schema"] = "aurora-virtual-genome-v2"
        with self.assertRaises(ValueError): PokemonDossier.model_validate(request)

    def test_accepted_assets_or_unknown_actions_cannot_be_overwritten(self):
        for key in ("accepted_art_sha256", "accepted_expression_sha256"):
            request = dossier(); request[key] = "11" * 32
            with self.assertRaises(ValueError): self.queue.plan(request)
        request = dossier(); request["mint"] = True
        with self.assertRaises(ValueError): self.queue.plan(request)

    def test_candidate_cannot_change_identity_or_forge_native_issuance(self):
        selected = PokemonDossier.model_validate(dossier())
        for key, changed in (("individual_id", "ff" * 16), ("dossier_sha256", "ff" * 32),
                             ("emitted_individual", True), ("native_admission", "accepted"),
                             ("pixels_generated", True), ("mode", "external_model")):
            value = fixture_candidate(selected); value[key] = changed
            with self.assertRaises(ValueError): validate_candidate(value, selected, "fixture")

    def test_offspring_requires_both_profiles_and_actual_parent_pixels(self):
        request = dossier(); request["origin"] = "recorded_offspring"
        image = png(); image_hash = sha256(image).hexdigest()
        profile = fixture_candidate(PokemonDossier.model_validate(dossier()))["expression"]
        parents = []
        for identity in ("ab" * 16, "cd" * 16):
            individual = copy.deepcopy(request["individual"]); individual["individual_id"] = identity
            parents.append({"individual": individual, "profile": profile,
                            "profile_sha256": digest(profile), "image_sha256": image_hash})
        request.update(parents=parents, parent_ids=[p["individual"]["individual_id"] for p in parents])
        with self.assertRaises(ValueError): self.queue.plan(request)
        self.queue.plan(request, images={image_hash: image})
        result = self.queue.run()
        candidate = json.loads(Path(result["candidate_path"]).read_bytes())
        self.assertEqual(candidate["parent_image_sha256"], [image_hash, image_hash])
        changed = copy.deepcopy(request); changed["parents"].pop()
        with self.assertRaises(ValueError): PokemonDossier.model_validate(changed)

    def test_unknown_external_attempt_cannot_auto_retry_after_restart(self):
        self.queue.plan(dossier(), mode="external_model", model="selected/model")
        def failed(**kwargs): raise TimeoutError("simulated outcome unknown")
        with self.assertRaises(TimeoutError): self.queue.run(live=True, key="explicit-test-key", provider=failed)
        with self.queue.transaction(): self.queue._expire(10**12)
        row = self.queue.db.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(row["status"], "unknown")
        self.assertIsNone(self.queue.claim("another-worker"))
        with self.assertRaises(ValueError): self.queue.reconcile(row["id"], outcome="no_result", note="No implicit retry")
        with patch("game_agents.deepagents_adapter.invoke_candidate", side_effect=AssertionError("reinvocation")):
            self.assertEqual(self.queue.run(live=True, key="explicit-test-key")["status"], "blocked_or_running")

    def test_missing_live_key_does_not_consume_a_claim(self):
        self.queue.plan(dossier(), mode="external_model", model="selected/model")
        with self.assertRaises(ValueError): self.queue.run(live=True)
        row = self.queue.db.execute("SELECT status,attempt FROM jobs").fetchone()
        self.assertEqual(tuple(row), ("pending", 0))

    def test_result_published_before_crash_recovers_without_model(self):
        self.queue.plan(dossier())
        real_complete = self.queue.complete
        with patch.object(self.queue, "complete", side_effect=RuntimeError("crash after publish")):
            with self.assertRaises(RuntimeError): self.queue.run()
        with self.queue.transaction(): self.queue._expire(10**12)
        row = self.queue.db.execute("SELECT * FROM jobs").fetchone()
        path = next((self.queue.path / "candidates").glob("*.json"))
        self.queue.reconcile(row["id"], outcome="accepted", note="Recovered retained candidate; no model call", result_sha256=path.stem)
        self.assertTrue(self.queue.run()["reused"])

    def test_cli_offline_fixture_is_concrete_and_replayable(self):
        request_file = self.directory / "dossier.json"
        request_file.write_text(json.dumps(dossier()))
        cli_queue = self.directory / "cli"
        script = Path(__file__).resolve().parents[1] / "scripts/pokemon-generator.py"
        base = [sys.executable, str(script), "--queue", str(cli_queue)]
        subprocess.run([*base, "plan", "--dossier", str(request_file)], check=True, capture_output=True)
        result = json.loads(subprocess.run([*base, "run"], check=True, capture_output=True).stdout)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["pixels_generated"])


@unittest.skipUnless(importlib.util.find_spec("deepagents"), "optional generation extra not installed")
class RealDeepAgentsSmokeTests(unittest.TestCase):
    def test_real_sdk_invokes_fake_model_and_only_approved_tools(self):
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from pydantic import PrivateAttr
        from game_agents.deepagents_adapter import build_candidate_agent
        candidate = fixture_candidate(PokemonDossier.model_validate(dossier()))

        class OfflineModel(ChatOpenAI):
            _calls: int = PrivateAttr(default=0)
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self._calls += 1
                call = {"name": "read_approved_context", "args": {}, "id": "approved-context"} if self._calls == 1 else {
                    "name": "PokemonCandidate", "args": candidate, "id": "candidate-result"}
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])

        model = OfflineModel(model="helix-offline-smoke", api_key="fixture-unused", max_retries=0)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            graph = build_candidate_agent(context={"dossier": dossier()}, schema=PokemonCandidate,
                                          system_prompt="Return a synthetic candidate.", chat_model=model)
            exposed = set(graph.get_graph().nodes["tools"].data.tools_by_name)
            self.assertEqual(exposed, {"read_file", "read_approved_context"})
            self.assertFalse(any("Summarization" in name for name in graph.get_graph().nodes))
            result = graph.invoke({"messages": [{"role": "user", "content": "Fixture candidate only."}]},
                                  config={"recursion_limit": 16})
        self.assertEqual(model._calls, 2)
        self.assertEqual(result["structured_response"].individual_id, dossier()["individual"]["individual_id"])
        self.assertFalse(result["structured_response"].emitted_individual)

    def test_real_sdk_stops_before_fifth_model_call(self):
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
        from pydantic import PrivateAttr
        from game_agents.deepagents_adapter import build_candidate_agent

        class RepeatingModel(ChatOpenAI):
            _calls: int = PrivateAttr(default=0)
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self._calls += 1
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[{
                    "name": "read_approved_context", "args": {}, "id": str(self._calls)}]))])

        model = RepeatingModel(model="helix-offline-limit", api_key="fixture-unused", max_retries=0)
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            graph = build_candidate_agent(context={"dossier": dossier()}, schema=PokemonCandidate,
                                          system_prompt="Return one synthetic candidate.", chat_model=model)
            with self.assertRaises(ModelCallLimitExceededError):
                graph.invoke({"messages": [{"role": "user", "content": "Fixture only."}]}, config={"recursion_limit": 32})
        self.assertEqual(model._calls, 4)


if __name__ == "__main__": unittest.main()
