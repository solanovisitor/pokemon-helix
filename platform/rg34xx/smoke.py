"""Exercise the real local lab TCP service on Linux without a ROM or emulator."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import selectors
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]


def context(sequence, condition=1):
    body = (struct.pack("<II6H", 123, sequence, 1, 0x7003, condition, 1, 1, 0)
            + bytes(range(16)) + bytes(range(32)) + struct.pack("<I", 0x89abcdef))
    return body + struct.pack("<I", zlib.crc32(body))


def exchange(port, raw, *, cancel=False):
    session = "0123456789abcdef" * 2 + "-1"
    identity = session.encode() + b"|" + raw.hex().encode()
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        stream = connection.makefile("rb")
        if cancel:
            connection.sendall(b"LAB1|CANCEL|" + identity + b"\n")
        connection.sendall(b"LAB1|REQ|" + identity + b"\n")
        reply = stream.readline(641)
        if cancel:
            assert reply == b"LAB1|ERROR|" + identity + b"||\n", reply
        else:
            parts = reply.rstrip(b"\n").split(b"|")
            assert len(parts) == 6 and parts[:2] == [b"LAB1", b"OK"]
            assert b"|".join(parts[2:4]) == identity
            assert parts[4] == b"01000b0003000a00", reply
            assert len(parts[5]) == 64
        return reply


def start_service(journal, port):
    command = [sys.executable, "-m", "companion.lab_service", "--host", "127.0.0.1",
               "--port", str(port), "--journal", str(journal)]
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if selector.select(timeout=3):
            line = process.stdout.readline()
            if line and json.loads(line).get("ready") is True:
                return process
    process.terminate()
    process.wait(timeout=3)
    raise RuntimeError("local service did not become ready")


def stop_service(process):
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def main():
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        port = candidate.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="helix-portability-") as directory:
        journal = Path(directory) / "synthetic-jobs.sqlite"
        process = start_service(journal, port)
        try:
            first = exchange(port, context(1))
            replay = exchange(port, context(1))
            assert replay == first
            exchange(port, context(2), cancel=True)
        finally:
            stop_service(process)
        process = start_service(journal, port)
        try:
            assert exchange(port, context(1)) == first
            exchange(port, context(2), cancel=True)
        finally:
            stop_service(process)
        with sqlite3.connect(journal) as db:
            rows = db.execute("SELECT result,cancelled FROM jobs ORDER BY key").fetchall()
        assert len(rows) == 2 and sum(row[1] for row in rows) == 1
        retained = [json.loads(row[0]) for row in rows if row[0] is not None]
        assert len(retained) == 1 and retained[0]["signal"] == 11
        source_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "companion/lab_service.py", "genetics/lab_simulation.py", "platform/rg34xx/smoke.py")}
        print(json.dumps({"passed": True, "platform": platform.system(), "architecture": platform.machine(),
                          "python": platform.python_version(), "uid": os.getuid(), "journal_rows": len(rows),
                          "checks": ["real_loopback_tcp", "known_assay_result", "byte_identical_replay",
                                     "cancel_tombstone", "restart_replay", "complete_result_journal"],
                          "source_sha256": source_hashes,
                          "not_tested": ["RG34XX hardware", "mGBA", "ROM", "KNULLI kernel", "peripherals"]}, sort_keys=True))


if __name__ == "__main__":
    main()
