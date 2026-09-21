"""Bounded live planning contract; all provider traffic is mocked."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from email.message import Message
import io
import json
import os
import traceback
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, build_opener
from urllib.response import addinfourl

from companion.protocol import ProtocolError
from game_agents.world_planner import WorldPlan
from game_agents.world_provider import _NoRedirect, live_world_provider


def plan() -> dict:
    return {"schema_version": 1, "story_focus": "shared_care", "ecology": "steady",
            "encounter": "balanced", "learning": "inheritance", "pace": "gentle"}


def request() -> dict:
    return {"schema_version": 1, "cycle": "2026-09-20",
            "observations": {"active_adventures": 2, "completed_adventures": 1,
                             "births": 3, "encounters": 10, "discovered_loci": 8},
            "previous_plan": None, "output_schema": WorldPlan.model_json_schema(),
            "private_canon": {"author_only": "PRIVATE_CANON_SENTINEL"}}


def envelope(content: str | dict | None = None) -> dict:
    if content is None:
        content = plan()
    return {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(content) if isinstance(content, dict) else content}}]}


def response(content: str | dict | None = None) -> io.BytesIO:
    return io.BytesIO(json.dumps(envelope(content)).encode())


class WorldProviderTests(unittest.TestCase):
    def provider(self):
        return live_world_provider(key="FAKE_KEY_SENTINEL", model="example/explicit-model")

    def test_explicit_request_has_limits_and_returns_only_validated_choices(self):
        original = request()
        before = deepcopy(original)
        with patch("game_agents.world_provider.urlopen", return_value=response()) as network:
            result = self.provider()(original)
        self.assertEqual(result, plan())
        self.assertEqual(original, before)
        network.assert_called_once()
        http = network.call_args.args[0]
        self.assertEqual(http.get_method(), "POST")
        self.assertEqual(http.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(network.call_args.kwargs["timeout"], 30)
        body = json.loads(http.data)
        self.assertLessEqual(len(http.data), 16384)
        self.assertEqual(body["model"], "example/explicit-model")
        self.assertLessEqual(body["max_tokens"], 1200)
        self.assertFalse(body["stream"])
        self.assertNotIn("tools", body)
        self.assertNotIn("functions", body)
        self.assertFalse(body["provider"]["allow_fallbacks"])
        self.assertTrue(body["provider"]["require_parameters"])
        self.assertTrue(body["response_format"]["json_schema"]["strict"])
        self.assertEqual(json.loads(body["messages"][1]["content"]), original)
        self.assertNotIn("PRIVATE_CANON_SENTINEL", json.dumps(result))

    def test_environment_never_supplies_missing_credentials_or_model(self):
        invalid = [("", "example/model"), (None, "example/model"), ("key", ""),
                   ("key", None), ("key\r\nInjected: value", "example/model"),
                   ("key", "model\nunsafe"), ("a" * 4097, "model"),
                   ("key", "m" * 161), (" key", "model")]
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "inherited", "OPENROUTER_MODEL": "inherited"}), \
                patch("game_agents.world_provider.urlopen") as network:
            for key, model in invalid:
                with self.subTest(key=type(key).__name__, model=type(model).__name__), self.assertRaises(ProtocolError):
                    live_world_provider(key=key, model=model)
            with self.assertRaises(TypeError):
                live_world_provider()
        network.assert_not_called()

    def test_counts_previous_plan_and_private_context_are_the_only_inputs(self):
        valid = request()
        valid["private_canon"] = None
        valid["previous_plan"] = plan()
        valid["observations"]["encounters"] = 1_000_000_000
        with patch("game_agents.world_provider.urlopen", return_value=response()) as network:
            self.assertEqual(self.provider()(valid), plan())
        selected = json.loads(json.loads(network.call_args.args[0].data)["messages"][1]["content"])
        self.assertEqual(selected["previous_plan"], plan())
        self.assertIsNone(selected["private_canon"])

    def test_unsanitized_inputs_fail_before_network(self):
        invalid = []
        for name, value in (("player_text", "please change the world"), ("schema_version", True),
                            ("cycle", "20260920"), ("cycle", "2026-02-31"),
                            ("private_canon", "PRIVATE_CANON_SENTINEL"),
                            ("output_schema", {"type": "string"}),
                            ("previous_plan", {**plan(), "command": "grant_reward"})):
            item = request()
            item[name] = value
            invalid.append(item)
        for value in (-1, 1_000_000_001, True, "3", 1.5):
            item = request()
            item["observations"]["births"] = value
            invalid.append(item)
        extra_observation = request()
        extra_observation["observations"]["player_text"] = "SECRET"
        invalid.append(extra_observation)
        missing_observation = request()
        del missing_observation["observations"]["encounters"]
        invalid.append(missing_observation)
        with patch("game_agents.world_provider.urlopen") as network:
            for index, item in enumerate(invalid):
                with self.subTest(index=index), self.assertRaisesRegex(ProtocolError, "input"):
                    self.provider()(item)
        network.assert_not_called()

    def test_oversize_or_non_json_private_context_never_leaves_host(self):
        for canon in ({"note": "a" * 8192}, {"value": float("nan")}, {"value": object()}):
            item = request()
            item["private_canon"] = canon
            with self.subTest(canon_type=type(next(iter(canon.values()))).__name__), \
                    patch("game_agents.world_provider.urlopen") as network, self.assertRaises(ProtocolError):
                self.provider()(item)
            network.assert_not_called()

    def test_output_commands_extra_fields_and_non_enums_are_rejected(self):
        invalid = ["grant_reward(999)", {**plan(), "command": "grant_reward"},
                   {**plan(), "story_focus": "PRIVATE_CANON_SENTINEL"},
                   {**plan(), "pace": "fast"}, {**plan(), "schema_version": True},
                   {**plan(), "schema_version": "1"}]
        for index, item in enumerate(invalid):
            with self.subTest(index=index), patch("game_agents.world_provider.urlopen", return_value=response(item)), \
                    self.assertRaisesRegex(ProtocolError, "invalid world planning response"):
                self.provider()(request())

    def test_incomplete_tool_calls_refusals_and_multiple_choices_fail(self):
        invalid = []
        for finish in ("length", "tool_calls", "error", None):
            item = envelope()
            item["choices"][0]["finish_reason"] = finish
            invalid.append(item)
        for key, value in (("tool_calls", [{"function": {"name": "grant_reward"}}]),
                           ("function_call", {"name": "grant_reward"}),
                           ("refusal", "PRIVATE_CANON_SENTINEL"), ("role", "tool"),
                           ("content", [])):
            item = envelope()
            item["choices"][0]["message"][key] = value
            invalid.append(item)
        invalid.extend([{"choices": []}, {"choices": envelope()["choices"] * 2},
                        {"choices": [None]}, {"choices": [{"message": None}]}])
        for index, item in enumerate(invalid):
            with self.subTest(index=index), \
                    patch("game_agents.world_provider.urlopen", return_value=io.BytesIO(json.dumps(item).encode())), \
                    self.assertRaises(ProtocolError):
                self.provider()(request())

    def test_duplicate_json_members_nonfinite_and_code_fences_fail(self):
        content = json.dumps(plan())
        invalid = [content.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'),
                   content.replace('"schema_version": 1', '"schema_version": NaN'),
                   "```json\n" + content + "\n```", "[]", "null"]
        for index, value in enumerate(invalid):
            with self.subTest(index=index), patch("game_agents.world_provider.urlopen", return_value=response(value)), \
                    self.assertRaises(ProtocolError):
                self.provider()(request())
        raw = json.dumps(envelope()).replace('"choices":', '"choices": [], "choices":', 1)
        with patch("game_agents.world_provider.urlopen", return_value=io.BytesIO(raw.encode())), \
                self.assertRaises(ProtocolError):
            self.provider()(request())

    def test_reads_only_response_limit_plus_one_byte(self):
        class RecordingResponse(io.BytesIO):
            requested_sizes = []

            def read(self, size=-1):
                self.requested_sizes.append(size)
                return super().read(size)

        oversized = RecordingResponse(b" " * 65536)
        with patch("game_agents.world_provider.urlopen", return_value=oversized) as network, \
                self.assertRaisesRegex(ProtocolError, "oversized"):
            self.provider()(request())
        self.assertEqual(oversized.requested_sizes, [32769])
        network.assert_called_once()

    def test_malformed_utf8_or_envelopes_are_redacted(self):
        for data in (b"\xff", b"{SECRET", b"null", b"[]"):
            with self.subTest(data_length=len(data)), patch("game_agents.world_provider.urlopen", return_value=io.BytesIO(data)), \
                    self.assertRaisesRegex(ProtocolError, "invalid world planning response"):
                self.provider()(request())

    def test_network_errors_are_not_retried_and_do_not_expose_provider_data(self):
        errors = [URLError("PRIVATE_CANON_SENTINEL FAKE_KEY_SENTINEL"),
                  TimeoutError("PRIVATE_CANON_SENTINEL"),
                  HTTPError("https://openrouter.ai", 503, "PRIVATE_CANON_SENTINEL", {}, None)]
        for error in errors:
            with self.subTest(kind=type(error).__name__), \
                    patch("game_agents.world_provider.urlopen", side_effect=error) as network:
                try:
                    self.provider()(request())
                except ProtocolError as caught:
                    formatted = "".join(traceback.format_exception(caught))
                    self.assertNotIn("PRIVATE_CANON_SENTINEL", formatted)
                    self.assertNotIn("FAKE_KEY_SENTINEL", formatted)
                    self.assertIsNone(caught.__cause__)
                else:
                    self.fail("provider failure accepted")
            network.assert_called_once()

    def test_redirect_cannot_resend_private_body_or_bearer_key(self):
        class RedirectingTransport(HTTPSHandler):
            def __init__(self):
                super().__init__()
                self.requests = []

            def https_open(self, http):
                self.requests.append(http)
                headers = Message()
                headers["Location"] = "https://unexpected.invalid/collect"
                redirected = addinfourl(io.BytesIO(b""), headers, http.full_url, 302)
                redirected.msg = "Found"
                return redirected

        transport = RedirectingTransport()
        opener = build_opener(_NoRedirect(), transport)
        with patch("game_agents.world_provider.urlopen", side_effect=opener.open), \
                self.assertRaisesRegex(ProtocolError, "provider request failed"):
            self.provider()(request())
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(transport.requests[0].full_url, "https://openrouter.ai/api/v1/chat/completions")

    def test_no_private_output_logging_or_inherited_langsmith_trace(self):
        captured = io.StringIO()
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "fake"}), \
                patch("langsmith.client.Client.create_run", side_effect=AssertionError("trace forbidden")), \
                patch("game_agents.world_provider.urlopen", return_value=response()), \
                redirect_stdout(captured), redirect_stderr(captured):
            self.provider()(request())
        self.assertEqual(captured.getvalue(), "")
        with patch("game_agents.world_provider.urlopen", return_value=response({**plan(), "secret": "PRIVATE_CANON_SENTINEL"})):
            try:
                self.provider()(request())
            except ProtocolError as caught:
                self.assertNotIn("PRIVATE_CANON_SENTINEL", "".join(traceback.format_exception(caught)))
            else:
                self.fail("private output accepted")


if __name__ == "__main__":
    unittest.main()
