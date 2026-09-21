from __future__ import annotations

import asyncio
from dataclasses import replace
import io
import json
import threading
import unittest
from unittest.mock import patch

from companion.protocol import (CHARMAP, ProtocolError, Request, encode_text,
                                parse_request, response_wire, validate_encoded)
from companion.providers import fixture, openrouter
from companion.server import Companion


BASE = Request("a" * 32 + "-1", 57, 1, 1, 1, 1)


class ProtocolTests(unittest.TestCase):
    def test_request_roundtrip_and_rejects_malformed_or_unsupported_state(self):
        self.assertEqual(parse_request(BASE.wire()), ("REQ", BASE))
        bad = [BASE.wire()[:-1], b"x" * 641 + b"\n", BASE.wire().replace(b"GBA1", b"GBA2"),
               replace(BASE, npc=5).wire(), replace(BASE, epoch=0).wire(),
               replace(BASE, request=2**32).wire(), replace(BASE, motivation=0).wire(),
               BASE.wire().replace(b"|57|", b"|1.0|"), BASE.wire() + b"junk", b"\xff\n"]
        for wire in bad:
            with self.subTest(wire=wire[:70]), self.assertRaises(ProtocolError):
                parse_request(wire)

    def test_encoding_is_gba_not_utf8_and_strips_untrusted_control_bytes(self):
        self.assertEqual(encode_text("Ivo: Olá!"), bytes(CHARMAP[c] for c in "Ivo: Ola!"))
        encoded = encode_text("Olá\x00\xfd\xfc\xff" + " muito" * 100 + " 🐉")
        validate_encoded(encoded)
        self.assertLessEqual(len(encoded), 123)
        self.assertNotIn(0xFC, encoded)
        self.assertNotIn(0xFD, encoded)
        self.assertNotIn(0xFF, encoded)
        self.assertEqual(encoded.count(b"\xfb"), 1)
        self.assertTrue(encoded.endswith(bytes([0xAD] * 3)))

    def test_rejects_raw_game_control_sequences_and_bad_pagination(self):
        for payload in (b"", b"\xfc\x01", b"\xff", b"\xfe\xbb", b"\xbb\xfe\xbb\xfe\xbb",
                        b"\xbb\xfb\xbb\xfb\xbb", b"\xbb" * 31, b"\xbb\xfb"):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                validate_encoded(payload)

    def test_all_scene_states_have_bounded_fixture_dialogue(self):
        for quest in range(4):
            for motivation in (1, 2):
                request = replace(BASE, quest=quest, motivation=motivation)
                validate_encoded(encode_text(fixture(request)))
        self.assertIn("curiosity", fixture(replace(BASE, quest=3)))
        self.assertIn("wish to help", fixture(replace(BASE, motivation=2, quest=3)))

    def test_openrouter_validates_schema_and_sends_only_authored_game_context(self):
        content = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Ivo: Oi!"}}]}).encode()
        with patch("companion.providers.urlopen", return_value=io.BytesIO(content)) as call:
            self.assertEqual(openrouter(BASE, key="test-secret", model="test/model"), "Ivo: Oi!")
        http = call.call_args.args[0]
        body = json.loads(http.data)
        self.assertEqual(body["model"], "test/model")
        self.assertEqual(body["max_tokens"], 100)
        self.assertNotIn("test-secret", http.data.decode())
        self.assertNotIn(BASE.session, http.data.decode())
        for payload in ({"error": {"message": "secret"}}, {"choices": []},
                        {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{}]}}]}):
            with patch("companion.providers.urlopen", return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(ProtocolError):
                    openrouter(BASE, key="key", model="test/model")

    def test_openrouter_limits_prior_context_and_keeps_rom_facts_authoritative(self):
        content = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "Oi!"}}]}).encode()
        context = {"persona": {"name": "Ivo"}, "memory": [{"text": "A pista mudou.", "delivery": "unconfirmed"}]}
        with patch("companion.providers.urlopen", return_value=io.BytesIO(content)) as call:
            openrouter(BASE, key="key", model="test/model", context=context)
        body = json.loads(call.call_args.args[0].data)
        sent = json.loads(body["messages"][1]["content"])
        self.assertEqual(sent["current_game_state"]["quest"], BASE.quest)
        self.assertEqual(sent["selected_prior_context"], context)
        self.assertIn("take precedence", body["messages"][0]["content"])
        self.assertIn("unconfirmed", body["messages"][0]["content"])
        for invalid in ({"memory": [{}] * 7}, {"memory": "arbitrary"}, {"api_key": "private"},
                        {"persona": "x" * 12001}, {"memory": [object()]}):
            with patch("companion.providers.urlopen") as call, self.assertRaises(ProtocolError):
                openrouter(BASE, key="key", model="test/model", context=invalid)
            call.assert_not_called()


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []
        self.calls = []
        self.release = threading.Event()
        self.release.set()
        self.fail = False
        def provider(request):
            self.calls.append(request)
            self.release.wait(2)
            if self.fail:
                raise ValueError("private provider data must not enter logs")
            return fixture(request)
        self.service = Companion(provider, log=lambda event, **kw: self.events.append((event, kw)))
        self.server = await asyncio.start_server(self.service.handle, "127.0.0.1", 0, limit=640)
        self.port = self.server.sockets[0].getsockname()[1]
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)

    async def asyncTearDown(self):
        self.release.set()
        self.writer.close()
        await self.writer.wait_closed()
        self.server.close()
        await self.server.wait_closed()
        if self.service.workers:
            await asyncio.gather(*self.service.workers, return_exceptions=True)
        await asyncio.sleep(0)

    async def send(self, request=BASE, kind="REQ"):
        self.writer.write(request.wire(kind))
        await self.writer.drain()

    async def read(self):
        return await asyncio.wait_for(self.reader.readline(), 1)

    async def test_actual_tcp_roundtrip_and_duplicate_is_cached(self):
        await self.send()
        first = await self.read()
        self.assertEqual(first, response_wire(BASE, encode_text(fixture(BASE))))
        await self.send()
        self.assertEqual(await self.read(), first)
        self.assertEqual(len(self.calls), 1)

    async def test_changed_state_cannot_reuse_id(self):
        await self.send()
        await self.read()
        await self.send(replace(BASE, quest=2))
        self.assertEqual(await self.read(), b"")
        self.assertEqual(len(self.calls), 1)

    async def test_cancel_discards_late_response_and_next_request_recovers(self):
        self.release.clear()
        await self.send()
        await asyncio.sleep(0.03)
        await self.send(kind="CANCEL")
        await asyncio.sleep(0.03)
        self.release.set()
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(self.reader.readline(), 0.06)
        second = replace(BASE, request=2, quest=2)
        await self.send(second)
        self.assertEqual(await self.read(), response_wire(second, encode_text(fixture(second))))

    async def test_timeout_responds_without_waiting_for_provider_and_logs_no_exception_text(self):
        self.release.clear()
        self.service.timeout = 0.03
        await self.send()
        self.assertEqual(await self.read(), response_wire(BASE))
        self.assertFalse(self.release.is_set())
        self.release.set()
        self.fail = True
        await self.send(replace(BASE, request=2))
        await self.read()
        self.assertNotIn("private provider", repr(self.events))

    async def test_old_session_rejected_after_reset(self):
        await self.send()
        await self.read()
        new = replace(BASE, session="a" * 32 + "-2", epoch=99)
        await self.send(new)
        await self.read()
        await self.send(replace(BASE, request=2))
        self.assertEqual(await self.read(), b"")

    async def test_restart_connection_does_not_inherit_pending_request(self):
        self.release.clear()
        await self.send()
        await asyncio.sleep(0.02)
        self.writer.close()
        await self.writer.wait_closed()
        self.release.set()
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
        second = replace(BASE, quest=2)
        await self.send(second)
        self.assertEqual(await self.read(), response_wire(second, encode_text(fixture(second))))

    async def test_malformed_socket_peer_is_closed(self):
        self.writer.write(b"GBA1|REQ|not valid\n")
        await self.writer.drain()
        self.assertEqual(await self.read(), b"")
        self.assertEqual(self.calls, [])

    async def test_evicted_old_id_cannot_trigger_inference_again(self):
        for sequence in range(1, 67):
            await self.send(replace(BASE, request=sequence))
            await self.read()
        await self.send()
        self.assertEqual(await self.read(), b"")
        self.assertEqual(len(self.calls), 66)


if __name__ == "__main__":
    unittest.main()
