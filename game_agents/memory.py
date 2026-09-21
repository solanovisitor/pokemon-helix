"""Private SQLite memory of observations and generated, unconfirmed dialogue."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3

from companion.protocol import ProtocolError
from .schemas import GameEvent


class MemoryStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        self.path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS npc_head (
                save_id TEXT, npc_id TEXT, branch INTEGER, quest INTEGER, motivation INTEGER,
                active_session TEXT,
                PRIMARY KEY (save_id, npc_id));
            CREATE TABLE IF NOT EXISTS session_head (
                save_id TEXT, npc_id TEXT, session_base TEXT, generation INTEGER, epoch INTEGER, sequence INTEGER,
                PRIMARY KEY (save_id, npc_id, session_base));
            CREATE TABLE IF NOT EXISTS dialogue_memory (
                id INTEGER PRIMARY KEY, save_id TEXT, npc_id TEXT, event_key TEXT, event_hash TEXT,
                branch INTEGER, quest INTEGER, motivation INTEGER, dialogue TEXT,
                delivery TEXT NOT NULL DEFAULT 'generated_unconfirmed',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (save_id, npc_id, event_key));
        """)
        if "active_session" not in {row[1] for row in connection.execute("PRAGMA table_info(npc_head)")}:
            connection.execute("ALTER TABLE npc_head ADD COLUMN active_session TEXT")
            connection.commit()
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def event_hash(event: GameEvent) -> str:
        return sha256(event.model_dump_json().encode()).hexdigest()

    def _check(self, db: sqlite3.Connection, event: GameEvent) -> tuple[int, str | None]:
        params = (event.memory_scope, event.npc_id)
        existing = db.execute("SELECT event_hash, branch, dialogue FROM dialogue_memory WHERE save_id=? AND npc_id=? AND event_key=?",
                              (*params, event.event_key)).fetchone()
        base, generation_text = event.session.rsplit("-", 1)
        generation = int(generation_text)
        previous_session = db.execute("SELECT * FROM session_head WHERE save_id=? AND npc_id=? AND session_base=?", (*params, base)).fetchone()
        head = db.execute("SELECT * FROM npc_head WHERE save_id=? AND npc_id=?", params).fetchone()
        if previous_session and head and head["active_session"] not in (None, base):
            raise ProtocolError("stale transport session")
        same_generation = previous_session and generation == previous_session["generation"]
        if previous_session and (generation < previous_session["generation"] or (same_generation and
                (event.epoch != previous_session["epoch"] or event.sequence < previous_session["sequence"]))):
            raise ProtocolError("stale event or epoch")
        if existing:
            if existing["event_hash"] != self.event_hash(event):
                raise ProtocolError("event identity reused with different ROM state")
            return existing["branch"], existing["dialogue"]
        if same_generation and event.sequence == previous_session["sequence"]:
            raise ProtocolError("sequence was already consumed")
        if head is None:
            return 0, None
        rollback = event.rom.quest < head["quest"] or (head["motivation"] != 0 and event.rom.motivation != head["motivation"])
        if rollback and same_generation:
            raise ProtocolError("state regressed without a save/reload session boundary")
        return head["branch"] + int(rollback), None

    def load(self, event: GameEvent) -> dict:
        with self.connection() as db:
            branch, cached = self._check(db, event)
            rows = db.execute("""SELECT quest, motivation, dialogue, delivery FROM dialogue_memory
                WHERE save_id=? AND npc_id=? AND branch=? ORDER BY id DESC LIMIT 6""",
                (event.memory_scope, event.npc_id, branch)).fetchall()
            return {"branch": branch, "cached": cached, "records": [dict(row) for row in reversed(rows)]}

    def remember(self, event: GameEvent, text: str) -> str:
        with self.connection() as db:
            with db:
                db.execute("BEGIN IMMEDIATE")
                branch, cached = self._check(db, event)
                if cached is not None:
                    return cached
                params = (event.memory_scope, event.npc_id)
                db.execute("INSERT INTO dialogue_memory (save_id,npc_id,event_key,event_hash,branch,quest,motivation,dialogue) VALUES (?,?,?,?,?,?,?,?)",
                           (*params, event.event_key, self.event_hash(event), branch, event.rom.quest, event.rom.motivation, text))
                base, generation = event.session.rsplit("-", 1)
                db.execute("INSERT OR REPLACE INTO npc_head VALUES (?,?,?,?,?,?)", (*params, branch, event.rom.quest, event.rom.motivation, base))
                db.execute("INSERT OR REPLACE INTO session_head VALUES (?,?,?,?,?,?)", (*params, base, int(generation), event.epoch, event.sequence))
                # Retain at most 100 generated turns per save/NPC, across branches.
                db.execute("""DELETE FROM dialogue_memory WHERE save_id=? AND npc_id=? AND id NOT IN
                    (SELECT id FROM dialogue_memory WHERE save_id=? AND npc_id=? ORDER BY id DESC LIMIT 100)""", (*params, *params))
        return text
