"""Offline, bounded laboratory jobs. No ROM/save access or remote inference.

The journal retains complete synthetic model results, not claims of native
commit. Only the ROM may consume material and save its own receipt.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import zlib

from genetics.lab_simulation import canonical, simulate, verify_result

MAX_WIRE = 640
MAX_JOBS = 10000
SESSION = re.compile(r"[a-f0-9]{32,48}-[0-9]{1,10}")


def parse(line: bytes) -> tuple[str, str, bytes]:
    if len(line) > MAX_WIRE or not line.endswith(b"\n"):
        raise ValueError("invalid lab frame length")
    fields = line[:-1].decode("ascii").split("|")
    if (len(fields) != 4 or fields[0] != "LAB1" or fields[1] not in ("REQ", "CANCEL")
            or SESSION.fullmatch(fields[2]) is None
            or re.fullmatch(r"[0-9a-f]{152}", fields[3]) is None):
        raise ValueError("invalid lab request")
    raw = bytes.fromhex(fields[3])
    epoch, request, model, receipt, condition, prediction, recipe, reserved = struct.unpack_from("<II6H", raw)
    if (not epoch or not request or model != 1 or receipt != 0x7003
            or condition not in (1, 2) or prediction not in (1, 2)
            or recipe not in (1, 2) or reserved
            or raw[36:68] == bytes(32)
            or struct.unpack_from("<I", raw, 72)[0] != zlib.crc32(raw[:72])):
        raise ValueError("unsupported or corrupt lab context")
    return fields[1], fields[2], raw


def result_for(session: str, raw: bytes) -> dict:
    _, _, _, receipt, condition, prediction, _, _ = struct.unpack_from("<II6H", raw)
    bindings = {
        "request_id": hashlib.sha256(session.encode() + raw[:8]).hexdigest(),
        "save_lineage": raw[20:36].hex(),
        "individual_id": raw[36:68].hex(),
        "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        "quest_revision": receipt,
    }
    args = ("sheltered" if condition == 1 else "exposed",
            "stable" if prediction == 1 else "sensitive", bindings)
    result = simulate(*args)
    verify_result(result, *args)
    return result


class LabService:
    def __init__(self, journal: Path, *, log=None):
        self.journal = Path(journal)
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        self.log = log or (lambda *args, **kwargs: None)
        self.busy = False
        self.clients = 0
        with self.database() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, context TEXT NOT NULL, result TEXT, cancelled INTEGER NOT NULL DEFAULT 0)")

    @contextmanager
    def database(self):
        db = sqlite3.connect(self.journal, timeout=0.5)
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def job(self, session: str, raw: bytes, *, cancel=False) -> dict | None:
        key = session + ":" + raw[:8].hex()
        context = raw.hex()
        with self.database() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT context,result,cancelled FROM jobs WHERE key=?", (key,)).fetchone()
            if prior and prior[0] != context:
                raise ValueError("lab identity reused with changed context")
            if not prior:
                if db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= MAX_JOBS:
                    raise ValueError("lab journal is full")
                db.execute("INSERT INTO jobs(key,context,cancelled) VALUES(?,?,?)", (key, context, int(cancel)))
            if cancel:
                db.execute("UPDATE jobs SET cancelled=1 WHERE key=?", (key,))
                return None
            if prior and prior[2]:
                return None
            result = result_for(session, raw)
            if prior and prior[1] is not None:
                if prior[1].encode() != canonical(result):
                    raise ValueError("retained lab result corrupt or version changed")
                return result
            db.execute("UPDATE jobs SET result=? WHERE key=?", (canonical(result).decode(), key))
            return result

    async def handle(self, reader, writer, first_line=None):
        if self.clients >= 1:
            writer.close()
            await writer.wait_closed()
            return
        self.clients += 1
        current = None
        task = None
        seen_session = None
        high = (-1, -1)
        epoch_seen = None
        latest = None

        async def resolve(session, raw):
            nonlocal current
            identity = (session, raw)
            prefix = b"LAB1|"
            try:
                if self.busy:
                    raise ValueError("lab worker busy")
                self.busy = True
                # Fixed-cost local calculation and durable I/O live off the
                # socket reader and emulator frame callback.
                worker = asyncio.create_task(asyncio.to_thread(self.job, session, raw))
                def done(future):
                    self.busy = False
                    if not future.cancelled():
                        future.exception()
                worker.add_done_callback(done)
                result = await asyncio.wait_for(asyncio.shield(worker), 2.0)
                if result is None:
                    raise ValueError("cancelled lab job")
                payload = struct.pack("<4H", result["result_code"], result["signal"], result["span"], result["control"])
                wire = (prefix + b"OK|" + session.encode() + b"|" + raw.hex().encode()
                        + b"|" + payload.hex().encode() + b"|" + result["result_sha256"].encode() + b"\n")
                self.log("lab_computed", input_sha256=result["input_sha256"], result_sha256=result["result_sha256"], model=result["model"])
            except asyncio.CancelledError:
                return
            except (ValueError, sqlite3.Error, asyncio.TimeoutError):
                wire = prefix + b"ERROR|" + session.encode() + b"|" + raw.hex().encode() + b"||\n"
            if current == identity and not writer.is_closing():
                writer.write(wire)
                await writer.drain()

        try:
            line = first_line
            while True:
                if line is None:
                    line = await reader.readline()
                if not line:
                    break
                kind, session, raw = parse(line)
                line = None
                base, generation = session.rsplit("-", 1)
                seq = struct.unpack_from("<I", raw, 4)[0]
                epoch = struct.unpack_from("<I", raw)[0]
                position = (int(generation), seq)
                if seen_session is not None and base != seen_session:
                    raise ValueError("lab session changed")
                if position < high:
                    raise ValueError("stale lab sequence")
                if position[0] == high[0] and epoch_seen != epoch:
                    raise ValueError("lab epoch changed without generation")
                if position == high and latest != raw:
                    raise ValueError("lab request identity reused")
                seen_session, high = base, position
                epoch_seen, latest = epoch, raw
                if kind == "CANCEL":
                    if current == (session, raw):
                        current = None
                        if task:
                            task.cancel()
                    await asyncio.to_thread(self.job, session, raw, cancel=True)
                    continue
                if task and not task.done():
                    if current == (session, raw):
                        continue  # Duplicate cannot spawn a second job.
                    raise ValueError("one outstanding lab job")
                current = (session, raw)
                task = asyncio.create_task(resolve(session, raw))
        except (ValueError, UnicodeError, ConnectionError, sqlite3.Error):
            self.log("lab_peer_rejected")
        finally:
            current = None
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.clients -= 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--journal", type=Path, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    async def serve():
        service = LabService(args.journal)
        server = await asyncio.start_server(service.handle, args.host, args.port, limit=MAX_WIRE)
        print(json.dumps({"ready": True, "host": args.host, "port": args.port, "mode": "synthetic-offline-v1"}), flush=True)
        async with server:
            await server.serve_forever()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
