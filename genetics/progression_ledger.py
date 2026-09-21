"""Committed encounters and birth rewards, separate from immutable genetics.

Preparation commits identity, never XP. A completed birth consumes both parents'
reward keys in one SQLite transaction. Native receipts describe an already saved
transaction and are reconciled without applying its reward a second time. The
caller must select the authoritative save; receipts are not remote attestation.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager

from genetics.adventures import AdventureStore
from genetics.primers import canonical, digest, hash_id

LEDGER_VERSION = 1
REWARD_POLICY = "aurora-breeding-xp-v1"
BREEDING_XP = 125
CURVES = ("medium_fast", "erratic", "fluctuating", "medium_slow", "fast", "slow")


def _validate_binding(value: dict) -> None:
    keys = {"individual_id", "individual_sha256", "genome_sha256", "primer_ancestry",
            "reference_sha256", "expression_sha256", "source_art_sha256"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("strict individual binding required")
    for key in keys - {"primer_ancestry"}:
        hash_id(value[key])
    if (not isinstance(value["primer_ancestry"], list) or not 1 <= len(value["primer_ancestry"]) <= 64
            or any(not isinstance(p, dict) or set(p) != {"primer_id", "version"}
                   or not isinstance(p["primer_id"], str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", p["primer_id"])
                   or type(p["version"]) is not int or not 1 <= p["version"] <= 65535 for p in value["primer_ancestry"])):
        raise ValueError("frozen primer ancestry required")


def validate_manifest(value: dict) -> None:
    """Validate portable immutable event bytes without opening a mutable store."""
    keys = {"schema_version", "adventure_id", "encounters", "birth_events", "manifest_sha256"}
    if (not isinstance(value, dict) or set(value) != keys or type(value["schema_version"]) is not int
            or value["schema_version"] != LEDGER_VERSION or len(canonical(value)) > 512 * 1024
            or not isinstance(value["encounters"], list) or not isinstance(value["birth_events"], list)
            or len(value["encounters"]) > 16 or len(value["birth_events"]) > 16
            or value["manifest_sha256"] != digest({k: v for k, v in value.items() if k != "manifest_sha256"})):
        raise ValueError("unsupported or changed native ledger manifest")
    hash_id(value["adventure_id"])
    encounters, births, seen_individuals = set(), set(), set()
    for event in value["encounters"]:
        if (not isinstance(event, dict) or set(event) != {"schema_version", "adventure_id", "encounter_intent", "individual_id", "binding", "initial_owner", "event_id"}
                or type(event["schema_version"]) is not int or event["schema_version"] != LEDGER_VERSION
                or event["adventure_id"] != value["adventure_id"]
                or event["event_id"] != digest({k: v for k, v in event.items() if k != "event_id"})):
            raise ValueError("changed encounter event")
        _intent(event["encounter_intent"])
        if event["encounter_intent"] in encounters or event["individual_id"] in seen_individuals:
            raise ValueError("duplicate encounter intent or identity")
        encounters.add(event["encounter_intent"])
        seen_individuals.add(event["individual_id"])
        binding = event["binding"]
        if not isinstance(binding, dict) or not {"battle_profile_sha256", "battle_profile_version"} <= set(binding):
            raise ValueError("encounter requires a retained battle profile")
        _validate_binding({k: v for k, v in binding.items() if k not in ("battle_profile_sha256", "battle_profile_version")})
        hash_id(binding["battle_profile_sha256"])
        from genetics.battle_profiles import BATTLE_POLICY_VERSION
        if binding["individual_id"] != event["individual_id"] or binding["battle_profile_version"] != BATTLE_POLICY_VERSION:
            raise ValueError("encounter profile identity/version mismatch")
        owner = event["initial_owner"]
        if not isinstance(owner, dict) or set(owner) != {"kind", "key"} or owner["kind"] not in ("wild", "trainer"):
            raise ValueError("invalid encounter initial owner")
        if owner["kind"] == "wild" and owner["key"] is not None:
            raise ValueError("wild ownership has no trainer key")
        if owner["kind"] == "trainer":
            _intent(owner["key"])
    for exported in value["birth_events"]:
        if not isinstance(exported, dict) or set(exported) != {"schema_version", "adventure_id", "birth_intent", "child_individual_id", "child_binding", "parents", "policy_version", "event_id", "status", "receipt"}:
            raise ValueError("strict birth event required")
        event = {k: v for k, v in exported.items() if k not in ("status", "receipt")}
        if (type(event["schema_version"]) is not int or event["schema_version"] != LEDGER_VERSION
                or event["adventure_id"] != value["adventure_id"] or event["policy_version"] != REWARD_POLICY
                or event["event_id"] != digest({k: v for k, v in event.items() if k != "event_id"})
                or exported["status"] not in ("prepared", "completed", "historical")
                or (exported["status"] == "prepared") != (exported["receipt"] is None)):
            raise ValueError("changed birth event or completion state")
        _intent(event["birth_intent"])
        if event["birth_intent"] in births:
            raise ValueError("duplicate birth intent")
        births.add(event["birth_intent"])
        _validate_binding(event["child_binding"])
        if event["child_binding"]["individual_id"] != event["child_individual_id"]:
            raise ValueError("birth child identity mismatch")
        if not isinstance(event["parents"], list) or len(event["parents"]) != 2:
            raise ValueError("birth requires two parents")
        parent_ids = set()
        for parent in event["parents"]:
            if not isinstance(parent, dict) or set(parent) != {"individual_id", "binding", "reward_key", "xp"}:
                raise ValueError("strict parent reward required")
            _validate_binding(parent["binding"])
            if (parent["binding"]["individual_id"] != parent["individual_id"] or parent["individual_id"] in parent_ids
                    or parent["individual_id"] == event["child_individual_id"]
                    or parent["reward_key"] != digest([REWARD_POLICY, value["adventure_id"], event["birth_intent"], parent["individual_id"]])
                    or type(parent["xp"]) is not int or parent["xp"] != BREEDING_XP):
                raise ValueError("birth reward policy/identity mismatch")
            parent_ids.add(parent["individual_id"])


def _intent(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}", value):
        raise ValueError("bounded stable intent required")
    return value


def experience_at_level(level: int, curve: str) -> int:
    """Pinned Emerald growth tables, including integer rounding and level one."""
    if type(level) is not int or not 1 <= level <= 100 or curve not in CURVES:
        raise ValueError("supported growth curve and level 1..100 required")
    if level == 1:
        return 1
    cube = level ** 3
    if curve == "medium_fast":
        return cube
    if curve == "fast":
        return 4 * cube // 5
    if curve == "slow":
        return 5 * cube // 4
    if curve == "medium_slow":
        return 6 * cube // 5 - 15 * level ** 2 + 100 * level - 140
    if curve == "erratic":
        return ((100 - level) * cube // 50 if level <= 50 else
                (150 - level) * cube // 100 if level <= 68 else
                ((1911 - 10 * level) // 3) * cube // 500 if level <= 98 else
                (160 - level) * cube // 100)
    return (((level + 1) // 3 + 24) * cube // 50 if level <= 15 else
            (level + 14) * cube // 50 if level <= 36 else
            (level // 2 + 32) * cube // 50)


def level_from_experience(xp: int, curve: str) -> int:
    if type(xp) is not int or not 0 <= xp <= experience_at_level(100, curve):
        raise ValueError("XP must fit the retained growth curve")
    return max((level for level in range(1, 101) if experience_at_level(level, curve) <= xp), default=1)


class ProgressionLedger:
    """Open only a copied adventure when preparing a new playable milestone."""

    def __init__(self, store: AdventureStore):
        self.store = store
        self.adventure_id = store.manifest["adventure_id"]
        self.db = sqlite3.connect(store.path / "progression.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS birth_events(
                intent TEXT PRIMARY KEY,event_json TEXT,status TEXT NOT NULL,receipt_json TEXT);
            CREATE TABLE IF NOT EXISTS rewards(
                reward_key TEXT PRIMARY KEY,event_id TEXT NOT NULL,parent_id TEXT NOT NULL,
                receipt_json TEXT NOT NULL,UNIQUE(event_id,parent_id));
            CREATE TABLE IF NOT EXISTS progression(
                individual_id TEXT PRIMARY KEY,curve TEXT NOT NULL,xp INTEGER NOT NULL,
                origin_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS encounters(
                intent TEXT PRIMARY KEY,event_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ownership(
                individual_id TEXT PRIMARY KEY,owner_kind TEXT NOT NULL,owner_key TEXT,
                capture_json TEXT);
            CREATE TABLE IF NOT EXISTS exports(
                manifest_sha256 TEXT PRIMARY KEY,payload TEXT NOT NULL);
        """)
        with self._transaction():
            expected = canonical({"version": LEDGER_VERSION, "adventure_manifest_sha256": digest(store.manifest)}).decode()
            old = self.db.execute("SELECT value FROM metadata WHERE key='binding'").fetchone()
            if old and old[0] != expected:
                raise ValueError("progression ledger belongs to a different adventure or version")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('binding',?)", (expected,))

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def close(self) -> None:
        self.db.close()

    def individual_binding(self, individual_id: str) -> dict:
        individual = self.store.individual(individual_id)
        profile = self.store.accepted(individual_id, "profile")
        art = self.store.accepted(individual_id, "source-art")
        if profile is None or art is None:
            raise ValueError("accepted expression and retained source art required")
        return {"individual_id": individual_id, "individual_sha256": digest(individual),
                "genome_sha256": individual["genome_sha256"], "primer_ancestry": individual["primer_ancestry"],
                "reference_sha256": digest(self.store.manifest["reference"]),
                "expression_sha256": profile["sha256"], "source_art_sha256": art["sha256"]}

    def prepare_birth(self, birth_intent: str) -> dict:
        """Freeze a playable birth event after acceptance; do not complete it."""
        _intent(birth_intent)
        child = self.store.individual(self.store.birth_status(birth_intent)["individual_id"])
        if child["parents"] is None:
            raise ValueError("founders have no reproductive parents to reward")
        parents = [{"individual_id": parent, "binding": self.individual_binding(parent),
                    "reward_key": digest([REWARD_POLICY, self.adventure_id, birth_intent, parent]),
                    "xp": BREEDING_XP} for parent in child["parents"]]
        event = {"schema_version": LEDGER_VERSION, "adventure_id": self.adventure_id,
                 "birth_intent": birth_intent, "child_individual_id": child["id"],
                 "child_binding": self.individual_binding(child["id"]),
                 "parents": parents, "policy_version": REWARD_POLICY}
        event["event_id"] = digest(event)
        with self._transaction():
            row = self.db.execute("SELECT * FROM birth_events WHERE intent=?", (birth_intent,)).fetchone()
            if row:
                if row["status"] in ("failed", "cancelled"):
                    raise ValueError("failed or cancelled birth cannot complete")
                if json.loads(row["event_json"]) != event:
                    raise ValueError("prepared birth bindings cannot change")
            else:
                self.db.execute("INSERT INTO birth_events VALUES(?,?,'prepared',NULL)", (birth_intent, canonical(event).decode()))
        return event

    def stop_birth(self, birth_intent: str, *, status: str) -> None:
        """Durably close failed/cancelled attempts; neither state grants XP."""
        _intent(birth_intent)
        self.store.birth_status(birth_intent)
        if status not in ("failed", "cancelled"):
            raise ValueError("terminal failure or cancellation required")
        with self._transaction():
            row = self.db.execute("SELECT status FROM birth_events WHERE intent=?", (birth_intent,)).fetchone()
            if row and row["status"] != status and row["status"] != "prepared":
                raise ValueError("terminal birth outcome cannot change")
            self.db.execute("INSERT INTO birth_events VALUES(?,NULL,?,NULL) ON CONFLICT(intent) DO UPDATE SET status=excluded.status",
                            (birth_intent, status))

    def birth_status(self, birth_intent: str) -> dict:
        row = self.db.execute("SELECT * FROM birth_events WHERE intent=?", (_intent(birth_intent),)).fetchone()
        if row is None:
            raise KeyError(birth_intent)
        return {"status": row["status"], "event": json.loads(row["event_json"]) if row["event_json"] else None,
                "receipt": json.loads(row["receipt_json"]) if row["receipt_json"] else None}

    def import_progress(self, individual_id: str, *, xp: int, curve: str, origin: dict) -> dict:
        """Explicit initial snapshot migration; never reset existing progress."""
        self.store.individual(individual_id)
        level_from_experience(xp, curve)
        if not isinstance(origin, dict) or not origin or len(canonical(origin)) > 4096:
            raise ValueError("bounded explicit migration provenance required")
        with self._transaction():
            row = self.db.execute("SELECT * FROM progression WHERE individual_id=?", (individual_id,)).fetchone()
            if row:
                if (row["curve"], row["xp"], row["origin_json"]) != (curve, xp, canonical(origin).decode()):
                    raise ValueError("progress already exists; migration cannot overwrite XP or its curve")
            else:
                self.db.execute("INSERT INTO progression VALUES(?,?,?,?)", (individual_id, curve, xp, canonical(origin).decode()))
        return self.progress(individual_id)

    def progress(self, individual_id: str) -> dict:
        row = self.db.execute("SELECT * FROM progression WHERE individual_id=?", (hash_id(individual_id),)).fetchone()
        if row is None:
            raise KeyError(individual_id)
        return {"individual_id": individual_id, "curve": row["curve"], "xp": row["xp"],
                "level": level_from_experience(row["xp"], row["curve"])}

    def _reward_receipts(self, event: dict, *, historical: bool = False) -> list[dict]:
        values = []
        for parent in event["parents"]:
            progress = self.progress(parent["individual_id"])
            before = progress["xp"]
            after = before if historical else min(before + parent["xp"], experience_at_level(100, progress["curve"]))
            values.append({"individual_id": parent["individual_id"], "reward_key": parent["reward_key"],
                           "curve": progress["curve"], "xp_before": before, "xp_after": after})
        return values

    def _commit_completion(self, event: dict, receipt: dict) -> dict:
        row = self.db.execute("SELECT * FROM birth_events WHERE intent=?", (event["birth_intent"],)).fetchone()
        if row["status"] in ("completed", "historical"):
            old = json.loads(row["receipt_json"])
            if old != receipt:
                raise ValueError("birth already consumed with a different receipt")
            return old
        if row["status"] != "prepared":
            raise ValueError("only a successfully prepared birth can complete")
        for parent in receipt["parents"]:
            self.db.execute("INSERT INTO rewards VALUES(?,?,?,?)", (parent["reward_key"], event["event_id"], parent["individual_id"], canonical(parent).decode()))
            self.db.execute("UPDATE progression SET xp=? WHERE individual_id=?", (parent["xp_after"], parent["individual_id"]))
        self.db.execute("UPDATE birth_events SET status=?,receipt_json=? WHERE intent=?",
                        ("historical" if receipt["historical_migration"] else "completed", canonical(receipt).decode(), event["birth_intent"]))
        return receipt

    def complete_birth(self, birth_intent: str) -> dict:
        """Explicit host completion, atomically awarding both retained parents."""
        event = self.prepare_birth(birth_intent)
        with self._transaction():
            state = self.birth_status(birth_intent)
            if state["status"] in ("completed", "historical"):
                return state["receipt"]
            receipt = {"schema_version": LEDGER_VERSION, "adventure_id": self.adventure_id,
                       "event_id": event["event_id"], "origin": "host", "historical_migration": False,
                       "parents": self._reward_receipts(event)}
            return self._commit_completion(event, receipt)

    def prepare_encounter(self, encounter_intent: str, individual_id: str, *, battle_profile: dict,
                          owner_kind: str = "wild", owner_key: str | None = None) -> dict:
        """Commit the complete individual before it can be placed in battle."""
        _intent(encounter_intent)
        if owner_kind not in ("wild", "trainer") or (owner_kind == "wild" and owner_key is not None):
            raise ValueError("wild or named trainer encounter ownership required")
        if owner_kind == "trainer":
            _intent(owner_key)
        # The battle contract is imported lazily to keep birth-only use independent.
        from genetics.battle_profiles import validate_battle_profile
        retained = self.store.accepted(individual_id, "profile")
        if retained is None:
            raise ValueError("accepted expression required before encounter")
        validate_battle_profile(battle_profile, individual=self.store.individual(individual_id),
                               expression=json.loads(self.store.object_bytes(retained)),
                               expression_sha256=retained["sha256"])
        binding = self.individual_binding(individual_id)
        if battle_profile["individual_id"] != individual_id:
            raise ValueError("battle profile belongs to a different individual")
        binding |= {"battle_profile_sha256": battle_profile["profile_sha256"], "battle_profile_version": battle_profile["policy_version"]}
        event = {"schema_version": LEDGER_VERSION, "adventure_id": self.adventure_id,
                 "encounter_intent": encounter_intent, "individual_id": individual_id, "binding": binding,
                 "initial_owner": {"kind": owner_kind, "key": owner_key}}
        event["event_id"] = digest(event)
        with self._transaction():
            old = self.db.execute("SELECT event_json FROM encounters WHERE intent=?", (encounter_intent,)).fetchone()
            if old:
                if json.loads(old[0]) != event:
                    raise ValueError("encounter intent already binds a different individual")
                return event
            owner = self.db.execute("SELECT * FROM ownership WHERE individual_id=?", (individual_id,)).fetchone()
            if owner is not None:
                raise ValueError("individual already owns a durable encounter or ownership record")
            self.db.execute("INSERT INTO encounters VALUES(?,?)", (encounter_intent, canonical(event).decode()))
            self.db.execute("INSERT INTO ownership VALUES(?,?,?,NULL)", (individual_id, owner_kind, owner_key))
        return event

    def encounter(self, encounter_intent: str) -> dict:
        row = self.db.execute("SELECT event_json FROM encounters WHERE intent=?", (_intent(encounter_intent),)).fetchone()
        if row is None:
            raise KeyError(encounter_intent)
        return json.loads(row[0])

    def ownership(self, individual_id: str) -> dict:
        row = self.db.execute("SELECT * FROM ownership WHERE individual_id=?", (hash_id(individual_id),)).fetchone()
        if row is None:
            raise KeyError(individual_id)
        return {"individual_id": individual_id, "kind": row["owner_kind"], "key": row["owner_key"],
                "capture": json.loads(row["capture_json"]) if row["capture_json"] else None}

    def capture(self, encounter_intent: str, *, player_key: str, observation: dict) -> dict:
        """Transfer exact committed identity; battle loss/run do not call this."""
        _intent(player_key)
        if not isinstance(observation, dict) or not observation or len(canonical(observation)) > 4096:
            raise ValueError("bounded explicit successful capture observation required")
        event = self.encounter(encounter_intent)
        receipt = {"event_id": event["event_id"], "individual_id": event["binding"]["individual_id"],
                   "player_key": player_key, "observation": observation}
        with self._transaction():
            owner = self.ownership(receipt["individual_id"])
            if owner["capture"] is not None:
                if owner["capture"] != receipt:
                    raise ValueError("captured identity already belongs to a committed player")
                return receipt
            if owner["kind"] != "wild":
                raise ValueError("trainer-owned individuals cannot be captured")
            self.db.execute("UPDATE ownership SET owner_kind='player',owner_key=?,capture_json=? WHERE individual_id=?",
                            (player_key, canonical(receipt).decode(), receipt["individual_id"]))
        return receipt

    def export_manifest(self, *, encounter_intents: list[str], birth_intents: list[str]) -> dict:
        """Freeze exact native import data, including any already consumed keys."""
        if len(encounter_intents) > 16 or len(birth_intents) > 16 or len(set(encounter_intents)) != len(encounter_intents) or len(set(birth_intents)) != len(birth_intents):
            raise ValueError("bounded distinct native event selection required")
        with self._transaction():
            births = [self.birth_status(intent) for intent in birth_intents]
            if any(item["status"] in ("failed", "cancelled") for item in births):
                raise ValueError("failed and cancelled births cannot be exported for completion")
            value = {"schema_version": LEDGER_VERSION, "adventure_id": self.adventure_id,
                     "encounters": [self.encounter(intent) for intent in encounter_intents],
                     "birth_events": [item["event"] | {"status": item["status"], "receipt": item["receipt"]} for item in births]}
            value["manifest_sha256"] = digest(value)
            validate_manifest(value)
            self.db.execute("INSERT OR IGNORE INTO exports VALUES(?,?)", (value["manifest_sha256"], canonical(value).decode()))
        return value

    def reconcile_native_birth(self, birth_intent: str, receipt: dict, *, expected_manifest_sha256: str) -> dict:
        """Import an authoritative saved native transaction, never reapply XP.

        Receipt keys: schema_version, adventure_id, event_id, origin='native',
        manifest_sha256, historical_migration, parents. Both ordered parents carry
        individual_id, reward_key, curve, xp_before, xp_after. Historical v1 saves
        report equal XP values and consume the preissued child without reward.
        """
        hash_id(expected_manifest_sha256)
        event = self.prepare_birth(birth_intent)
        keys = {"schema_version", "adventure_id", "event_id", "origin", "manifest_sha256", "historical_migration", "parents"}
        if (not isinstance(receipt, dict) or set(receipt) != keys or receipt["schema_version"] != LEDGER_VERSION
                or receipt["adventure_id"] != self.adventure_id or receipt["event_id"] != event["event_id"]
                or receipt["origin"] != "native" or receipt["manifest_sha256"] != expected_manifest_sha256
                or type(receipt["historical_migration"]) is not bool or not isinstance(receipt["parents"], list)
                or len(receipt["parents"]) != 2):
            raise ValueError("native completion receipt does not bind the selected manifest/event")
        with self._transaction():
            exported = self.db.execute("SELECT payload FROM exports WHERE manifest_sha256=?", (expected_manifest_sha256,)).fetchone()
            if exported is None or not any({k: v for k, v in row.items() if k not in ("status", "receipt")} == event
                                           for row in json.loads(exported[0])["birth_events"]):
                raise ValueError("native event must come from a retained ledger export")
            current = self.birth_status(birth_intent)
            if current["status"] in ("completed", "historical"):
                if current["receipt"] != receipt:
                    raise ValueError("native receipt conflicts with already consumed birth")
                return current["receipt"]
            for parent, observed in zip(event["parents"], receipt["parents"]):
                if (not isinstance(observed, dict) or set(observed) != {"individual_id", "reward_key", "curve", "xp_before", "xp_after"}
                        or observed["individual_id"] != parent["individual_id"] or observed["reward_key"] != parent["reward_key"]):
                    raise ValueError("native receipt parent identity/reward key mismatch")
                level_from_experience(observed["xp_before"], observed["curve"])
                expected_after = observed["xp_before"] if receipt["historical_migration"] else min(observed["xp_before"] + parent["xp"], experience_at_level(100, observed["curve"]))
                if type(observed["xp_after"]) is not int or observed["xp_after"] != expected_after:
                    raise ValueError("native receipt does not preserve bounded XP policy")
                previous = self.db.execute("SELECT curve,xp FROM progression WHERE individual_id=?", (parent["individual_id"],)).fetchone()
                if previous and (previous["curve"], previous["xp"]) != (observed["curve"], observed["xp_before"]):
                    raise ValueError("native receipt conflicts with retained parent progression")
                self.db.execute("INSERT OR IGNORE INTO progression VALUES(?,?,?,?)", (parent["individual_id"], observed["curve"], observed["xp_before"], canonical({"native_manifest_sha256": expected_manifest_sha256}).decode()))
            return self._commit_completion(event, receipt)
