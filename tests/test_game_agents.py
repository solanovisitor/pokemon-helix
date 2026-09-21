"""Behavior checks for the actual LangGraph, scope boundary, and persistent memory."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from companion.protocol import ProtocolError, Request, validate_encoded
from game_agents.drafts import fixture_draft
from game_agents.memory import MemoryStore
from game_agents.schemas import GameEvent, MapDraft
from game_agents.service import LangGraphRuntime


def event(*, save="save_a", sequence=1, generation=0, quest=1, motivation=1, kind="npc_dialogue") -> GameEvent:
    return GameEvent(kind=kind, save_id=save, session="a" * 32 + f"-{generation}", epoch=100,
                     sequence=sequence, rom={"motivation": motivation, "quest": quest},
                     brief="Uma pequena pista opcional na vila." if kind != "npc_dialogue" else "")


class AgentRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.memory = Path(self.temporary.name) / "memory.sqlite3"

    def runtime(self, **kwargs):
        return LangGraphRuntime(memory_path=self.memory, **kwargs)

    def test_real_graph_routes_all_four_tasks_and_only_dialogue_is_runtime_action(self):
        runtime = self.runtime()
        for kind, route in (("npc_dialogue", "npc"), ("world_draft", "world"), ("scene_draft", "scene"), ("map_draft", "map")):
            with self.subTest(kind=kind):
                output = runtime.invoke(event(kind=kind))
                self.assertEqual(output["route"], route)
                if route == "npc":
                    self.assertEqual(output["result"]["action"], "dialogue")
                else:
                    self.assertEqual(output["result"]["runtime_action"], "none")
                    self.assertEqual(output["result"]["status"], "draft")

    def test_memory_survives_new_runtime_and_is_isolated_by_save_and_npc(self):
        observed = []
        def provider(evt, persona, memory):
            observed.append((evt.save_id, persona["id"], memory))
            return "Estou observando a vila."
        self.runtime(provider=provider).invoke(event())
        self.runtime(provider=provider).invoke(event(sequence=2))
        self.runtime(provider=provider).invoke(event(save="save_b"))
        self.assertEqual(len(observed[1][2]), 1)
        self.assertEqual(observed[1][2][0]["delivery"], "generated_unconfirmed")
        self.assertEqual(observed[2][2], [])
        with MemoryStore(self.memory).connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM dialogue_memory WHERE npc_id=?", ("other_npc",)).fetchone()[0], 0)
        self.assertEqual(self.memory.stat().st_mode & 0o777, 0o600)

    def test_world_and_player_scopes_cannot_share_npc_memory(self):
        histories = []
        runtime = self.runtime(provider=lambda evt, persona, memory: histories.append(memory) or "Vamos observar.")
        runtime.invoke(event())
        for changed in ({"player_id": "second-player"}, {"world_id": "second-world"}):
            payload = event().model_dump()
            payload.update(changed)
            runtime.invoke(payload)
        self.assertEqual(histories, [[], [], []])

    def test_duplicate_is_idempotent_and_identity_reuse_is_rejected(self):
        calls = []
        def provider(*args):
            calls.append(True)
            return "Podemos observar juntos."
        runtime = self.runtime(provider=provider)
        first = runtime.invoke(event())
        self.assertEqual(runtime.invoke(event()), first)
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ProtocolError, "identity reused"):
            runtime.invoke(event(quest=2))

    def test_old_events_and_state_regression_are_rejected_before_provider(self):
        runtime = self.runtime()
        runtime.invoke(event(sequence=5, quest=2))
        with self.assertRaisesRegex(ProtocolError, "stale event"):
            runtime.invoke(event(sequence=4, quest=2))
        with self.assertRaisesRegex(ProtocolError, "regressed"):
            runtime.invoke(event(sequence=6, quest=1))

    def test_reload_rollback_starts_memory_branch_without_future_knowledge(self):
        memories = []
        def provider(evt, persona, memory):
            memories.append(memory)
            return "Vamos observar com calma."
        runtime = self.runtime(provider=provider)
        runtime.invoke(event(quest=3))
        runtime.invoke(event(generation=1, quest=1))
        runtime.invoke(event(generation=1, sequence=2, quest=1))
        self.assertEqual(memories[1], [])
        self.assertEqual(len(memories[2]), 1)
        self.assertEqual(memories[2][0]["quest"], 1)
        with self.assertRaisesRegex(ProtocolError, "stale event"):
            runtime.invoke(event(quest=3))

    def test_old_transport_cannot_replay_cached_future_after_restart(self):
        runtime = self.runtime()
        runtime.invoke(event(quest=3))
        fresh = event(quest=1).model_dump()
        fresh["session"] = "b" * 32 + "-0"
        runtime.invoke(fresh)
        with self.assertRaisesRegex(ProtocolError, "stale transport"):
            runtime.invoke(event(quest=3))

    def test_invalid_or_executable_output_never_enters_memory(self):
        runtime = self.runtime(provider=lambda *args: {"action": "warp", "map": "invented"})
        with self.assertRaises(ProtocolError):
            runtime.invoke(event())
        self.assertEqual(MemoryStore(self.memory).load(event())["records"], [])

    def test_oversized_dialogue_is_bounded_by_actual_game_encoding(self):
        output = self.runtime(provider=lambda *args: "a" * 800).invoke(event())["result"]
        encoded = bytes.fromhex(output["encoded_hex"])
        validate_encoded(encoded)
        self.assertLessEqual(len(encoded.split(b"\xfb")), 2)
        self.assertLessEqual(len(encoded), 123)

    def test_fixture_service_suppresses_inherited_tracing_and_never_calls_live_provider(self):
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true", "GBA_LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "not-a-real-key"}), \
                patch("companion.providers.openrouter", side_effect=AssertionError("network forbidden")), \
                patch("langsmith.client.Client.create_run", side_effect=AssertionError("trace forbidden")):
            text = self.runtime().dialogue(Request("a" * 32 + "-0", 100, 1, 1, 1, 1), save_id="fixture")
        self.assertIn("curiosity", text)

    def test_runtime_rejects_unknown_npc_and_unsupported_event(self):
        with self.assertRaises(ProtocolError):
            self.runtime().dialogue(Request("a" * 32 + "-0", 100, 1, 5, 1, 1), save_id="fixture")
        payload = event().model_dump()
        payload["kind"] = "grant_reward"
        with self.assertRaises(ValidationError):
            self.runtime().invoke(payload)
        payload = event().model_dump()
        payload["rom"]["source"] = "model"
        with self.assertRaises(ValidationError):
            self.runtime().invoke(payload)

    def test_explicit_fixture_runtime_import_ignores_server_live_environment(self):
        environment = os.environ.copy()
        environment["GAME_AGENT_MODE"] = "openrouter"
        environment.pop("OPENROUTER_API_KEY", None)
        environment.pop("OPENROUTER_MODEL", None)
        result = subprocess.run([sys.executable, "-c",
            "from game_agents.service import LangGraphRuntime; LangGraphRuntime(mode='fixture')"],
            env=environment, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_authoring_output_cannot_smuggle_runtime_action_or_unreachable_map(self):
        payload = fixture_draft(event(kind="map_draft"))
        payload["runtime_action"] = "apply_map"
        with self.assertRaises(ValidationError):
            self.runtime(draft_provider=lambda evt: payload).invoke(event(kind="map_draft"))
        payload = fixture_draft(event(kind="map_draft"))
        payload["rows"] = ["########", "#S#....#", "###....#", "#......#", "#......#", "########"]
        payload["objects"][0]["x"] = 4
        with self.assertRaisesRegex(ValidationError, "reachable"):
            MapDraft.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
