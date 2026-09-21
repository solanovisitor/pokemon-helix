"""Loopback transport. Slow inference runs in a worker, never an emulator callback."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .protocol import MAX_WIRE, ProtocolError, Request, encode_text, parse_request, response_wire
from game_agents.public_lore import validate_public_encoded, validate_public_text


class EventLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: str, **fields: object) -> None:
        row = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        line = json.dumps(row, sort_keys=True)
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        print(line, flush=True)


class Companion:
    def __init__(self, provider: Callable[[Request], str], *, mode: str = "fixture",
                 log: Callable[..., None] | None = None, timeout: float = 8.5, lifecycle=None,
                 voice=None, voice_provider=None, setup=None, lab=None):
        self.provider = provider
        self.mode = mode
        self.log = log or EventLog()
        self.timeout = timeout
        # Bound global inference concurrency. A disconnected client cannot flood workers.
        self.worker = asyncio.Semaphore(1)
        self.clients = 0
        self.workers: set[asyncio.Task[str]] = set()
        self.lifecycle = lifecycle
        self.voice, self.voice_provider = voice, voice_provider
        self.setup = setup
        self.lab = lab

    async def generate(self, request: Request, active: Callable[[], bool], utterance: str = "") -> str:
        async with self.worker:
            if not active():
                raise ProtocolError("request expired before inference")
            if utterance and self.voice_provider:
                return await asyncio.to_thread(self.voice_provider, request, utterance)
            return await asyncio.to_thread(self.provider, request)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.clients >= 4:
            writer.close()
            await writer.wait_closed()
            return
        self.clients += 1
        self.log("connected", mode=self.mode)
        current: Request | None = None
        task: asyncio.Task[None] | None = None
        seen: OrderedDict[tuple[str, int, int], tuple[Request, bytes | None]] = OrderedDict()
        session_base: str | None = None
        generation, highest_request, epoch = -1, 0, 0

        async def resolve(request: Request) -> None:
            started = time.monotonic()
            wire = response_wire(request)
            expired = False
            try:
                utterance = await asyncio.wait_for(self.voice.utterance(request), self.timeout) if self.voice else ""
                # The worker owns its semaphore until HTTPS finishes. Timeout/cancel
                # discard its result without blocking the reader or permitting overlap.
                if len(self.workers) >= 4:
                    raise ProtocolError("provider busy")
                worker = asyncio.create_task(self.generate(request, lambda: not expired and current == request, utterance))
                self.workers.add(worker)
                def finished(done: asyncio.Task[str]) -> None:
                    self.workers.discard(done)
                    if not done.cancelled():
                        done.exception()  # Retrieve failures of cancelled/expired requests.
                worker.add_done_callback(finished)
                remaining = max(0.001, self.timeout - (time.monotonic() - started))
                text = await asyncio.wait_for(asyncio.shield(worker), remaining)
                validate_public_text(text)
                encoded = encode_text(text)
                validate_public_encoded(encoded)
                wire = response_wire(request, encoded)
                if self.voice:
                    self.voice.prepared(request, text, spoken=bool(utterance))
            except asyncio.CancelledError:
                expired = True
                return
            except Exception as exc:
                expired = True
                if self.voice:
                    self.voice.cancel(request)
                # Never log provider response bodies, HTTP error strings, keys or prompts.
                self.log("provider_error", request=request.request, kind=type(exc).__name__)
            if current != request or writer.is_closing():
                return
            seen[request.key] = (request, wire)
            writer.write(wire)
            await writer.drain()
            self.log("response", epoch=request.epoch, request=request.request, npc=request.npc,
                     motivation=request.motivation, quest=request.quest, mode=self.mode,
                     status="OK" if b"|OK|" in wire else "ERROR",
                     elapsed_ms=round((time.monotonic() - started) * 1000))

        try:
            first_line = True
            while line := await reader.readline():
                if first_line and line.startswith(b"LAB1|") and self.lab is not None:
                    await self.lab.handle(reader, writer, line)
                    return
                if first_line and line.startswith(b"HLS1|") and self.setup is not None:
                    await self.setup.handle(reader, writer, line)
                    return
                if first_line and line.startswith(b"AUR1|") and self.lifecycle is not None:
                    await self.lifecycle.handle(reader, writer, line)
                    return
                first_line = False
                kind, request = parse_request(line)
                if kind == "ACK":
                    previous = seen.get(request.key)
                    if (self.voice and current == request and previous and previous[0] == request
                            and previous[1] is not None and b"|OK|" in previous[1]):
                        self.voice.acknowledge(request)
                    continue
                if kind == "CANCEL":
                    if current == request:
                        if self.voice:
                            self.voice.cancel(request)
                        current = None
                        if task:
                            task.cancel()
                        seen[request.key] = (request, None)
                        self.log("cancelled", epoch=request.epoch, request=request.request)
                    continue
                previous = seen.get(request.key)
                if previous:
                    if previous[0] != request:
                        raise ProtocolError("identity reuse with changed state")
                    # Duplicates are idempotent; cancellation is a tombstone.
                    if previous[1] is not None and current == request:
                        writer.write(previous[1])
                        await writer.drain()
                        self.log("duplicate", request=request.request)
                    continue
                base, counter = request.session.rsplit("-", 1)
                counter = int(counter)
                if session_base is not None and base != session_base:
                    raise ProtocolError("session identity changed")
                if counter < generation:
                    raise ProtocolError("stale session")
                if counter == generation and (request.epoch != epoch or request.request <= highest_request):
                    raise ProtocolError("stale request or epoch")
                session_base, generation = base, counter
                highest_request, epoch = request.request, request.epoch
                if current and task and not task.done():
                    task.cancel()
                    seen[current.key] = (current, None)
                current = request
                if self.voice:
                    self.voice.begin(request)
                seen[request.key] = (request, None)
                if len(seen) > 64:
                    seen.popitem(last=False)
                self.log("request", epoch=request.epoch, request=request.request,
                         npc=request.npc, motivation=request.motivation, quest=request.quest, mode=self.mode)
                task = asyncio.create_task(resolve(request))
        except (ProtocolError, ValueError, ConnectionError):
            self.log("peer_rejected")
        finally:
            if self.voice and current:
                self.voice.cancel(current)
            current = None
            if task:
                task.cancel()
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.clients -= 1
            self.log("disconnected")

    async def serve(self, host: str, port: int) -> None:
        server = await asyncio.start_server(self.handle, host, port, limit=MAX_WIRE)
        self.log("ready", host=host, port=port, mode=self.mode)
        async with server:
            await server.serve_forever()
