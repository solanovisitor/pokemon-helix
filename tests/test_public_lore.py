"""Adversarial public-output boundaries; no provider call or private input."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from companion.protocol import Request, encode_text, response_wire
from companion.server import Companion
from game_agents.drafts import fixture_draft
from game_agents.memory import MemoryStore
from game_agents.npc_quest_generator import (
    DraftNarrative, JointProposal, NpcQuestQueue, SYSTEM_PROMPT, approved_context,
    assemble, export_candidate, fixture_narrative, request,
)
from game_agents.public_lore import (
    PublicLoreError, validate_public_encoded, validate_public_text, validate_public_value,
)
from game_agents.schemas import DRAFT_SCHEMAS, Dialogue, GameEvent, make_dialogue
from game_agents.service import LangGraphRuntime


def event(kind="npc_dialogue"):
    return GameEvent(kind=kind, save_id="public-review", session="a" * 32 + "-0",
                     epoch=1, sequence=1, rom={"motivation": 1, "quest": 1},
                     brief="An optional village clue." if kind != "npc_dialogue" else "")


class PublicLoreTests(unittest.TestCase):
    def test_reserved_name_rejected_under_normalization_and_basic_obfuscation(self):
        variants = ["Veilwarden", "VEILWARDEN", "veIlWaRdEn", "Véïlwárdén", "Ｖｅｉｌｗａｒｄｅｎ",
                    "Veil\u200bwarden", "Veil\x00warden", "Ve1lw4rden", "ve1lw4rden"]
        variants += [separator.join("Veilwarden") for separator in (" ", "\n", ".", "-", "_", "/", "💫")]
        for value in variants:
            with self.subTest(value=value), self.assertRaises(PublicLoreError) as failure:
                validate_public_text("A visitor mentions " + value + ".")
            self.assertEqual(str(failure.exception), "Public content is unavailable.")

    def test_unrelated_public_text_is_accepted_unchanged(self):
        for text in ("We watch a silver beacon in the village.",
                     "A vila observa uma luz prateada.",
                     "The fixture secret is not amber.", "The amber light varies.",
                     "The veil is thin.", "Amar e cuidar."):
            validate_public_text(text)
            self.assertTrue(make_dialogue(text).text)

    def test_synthetic_policy_sentences_are_rejected_without_overbroad_word_ban(self):
        for text in ("The fixture secret is amber.", "O segredo de teste e ambar.",
                     "O segredo de teste é âmbar."):
            with self.subTest(text=text), self.assertRaises(PublicLoreError):
                validate_public_text(text)
        validate_public_text("The beacon has amber light; this is a fixture.")

    def test_raw_dialogue_is_checked_before_lossy_truncation(self):
        text = "A quiet garden. " * 40 + "Veilwarden"
        # Native encoding alone drops the trailing disclosure; the output gate
        # must still refuse the entire raw response instead of silently hiding it.
        validate_public_encoded(encode_text(text))
        with self.assertRaises(PublicLoreError):
            make_dialogue(text)

    def test_exact_encoded_payload_is_checked_even_with_benign_declared_text(self):
        encoded = encode_text("V e i l w a r d e n")
        with self.assertRaises(PublicLoreError):
            validate_public_encoded(encoded)
        with self.assertRaises(ValidationError) as failure:
            Dialogue(text="A quiet garden.", encoded_hex=encoded.hex())
        self.assertIn("Public content is unavailable", str(failure.exception))
        self.assertNotIn("V e i l w a r d e n", str(failure.exception))

    def test_every_nested_draft_string_is_checked_before_field_errors(self):
        for kind in DRAFT_SCHEMAS:
            original = fixture_draft(event(kind))
            mutations = [(key,) for key in ("title", "rationale")]
            mutations += {"world_draft": [("premise",), ("hooks", 0)],
                          "scene_draft": [("objective",), ("beats", 0), ("dialogue", 0)],
                          "map_draft": [("objects", 0, "label")]}[kind]
            for path in mutations:
                value = deepcopy(original)
                target = value
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = "Veilwarden " * 100
                with self.subTest(kind=kind, path=path), self.assertRaises(ValidationError) as failure:
                    DRAFT_SCHEMAS[kind].model_validate(value)
                self.assertNotIn("Veilwarden", str(failure.exception))

    def test_all_npc_names_and_nested_copy_fields_are_guarded(self):
        narrative = fixture_narrative(2)
        paths = []
        def visit(value, path=()):
            if isinstance(value, dict):
                for key, part in value.items():
                    if key in ("en", "pt", "name"):
                        paths.append(path + (key,))
                    elif isinstance(part, (dict, list)):
                        visit(part, path + (key,))
            elif isinstance(value, list):
                for index, part in enumerate(value):
                    visit(part, path + (index,))
        visit(narrative)
        self.assertGreater(len(paths), 40)
        for path in paths:
            value = deepcopy(narrative)
            target = value
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = "VEILWARDEN"
            with self.subTest(path=path), self.assertRaises(ValidationError) as failure:
                DraftNarrative.model_validate(value)
            self.assertNotIn("VEILWARDEN", str(failure.exception))

    def test_preconstructed_models_are_revalidated_and_cycles_refused(self):
        poisoned = Dialogue.model_construct(text="Veilwarden", encoded_hex=encode_text("Veilwarden").hex())
        with self.assertRaises(ValidationError):
            Dialogue.model_validate(poisoned)
        cycle = []
        cycle.append(cycle)
        with self.assertRaises(PublicLoreError):
            validate_public_value(cycle)

    def test_rules_do_not_enter_provider_schema_or_approved_context(self):
        req = request(2)
        wire = json.dumps({"context": approved_context(req), "prompt": SYSTEM_PROMPT,
                           "schemas": [schema.model_json_schema() for schema in
                                       (Dialogue, JointProposal, DraftNarrative, *DRAFT_SCHEMAS.values())]})
        for private_term in ("veilwarden", "fixture secret is amber", "segredo de teste e ambar"):
            self.assertNotIn(private_term, wire.casefold())

    def test_actual_graph_rejects_provider_or_cached_text_before_memory_or_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            memory = Path(temp) / "memory.sqlite3"
            runtime = LangGraphRuntime(memory_path=memory, provider=lambda *args: "Veilwarden")
            with self.assertRaises(PublicLoreError):
                runtime.invoke(event())
            store = MemoryStore(memory)
            self.assertEqual(store.load(event())["records"], [])
            # Historical caches are untrusted too: revalidation precedes delivery.
            store.remember(event(), "Veilwarden")
            with self.assertRaises(PublicLoreError):
                runtime.invoke(event())

    def test_candidate_export_and_mock_live_result_refuse_publication(self):
        bad = fixture_narrative(1)
        bad["npcs"][0]["name"] = "VEILWARDEN"
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "export"
            candidate = assemble(request(1), fixture_narrative(1))
            candidate["narrative"] = bad
            with self.assertRaises(ValidationError):
                export_candidate(candidate, destination)
            self.assertFalse(destination.exists())
            queue = NpcQuestQueue(Path(temp) / "queue")
            self.addCleanup(queue.close)
            queue.plan(request(1, mode="deepagents", model="example/model"))
            proposal = {"title": bad["title"], "npcs": [
                {key: npc[key] for key in ("role", "name", "motivation", "greeting")}
                for npc in bad["npcs"]]}
            with patch("game_agents.deepagents_adapter.invoke_candidate", return_value=proposal), \
                    self.assertRaises(ValidationError):
                queue.run(key="synthetic-not-a-credential")
            self.assertFalse((Path(temp) / "queue" / "results").exists())
            self.assertNotEqual(queue.db.execute("SELECT status FROM jobs").fetchone()[0], "complete")


class PublicLoreTransportTests(unittest.IsolatedAsyncioTestCase):
    async def direct_exchange(self, text):
        logs = []
        voice = Mock()
        async def utterance(_):
            return ""
        voice.utterance = utterance
        service = Companion(lambda request: text, voice=voice,
                            log=lambda event_name, **fields: logs.append((event_name, fields)))
        server = await asyncio.start_server(service.handle, "127.0.0.1", 0, limit=640)
        reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
        req = Request("a" * 32 + "-0", 1, 1, 1, 1, 1)
        try:
            writer.write(req.wire())
            await writer.drain()
            wire = await asyncio.wait_for(reader.readline(), 5)
            return req, wire, logs, voice, voice.cancel.call_count
        finally:
            writer.close()
            await writer.wait_closed()
            server.close()
            await server.wait_closed()
            if service.workers:
                await asyncio.gather(*service.workers, return_exceptions=True)
            await asyncio.sleep(0)

    async def test_direct_provider_cannot_bypass_guard_or_hide_text_after_truncation(self):
        for text in ("Veilwarden", "V.é.ï.l.w.á.r.d.é.n", "A quiet garden. " * 40 + "Veilwarden"):
            with self.subTest(text=text):
                req, wire, logs, voice, cancelled = await self.direct_exchange(text)
                self.assertEqual(wire, response_wire(req))
                self.assertEqual(cancelled, 1)
                voice.prepared.assert_not_called()
                self.assertNotIn("veilwarden", json.dumps(logs).casefold())
                self.assertTrue(any(name == "provider_error" for name, fields in logs))

    async def test_direct_provider_allowed_text_preserves_success_and_voice(self):
        text = "We watch a silver beacon in the village."
        req, wire, logs, voice, cancelled = await self.direct_exchange(text)
        self.assertEqual(wire, response_wire(req, encode_text(text)))
        self.assertEqual(cancelled, 0)
        voice.prepared.assert_called_once_with(req, text, spoken=False)
        self.assertFalse(any(name == "provider_error" for name, fields in logs))

    async def test_final_encoded_payload_is_rechecked_independently_of_raw_text(self):
        with patch("companion.server.encode_text", return_value=encode_text("Veilwarden")):
            req, wire, logs, voice, cancelled = await self.direct_exchange("A quiet garden.")
        self.assertEqual(wire, response_wire(req))
        self.assertEqual(cancelled, 1)
        voice.prepared.assert_not_called()
        self.assertNotIn("veilwarden", json.dumps(logs).casefold())

    async def test_actual_graph_transport_returns_generic_error_and_never_speaks_rejected_text(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = LangGraphRuntime(memory_path=Path(temp) / "memory.sqlite3",
                                       provider=lambda *args: "Veilwarden")
            logs = []
            voice = Mock()
            async def utterance(_):
                return ""
            voice.utterance = utterance
            service = Companion(lambda req: runtime.dialogue(req, save_id="public-review"),
                                log=lambda event_name, **fields: logs.append((event_name, fields)), voice=voice)
            server = await asyncio.start_server(service.handle, "127.0.0.1", 0, limit=640)
            reader, writer = await asyncio.open_connection("127.0.0.1", server.sockets[0].getsockname()[1])
            req = Request("a" * 32 + "-0", 1, 1, 1, 1, 1)
            try:
                writer.write(req.wire())
                await writer.drain()
                wire = await asyncio.wait_for(reader.readline(), 5)
                self.assertEqual(wire, response_wire(req))
                self.assertNotIn("veilwarden", json.dumps(logs).casefold())
                voice.prepared.assert_not_called()
                voice.cancel.assert_called_with(req)
            finally:
                writer.close()
                await writer.wait_closed()
                server.close()
                await server.wait_closed()
                if service.workers:
                    await asyncio.gather(*service.workers, return_exceptions=True)
                await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
