"""Durable daily authoring plans; projections never contain private canon.

This host service supplies draft context only. It cannot edit a ROM, save,
accepted adventure, individual, artwork, inventory, or battle rule.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Literal
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class WorldPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              revalidate_instances="always")
    schema_version: Literal[1] = 1
    story_focus: Literal["shared_care", "exploration", "cooperation"]
    ecology: Literal["steady", "tide_pools", "reed_growth"]
    encounter: Literal["balanced", "curious", "sheltered"]
    learning: Literal["inheritance", "variation", "habitat"]
    pace: Literal["gentle", "steady"]

    @field_validator("schema_version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("unsupported schema version")
        return value


class WorldObservations(BaseModel):
    """Counts from trusted backend events, never dialogue or player identifiers."""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              revalidate_instances="always")
    active_adventures: int = Field(default=0, ge=0, le=1_000_000_000)
    completed_adventures: int = Field(default=0, ge=0, le=1_000_000_000)
    births: int = Field(default=0, ge=0, le=1_000_000_000)
    encounters: int = Field(default=0, ge=0, le=1_000_000_000)
    discovered_loci: int = Field(default=0, ge=0, le=1_000_000_000)


BASELINE = WorldPlan(story_focus="shared_care", ecology="steady",
                     encounter="balanced", learning="inheritance", pace="gentle")
ROLES = ("npc", "world", "scene", "map", "ecology", "encounter")
REGIONS = ("aurora_coast",)
FACETS = {
    "story_focus": ("shared_care", "exploration", "cooperation"),
    "ecology": ("steady", "tide_pools", "reed_growth"),
    "encounter": ("balanced", "curious", "sheltered"),
    "learning": ("inheritance", "variation", "habitat"),
    "pace": ("gentle", "steady"),
}
GUIDANCE = {
    "story_focus": {
        "shared_care": "Suggest small, optional stories about caring for companions and their home.",
        "exploration": "Suggest optional discoveries near familiar places, with a clear way home.",
        "cooperation": "Suggest small, optional stories in which neighbors help one another.",
    },
    "ecology": {
        "steady": "Keep the coast familiar. Notice everyday signs of life around water and reeds.",
        "tide_pools": "For future drafts, notice tide pools and animals finding shelter near water.",
        "reed_growth": "For future drafts, notice new reeds and the shelter they offer small animals.",
    },
    "encounter": {
        "balanced": "Draft a familiar mix of encounters with room to explore at the player's pace.",
        "curious": "Draft optional encounters with curious companions near places of discovery.",
        "sheltered": "Draft optional encounters near safe resting places and natural shelter.",
    },
    "learning": {
        "inheritance": "When useful, explain simply that a child receives traits from both parents.",
        "variation": "When useful, explain simply that relatives can still look and act differently.",
        "habitat": "When useful, explain simply how a place can help some traits be more useful.",
    },
    "pace": {
        "gentle": "Keep requests short and optional. Give the player time to care, explore and battle.",
        "steady": "Offer one clear next step at a time and keep room for care, exploration and battles.",
    },
}
ROLE_FACETS = {
    "npc": ("story_focus", "learning", "pace"),
    "world": ("story_focus", "ecology", "encounter", "learning", "pace"),
    "scene": ("story_focus", "ecology", "learning", "pace"),
    "map": ("ecology", "pace"),
    "ecology": ("ecology", "learning", "pace"),
    "encounter": ("encounter", "ecology", "pace"),
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _time(now: datetime | None) -> datetime:
    now = datetime.now(timezone.utc) if now is None else now
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return now.astimezone(timezone.utc)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load_canon(path: str | Path | None) -> dict | None:
    if path is None:
        return None
    path = Path(path).resolve()
    if ".local" not in path.parts[:-1] or path.suffix != ".json":
        raise ValueError("private canon must be a JSON file inside .local")
    if path.stat().st_size > 8192:
        raise ValueError("private canon exceeds 8 KiB")
    with path.open("rb") as handle:
        raw = handle.read(8193)
    if len(raw) > 8192:
        raise ValueError("private canon exceeds 8 KiB")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        _json(value)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError("private canon must be a bounded JSON object") from None
    return value


def fixture_plan(request: dict) -> WorldPlan:
    """Bounded authored fixtures; the legacy default rotates one facet per day."""
    previous = request["previous_plan"] or BASELINE.model_dump()
    plan = dict(previous)
    if request.get("fixture_policy") == "confirmed_events":
        counts = request["observations"]
        if counts["completed_adventures"] or counts["discovered_loci"]:
            plan.update(story_focus="exploration", learning="habitat")
        elif counts["active_adventures"]:
            plan.update(story_focus="shared_care", pace="gentle")
        elif counts["encounters"]:
            plan.update(encounter="curious", ecology="tide_pools")
        return WorldPlan.model_validate(plan)
    seed = hashlib.sha256(request["cycle"].encode()).digest()
    facet = tuple(FACETS)[seed[0] % len(FACETS)]
    choices = FACETS[facet]
    plan[facet] = choices[(choices.index(plan[facet]) + 1) % len(choices)]
    return WorldPlan.model_validate(plan)


class WorldPlannerStore:
    """Durable calendar-day or rolling-24h claims and immutable adventure pins.

    Provider callback input: schema_version, cycle, observations, previous_plan,
    output_schema and private_canon. Only strict WorldPlan output is retained.
    A provider exception has unknown outcome and is never retried in that cycle.
    """

    def __init__(self, path: str | Path, world_id: str = "local-world", *,
                 cadence: Literal["utc_calendar_day", "rolling_24h"] = "utc_calendar_day"):
        if not isinstance(world_id, str) or not 1 <= len(world_id) <= 160:
            raise ValueError("world_id must contain 1..160 characters")
        self.path = Path(path)
        self.world_id = world_id
        if cadence not in {"utc_calendar_day", "rolling_24h"}:
            raise ValueError("unsupported planner cadence")
        self.cadence = cadence
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.touch(mode=0o600, exist_ok=True)
        self.path.chmod(0o600)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS world_planner_schema(version INTEGER NOT NULL);
                INSERT INTO world_planner_schema SELECT 1
                  WHERE NOT EXISTS(SELECT 1 FROM world_planner_schema);
                CREATE TABLE IF NOT EXISTS world_cycles(
                  world TEXT NOT NULL, cycle TEXT NOT NULL, status TEXT NOT NULL,
                  claimed_at TEXT NOT NULL, finished_at TEXT, claim_token TEXT NOT NULL,
                  mode TEXT NOT NULL, input_digest TEXT NOT NULL,
                  previous_plan_id INTEGER, plan_id INTEGER, error_code TEXT,
                  PRIMARY KEY(world, cycle));
                CREATE TABLE IF NOT EXISTS world_plans(
                  id INTEGER PRIMARY KEY AUTOINCREMENT, world TEXT NOT NULL,
                  revision INTEGER NOT NULL, cycle TEXT NOT NULL,
                  previous_plan_id INTEGER, accepted_at TEXT NOT NULL,
                  plan_json TEXT NOT NULL, plan_digest TEXT NOT NULL,
                  UNIQUE(world, revision), UNIQUE(world, cycle));
                CREATE TABLE IF NOT EXISTS world_adventure_pins(
                  world TEXT NOT NULL, adventure_digest TEXT NOT NULL,
                  revision INTEGER NOT NULL, cycle TEXT, plan_json TEXT NOT NULL,
                  plan_digest TEXT NOT NULL, PRIMARY KEY(world, adventure_digest));
                CREATE TABLE IF NOT EXISTS world_planner_cadence(
                  world TEXT PRIMARY KEY, cadence TEXT NOT NULL);
            """)
            versions = db.execute("SELECT version FROM world_planner_schema").fetchall()
            if len(versions) != 1 or versions[0][0] != 1:
                raise ValueError("unsupported world planner schema")
            db.execute("BEGIN IMMEDIATE")
            configured = db.execute("SELECT cadence FROM world_planner_cadence WHERE world=?",
                                    (self.world_id,)).fetchone()
            if configured is None:
                if cadence != "utc_calendar_day" and db.execute(
                        "SELECT 1 FROM world_cycles WHERE world=? LIMIT 1",
                        (self.world_id,)).fetchone():
                    raise ValueError("existing UTC calendar history cannot change cadence")
                db.execute("INSERT INTO world_planner_cadence VALUES(?,?)", (self.world_id, cadence))
            elif configured["cadence"] != cadence:
                raise ValueError("stored planner cadence cannot change")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _latest_row(self, db):
        return db.execute("SELECT * FROM world_plans WHERE world=? ORDER BY revision DESC LIMIT 1",
                          (self.world_id,)).fetchone()

    @staticmethod
    def _record(row) -> dict | None:
        if row is None:
            return None
        try:
            data = WorldPlan.model_validate_json(row["plan_json"]).model_dump()
            if _digest(data) != row["plan_digest"]:
                raise ValueError()
        except (ValidationError, ValueError, TypeError):
            raise ValueError("stored plan integrity check failed") from None
        return {"revision": row["revision"], "cycle": row["cycle"],
                "plan_digest": row["plan_digest"],
                "plan": data}

    def latest_plan(self) -> dict | None:
        with self._connect() as db:
            return self._record(self._latest_row(db))

    def _window(self, db, timestamp: datetime) -> dict:
        if self.cadence == "utc_calendar_day":
            cycle = timestamp.date().isoformat()
            next_due = timestamp.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            last = db.execute("SELECT cycle,claimed_at FROM world_cycles WHERE world=? "
                              "ORDER BY claimed_at DESC LIMIT 1", (self.world_id,)).fetchone()
            if last is not None:
                next_due = _time(datetime.fromisoformat(last["claimed_at"])) + timedelta(hours=24)
                if timestamp < next_due:
                    return {"cycle": last["cycle"], "due": False,
                            "next_due_at": next_due.isoformat()}
            cycle = timestamp.isoformat()
            next_due = timestamp + timedelta(hours=24)
        claimed = db.execute("SELECT 1 FROM world_cycles WHERE world=? AND cycle=?",
                             (self.world_id, cycle)).fetchone()
        return {"cycle": cycle, "due": claimed is None, "next_due_at": next_due.isoformat()}

    def planning_window(self, *, now: datetime | None = None) -> dict:
        """Read the next/current window; tick rechecks it under its write lock."""
        with self._connect() as db:
            return self._window(db, _time(now))

    def plan_for_cycle(self, cycle: str) -> dict | None:
        with self._connect() as db:
            return self._record(db.execute("SELECT * FROM world_plans WHERE world=? AND cycle=?",
                                           (self.world_id, cycle)).fetchone())

    def tick(self, *, now: datetime | None = None,
             observations: dict | WorldObservations | None = None,
             provider: Callable[[dict], dict | WorldPlan] | None = None,
             private_canon_path: str | Path | None = None,
             fixture_policy: Literal["calendar_rotation", "confirmed_events"] = "calendar_rotation") -> dict:
        timestamp = _time(now)
        # Retained outcomes do not depend on today's config files still existing.
        with self._connect() as db:
            cycle = self._window(db, timestamp)["cycle"]
            existing = self._existing_or_outdated(db, cycle)
            if existing is not None:
                return existing
        counts = WorldObservations.model_validate(
            {} if observations is None else observations).model_dump()
        if fixture_policy not in {"calendar_rotation", "confirmed_events"}:
            raise ValueError("unsupported fixture policy")
        if fixture_policy == "confirmed_events" and (provider is not None or private_canon_path is not None):
            raise ValueError("confirmed fixture policy cannot invoke live providers or private canon")
        canon = _load_canon(private_canon_path)
        token = uuid.uuid4().hex
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cycle = self._window(db, timestamp)["cycle"]
            existing = self._existing_or_outdated(db, cycle)
            if existing is not None:
                return existing
            latest = self._latest_row(db)
            latest_record = self._record(latest)
            request = {"schema_version": 1, "cycle": cycle, "observations": counts,
                       "previous_plan": None if latest_record is None else latest_record["plan"],
                       "output_schema": WorldPlan.model_json_schema(), "private_canon": canon}
            if fixture_policy != "calendar_rotation":
                request["fixture_policy"] = fixture_policy
            previous_id = None if latest is None else latest["id"]
            db.execute("""INSERT INTO world_cycles
                (world,cycle,status,claimed_at,claim_token,mode,input_digest,previous_plan_id)
                VALUES(?,?,'running',?,?,?,?,?)""",
                (self.world_id, cycle, timestamp.isoformat(), token,
                 "fixture" if provider is None else "live", _digest(request), previous_id))
        previous_plan_snapshot = (None if request["previous_plan"] is None
                                  else dict(request["previous_plan"]))
        # The transaction ends before any external call. Never retain raw model text.
        try:
            raw = (provider or fixture_plan)(request)
        except BaseException as exc:
            self._finish_failure(cycle, token, "unknown", "provider_outcome_unknown", timestamp)
            if not isinstance(exc, Exception):
                raise
            return self.cycle_status(cycle)
        try:
            plan = WorldPlan.model_validate(raw)
            if previous_plan_snapshot is not None:
                changed = sum(plan.model_dump()[key] != previous_plan_snapshot[key]
                              for key in FACETS)
                if changed > 2:
                    raise ValueError("too many daily changes")
        except (ValidationError, ValueError, TypeError):
            self._finish_failure(cycle, token, "rejected", "invalid_plan", timestamp)
            return self.cycle_status(cycle)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM world_cycles WHERE world=? AND cycle=?",
                             (self.world_id, cycle)).fetchone()
            if row["status"] != "running" or row["claim_token"] != token:
                return self._cycle_result(db, cycle)
            latest = self._latest_row(db)
            self._record(latest)
            latest_id = None if latest is None else latest["id"]
            if latest_id != previous_id:
                db.execute("""UPDATE world_cycles SET status='superseded', error_code='lineage_changed',
                           finished_at=? WHERE world=? AND cycle=?""",
                           (timestamp.isoformat(), self.world_id, cycle))
                return self._cycle_result(db, cycle)
            revision = 1 if latest is None else latest["revision"] + 1
            data = plan.model_dump()
            cursor = db.execute("""INSERT INTO world_plans
                (world,revision,cycle,previous_plan_id,accepted_at,plan_json,plan_digest)
                VALUES(?,?,?,?,?,?,?)""", (self.world_id, revision, cycle, previous_id,
                timestamp.isoformat(), _json(data), _digest(data)))
            db.execute("""UPDATE world_cycles SET status='accepted', plan_id=?, finished_at=?
                       WHERE world=? AND cycle=? AND claim_token=?""",
                       (cursor.lastrowid, timestamp.isoformat(), self.world_id, cycle, token))
            return self._cycle_result(db, cycle)

    def _finish_failure(self, cycle, token, status, code, timestamp):
        with self._connect() as db:
            db.execute("""UPDATE world_cycles SET status=?, error_code=?, finished_at=?
                       WHERE world=? AND cycle=? AND claim_token=? AND status='running'""",
                       (status, code, timestamp.isoformat(), self.world_id, cycle, token))

    def _existing_or_outdated(self, db, cycle):
        if db.execute("SELECT 1 FROM world_cycles WHERE world=? AND cycle=?",
                      (self.world_id, cycle)).fetchone():
            return self._cycle_result(db, cycle)
        latest = self._latest_row(db)
        if latest is not None and cycle <= latest["cycle"]:
            return {"cycle": cycle, "status": "outdated", "error_code": None,
                    "latest_plan": self._record(latest)}
        return None

    def _cycle_result(self, db, cycle):
        row = db.execute("SELECT status,error_code FROM world_cycles WHERE world=? AND cycle=?",
                         (self.world_id, cycle)).fetchone()
        return {"cycle": cycle, "status": None if row is None else row["status"],
                "error_code": None if row is None else row["error_code"],
                "latest_plan": self._record(self._latest_row(db))}

    def cycle_status(self, cycle: str) -> dict:
        with self._connect() as db:
            return self._cycle_result(db, cycle)

    def status(self) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT cycle FROM world_cycles WHERE world=? ORDER BY cycle DESC LIMIT 1",
                             (self.world_id,)).fetchone()
            return {"schema_version": 1, "cadence": ("UTC calendar day" if self.cadence == "utc_calendar_day"
                                                     else "rolling 24 hours from last claim"),
                    "latest_cycle": None if row is None else self._cycle_result(db, row["cycle"]),
                    "latest_plan": self._record(self._latest_row(db)),
                    "pinned_adventures": db.execute("SELECT count(*) FROM world_adventure_pins WHERE world=?",
                                                    (self.world_id,)).fetchone()[0]}

    def mark_stale_unknown(self, *, now: datetime | None = None,
                           max_age_seconds: int = 300) -> int:
        """Close expired claims without reissuing them, including after a crash."""
        if type(max_age_seconds) is not int or not 60 <= max_age_seconds <= 86400:
            raise ValueError("claim age must be 60..86400 seconds")
        timestamp = _time(now)
        cutoff = datetime.fromtimestamp(timestamp.timestamp() - max_age_seconds, timezone.utc)
        with self._connect() as db:
            cursor = db.execute("""UPDATE world_cycles SET status='unknown',
                error_code='interrupted_claim',finished_at=?
                WHERE world=? AND status='running' AND claimed_at<=?""",
                (timestamp.isoformat(), self.world_id, cutoff.isoformat()))
            return cursor.rowcount

    def project_context(self, role: str, region: str = "aurora_coast",
                        adventure_id: str | None = None) -> dict:
        if role not in ROLES or region not in REGIONS:
            raise ValueError("unsupported public role or region")
        if adventure_id is not None and (not isinstance(adventure_id, str)
                                          or not 1 <= len(adventure_id) <= 256):
            raise ValueError("adventure_id must contain 1..256 characters")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._record(self._latest_row(db)) or {
                "revision": 0, "cycle": None, "plan": BASELINE.model_dump(),
                "plan_digest": _digest(BASELINE.model_dump())}
            if adventure_id is not None:
                identity = _digest(adventure_id)
                db.execute("""INSERT OR IGNORE INTO world_adventure_pins
                    (world,adventure_digest,revision,cycle,plan_json,plan_digest) VALUES(?,?,?,?,?,?)""",
                    (self.world_id, identity, record["revision"], record["cycle"],
                     _json(record["plan"]), record["plan_digest"]))
                pin = db.execute("SELECT * FROM world_adventure_pins WHERE world=? AND adventure_digest=?",
                                 (self.world_id, identity)).fetchone()
                record = self._record(pin)
        plan = record["plan"]
        return {"schema_version": 1, "status": "draft", "runtime_action": "none",
                "plan_revision": record["revision"], "plan_digest": record["plan_digest"],
                "cycle": record["cycle"], "role": role, "region": region,
                "guidance": [GUIDANCE[facet][plan[facet]] for facet in ROLE_FACETS[role]]}
