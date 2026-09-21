"""Request policy is inspected at real adapter boundaries; no paid inference."""
import io
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydantic import BaseModel

from companion.openrouter_policy import (LOW_EFFORT_MODELS, openrouter_options,
                                         openrouter_policy_fingerprint)
from companion.protocol import Request
from companion.providers import openrouter
from game_agents.deepagents_adapter import invoke_candidate
from game_agents.drafts import fixture_draft, live_draft
from game_agents.schemas import GameEvent
from game_agents.world_provider import live_world_provider
from genetics.engine import run_experiment
from genetics.expression import ExpressionProfile, fixture_expression, generate_expression
from genetics.models import SpeciesConfig
from genetics.reference import load_reference
from test_world_provider import request as world_request, plan as world_plan


def envelope(content):
    return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": content if isinstance(content, str) else json.dumps(content)}}]}).encode())


class OpenRouterPolicyTests(unittest.TestCase):
    def test_exact_reviewed_ids_only_and_fresh_bounded_options(self):
        self.assertEqual(LOW_EFFORT_MODELS, {"z-ai/glm-5.3", "z-ai/glm-5.3-flash"})
        for model in (*sorted(LOW_EFFORT_MODELS), "z-ai/glm-5.2", "example/explicit-model",
                      "z-ai/glm-5.3-flash-20260826", "z-ai/glm-5.3:unknown"):
            options = openrouter_options(model)
            self.assertEqual(options["provider"], {"sort": "latency", "require_parameters": True,
                                                   "allow_fallbacks": False})
            self.assertEqual(options.get("reasoning"), {"effort": "low"} if model in LOW_EFFORT_MODELS else None)
            before = openrouter_policy_fingerprint(model)
            options["provider"]["allow_fallbacks"] = True
            self.assertFalse(openrouter_options(model)["provider"]["allow_fallbacks"])
            self.assertEqual(openrouter_policy_fingerprint(model), before)
        for model in (None, "", "bad\nmodel", "a" * 161):
            with self.subTest(model=model), self.assertRaises(ValueError):
                openrouter_options(model)

    def test_effective_policy_change_invalidates_fingerprint(self):
        original = openrouter_policy_fingerprint("z-ai/glm-5.3-flash")
        with patch("companion.openrouter_policy.LOW_EFFORT_MODELS", frozenset()):
            self.assertNotEqual(original, openrouter_policy_fingerprint("z-ai/glm-5.3-flash"))

    def test_dialogue_draft_and_world_send_exact_policy_without_changing_caps(self):
        event = GameEvent(kind="world_draft", save_id="policy-fixture", session="a" * 32 + "-0",
                          epoch=1, sequence=1, rom={"motivation": 1, "quest": 1}, brief="A village clue.")
        req = Request("a" * 32 + "-0", 1, 1, 1, 1, 1)
        adapters = [
            ("companion.providers.urlopen", lambda m: openrouter(req, key="synthetic", model=m), "Hello.", 100),
            ("game_agents.drafts.urlopen", lambda m: live_draft(event, key="synthetic", model=m), fixture_draft(event), 1600),
            ("game_agents.world_provider.urlopen", lambda m: live_world_provider(key="synthetic", model=m)(world_request()), world_plan(), 1200),
        ]
        for model in ("z-ai/glm-5.3", "z-ai/glm-5.3-flash", "z-ai/glm-5.2"):
            for target, invoke, content, cap in adapters:
                with self.subTest(model=model, target=target), patch(target, return_value=envelope(content)) as network:
                    invoke(model)
                network.assert_called_once()
                body = json.loads(network.call_args.args[0].data)
                for key, value in openrouter_options(model).items():
                    self.assertEqual(body[key], value)
                self.assertEqual("reasoning" in body, model in LOW_EFFORT_MODELS)
                self.assertEqual(body["model"], model)
                self.assertEqual(body["max_tokens"], cap)
                self.assertFalse(body["stream"])
                self.assertNotIn("synthetic", json.dumps(body))

    def test_direct_adapters_do_not_retry_provider_failures(self):
        event = GameEvent(kind="world_draft", save_id="policy-fixture", session="a" * 32 + "-0",
                          epoch=1, sequence=1, rom={"motivation": 1, "quest": 1}, brief="A village clue.")
        req = Request("a" * 32 + "-0", 1, 1, 1, 1, 1)
        for target, invoke in (
            ("companion.providers.urlopen", lambda: openrouter(req, key="synthetic", model="z-ai/glm-5.3-flash")),
            ("game_agents.drafts.urlopen", lambda: live_draft(event, key="synthetic", model="z-ai/glm-5.3-flash")),
            ("game_agents.world_provider.urlopen", lambda: live_world_provider(key="synthetic", model="z-ai/glm-5.3-flash")(world_request())),
        ):
            with self.subTest(target=target), patch(target, side_effect=TimeoutError("synthetic timeout")) as network:
                with self.assertRaises((TimeoutError, ValueError)):
                    invoke()
            network.assert_called_once()

    def test_deepagents_uses_same_extra_body_and_zero_sdk_retries(self):
        class Output(BaseModel):
            value: str
        for model in ("z-ai/glm-5.3-flash", "z-ai/glm-5.2"):
            graph = Mock()
            graph.ainvoke = AsyncMock(return_value={"structured_response": {"value": "fixture"}})
            with patch("langchain_openai.ChatOpenAI") as constructor, \
                    patch("game_agents.deepagents_adapter.build_candidate_agent", return_value=graph):
                self.assertEqual(invoke_candidate(context={"fixture": True}, schema=Output,
                    system_prompt="Return a fixture.", model=model, key="synthetic"), {"value": "fixture"})
            constructor.assert_called_once()
            kwargs = constructor.call_args.kwargs
            self.assertEqual(kwargs["extra_body"], openrouter_options(model))
            self.assertEqual(kwargs["max_retries"], 0)
            self.assertEqual(kwargs["max_tokens"], 1200)
            self.assertEqual(kwargs["timeout"], 10)
            graph.ainvoke.assert_awaited_once()

    def test_expression_policy_is_recorded_without_rewriting_legacy_profiles(self):
        job = run_experiment(species=SpeciesConfig.from_reference(load_reference()),
                             population_size=2, generations=1)["generation_requests"][0]
        legacy = fixture_expression(job)
        before = legacy.model_dump_json()
        self.assertNotIn("provider_policy_sha256", before)
        for model in ("z-ai/glm-5.3-flash", "z-ai/glm-5.2"):
            opener = Mock()
            opener.open.return_value = envelope(legacy.expression.model_dump())
            with patch("genetics.expression.build_opener", return_value=opener):
                profile = generate_expression(job, key="synthetic", model=model)
            opener.open.assert_called_once()
            body = json.loads(opener.open.call_args.args[0].data)
            self.assertEqual(body["provider"], openrouter_options(model)["provider"])
            self.assertEqual(body.get("reasoning"), openrouter_options(model).get("reasoning"))
            self.assertEqual(profile.provenance.provider_policy_sha256, openrouter_policy_fingerprint(model))
            self.assertEqual(ExpressionProfile.model_validate_json(profile.model_dump_json()), profile)
        self.assertEqual(ExpressionProfile.model_validate_json(before).model_dump_json(), before)
        opener = Mock()
        opener.open.side_effect = TimeoutError("synthetic timeout")
        with patch("genetics.expression.build_opener", return_value=opener), self.assertRaises(ValueError):
            generate_expression(job, key="synthetic", model="z-ai/glm-5.3-flash")
        opener.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
