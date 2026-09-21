"""Durable bounded generation DAGs and portable original-art dataset exports.

Planning/reservation never invokes a model. Workers must explicitly mark the
external boundary before a request; an expired external attempt is unknown and
cannot be silently replayed. Accepted AdventureStore objects remain authoritative.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Iterable

from genetics.adventures import AdventureStore, validate_family
from genetics.primers import canonical, digest, hash_id, identifier

STAGES = ("profile", "source-art", "conversion-review")
MAX_WORKERS = 32
MAX_SHARD_ROWS = 1000


def job_id(adventure_id: str, individual_id: str, stage: str) -> str:
    hash_id(adventure_id); hash_id(individual_id)
    if stage not in STAGES:
        raise ValueError("unsupported batch stage")
    return digest(["aurora-batch-v1", adventure_id, individual_id, stage])


def _bounded_note(value: str) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 1024:
        raise ValueError("explicit bounded reconciliation/review note required")
    return value


class BatchQueue:
    def __init__(self, directory: str | Path, *, max_workers: int = 4):
        if type(max_workers) is not int or not 1 <= max_workers <= MAX_WORKERS:
            raise ValueError("max_workers must be 1..32")
        self.path = Path(directory)
        self.path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path / "batch.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs(
            id TEXT PRIMARY KEY,adventure_id TEXT NOT NULL,owner_id TEXT NOT NULL,
            stage TEXT NOT NULL,payload TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',worker TEXT,token TEXT,lease_until REAL,
            attempt INTEGER NOT NULL DEFAULT 0,request_sha256 TEXT,result_sha256 TEXT);
          CREATE INDEX IF NOT EXISTS claim_jobs ON jobs(status,stage,id);
          CREATE INDEX IF NOT EXISTS expired_jobs ON jobs(status,lease_until);
          CREATE TABLE IF NOT EXISTS dependencies(
            job_id TEXT NOT NULL REFERENCES jobs(id),depends_on TEXT NOT NULL REFERENCES jobs(id),
            PRIMARY KEY(job_id,depends_on),CHECK(job_id!=depends_on));
          CREATE INDEX IF NOT EXISTS by_dependency ON dependencies(depends_on,job_id);
          CREATE TABLE IF NOT EXISTS events(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL REFERENCES jobs(id),
            at REAL NOT NULL,kind TEXT NOT NULL,detail TEXT NOT NULL);
        """)
        with self.transaction():
            previous = self.db.execute("SELECT value FROM settings WHERE key='max_workers'").fetchone()
            if previous is not None and int(previous[0]) != max_workers:
                raise ValueError("reopen with the queue's original worker bound")
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('max_workers',?)", (str(max_workers),))
        self.max_workers = max_workers

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def _event(self, identity: str, kind: str, detail: dict, now: float):
        self.db.execute("INSERT INTO events(job_id,at,kind,detail) VALUES(?,?,?,?)",
                        (identity, now, kind, canonical(detail).decode()))

    @staticmethod
    def _time(now):
        now = time.time() if now is None else now
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
            raise ValueError("finite nonnegative time required")
        return now

    def plan(self, adventure: str | Path) -> dict:
        """Idempotently plan the complete persisted family; no creation/inference."""
        store = AdventureStore.open(adventure)
        try:
            manifest = store.manifest
            # A store has one canonical queue. A second independent scheduler
            # cannot race the same individual/stage against another local queue.
            store.db.execute("BEGIN IMMEDIATE")
            try:
                previous_queue = store.db.execute("SELECT value FROM metadata WHERE key='batch_queue_root'").fetchone()
                if previous_queue is not None and previous_queue[0] != str(self.path.resolve()):
                    raise ValueError("adventure already belongs to a different canonical batch queue")
                store.db.execute("INSERT OR IGNORE INTO metadata VALUES('batch_queue_root',?)", (str(self.path.resolve()),))
                store.db.commit()
            except BaseException:
                store.db.rollback()
                raise
            people = store.list_individuals()
            if not people:
                raise ValueError("reserve explicit founders/offspring in AdventureStore first")
            inventory = {person["id"] for person in people}
            jobs = []
            for person in people:
                if any(parent not in inventory for parent in person["parents"] or []):
                    raise ValueError("batch family requires complete parent inventory")
                for stage in STAGES:
                    identity = job_id(manifest["adventure_id"], person["id"], stage)
                    dependencies = []
                    if stage == "profile":
                        dependencies = [job_id(manifest["adventure_id"], parent, role)
                                        for parent in person["parents"] or [] for role in ("profile", "source-art")]
                    elif stage == "source-art":
                        dependencies = [job_id(manifest["adventure_id"], person["id"], "profile")]
                    else:
                        dependencies = [job_id(manifest["adventure_id"], person["id"], "source-art")]
                    payload = {"schema_version": 1, "adventure_id": manifest["adventure_id"],
                               "adventure_path": str(store.path.resolve()), "individual_id": person["id"], "stage": stage,
                               "individual_sha256": digest(person), "adventure_manifest_sha256": digest(manifest),
                               "external_generation": stage != "conversion-review"}
                    jobs.append((identity, payload, sorted(dependencies)))
            now = time.time()
            with self.transaction():
                for identity, payload, _ in jobs:
                    raw = canonical(payload).decode()
                    prior = self.db.execute("SELECT payload FROM jobs WHERE id=?", (identity,)).fetchone()
                    if prior is not None and prior[0] != raw:
                        raise ValueError("job's immutable input or local adventure location changed")
                    self.db.execute("INSERT OR IGNORE INTO jobs(id,adventure_id,owner_id,stage,payload,payload_sha256) VALUES(?,?,?,?,?,?)",
                                    (identity, manifest["adventure_id"], payload["individual_id"], payload["stage"], raw, digest(payload)))
                    if prior is None:
                        self._event(identity, "planned", {"input_sha256": digest(payload)}, now)
                for identity, _, dependencies in jobs:
                    self.db.executemany("INSERT OR IGNORE INTO dependencies VALUES(?,?)", [(identity, dep) for dep in dependencies])
            return {"adventure_id": manifest["adventure_id"], "individuals": len(people), "jobs": len(jobs),
                    "job_ids": sorted(identity for identity, _, _ in jobs)}
        finally:
            store.close()

    def _expire(self, now):
        rows = self.db.execute("SELECT id,status FROM jobs WHERE status IN ('leased','running') AND lease_until<=?", (now,)).fetchall()
        for row in rows:
            status = "unknown" if row["status"] == "running" else "pending"
            self.db.execute("UPDATE jobs SET status=?,worker=NULL,token=NULL,lease_until=NULL WHERE id=?", (status, row["id"]))
            self._event(row["id"], "lease_expired", {"status": status, "no_automatic_external_retry": status == "unknown"}, now)

    def claim(self, worker: str, *, stage: str | None = None, lease_seconds: int = 900, now=None) -> dict | None:
        identifier(worker, "worker")
        if stage is not None and stage not in STAGES:
            raise ValueError("unsupported stage")
        if type(lease_seconds) is not int or not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be 10..3600")
        now = self._time(now)
        with self.transaction():
            self._expire(now)
            active = self.db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('leased','running')").fetchone()[0]
            if active >= self.max_workers:
                return None
            row = self.db.execute("""SELECT j.* FROM jobs j WHERE j.status='pending'
                AND (? IS NULL OR j.stage=?) AND NOT EXISTS(
                  SELECT 1 FROM dependencies d JOIN jobs p ON p.id=d.depends_on
                  WHERE d.job_id=j.id AND p.status!='complete') ORDER BY j.id LIMIT 1""", (stage, stage)).fetchone()
            if row is None:
                return None
            token = secrets.token_hex(16)
            self.db.execute("UPDATE jobs SET status='leased',worker=?,token=?,lease_until=?,attempt=attempt+1 WHERE id=?",
                            (worker, token, now + lease_seconds, row["id"]))
            self._event(row["id"], "claimed", {"worker": worker, "attempt": row["attempt"] + 1}, now)
            return {"job_id": row["id"], "token": token, "lease_until": now + lease_seconds,
                    "attempt": row["attempt"] + 1, "payload": json.loads(row["payload"])}

    def _owned(self, identity, token, now, statuses=("leased", "running")):
        hash_id(identity)
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
        if row is None or row["token"] != token or row["status"] not in statuses or row["lease_until"] <= now:
            raise ValueError("claim is missing, stale, expired, or held by another worker")
        if digest(json.loads(row["payload"])) != row["payload_sha256"]:
            raise ValueError("batch input checksum mismatch")
        return row

    def heartbeat(self, identity: str, token: str, *, lease_seconds: int = 900, now=None):
        if type(lease_seconds) is not int or not 10 <= lease_seconds <= 3600:
            raise ValueError("lease_seconds must be 10..3600")
        now = self._time(now)
        with self.transaction():
            self._owned(identity, token, now)
            self.db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (now + lease_seconds, identity))

    def begin_external(self, identity: str, token: str, request_sha256: str, *, now=None) -> dict:
        """Persist before sending. Repeated calls never authorize another request."""
        hash_id(request_sha256); now = self._time(now)
        with self.transaction():
            row = self._owned(identity, token, now)
            if row["stage"] == "conversion-review":
                raise ValueError("conversion review must not invoke a generation model")
            if row["status"] == "running":
                if row["request_sha256"] != request_sha256:
                    raise ValueError("external request changed after its durable start")
                return {"should_invoke": False, "status": "outcome_unknown"}
            payload = json.loads(row["payload"])
            store = AdventureStore.open(payload["adventure_path"])
            try:
                accepted = store.accepted(row["owner_id"], row["stage"])
                if accepted is not None:
                    self._verify_result(row, accepted["sha256"])
                    self.db.execute("UPDATE jobs SET status='complete',result_sha256=?,worker=NULL,token=NULL,lease_until=NULL WHERE id=?", (accepted["sha256"], identity))
                    self._event(identity, "accepted_before_invocation", {"result_sha256": accepted["sha256"]}, now)
                    return {"should_invoke": False, "status": "accepted"}
                external = store.db.execute("SELECT status FROM invocations WHERE owner=? AND role=?", (row["owner_id"], row["stage"])).fetchone()
                if external is not None:
                    raise ValueError("existing manual/provider invocation must be reconciled in its owning workflow; batch will not replay it")
            finally:
                store.close()
            self.db.execute("UPDATE jobs SET status='running',request_sha256=? WHERE id=?", (request_sha256, identity))
            self._event(identity, "external_started", {"request_sha256": request_sha256, "attempt": row["attempt"]}, now)
            return {"should_invoke": True, "status": "outcome_unknown", "idempotency_key": identity + ":" + str(row["attempt"])}

    def complete(self, identity: str, token: str, result_sha256: str, *, now=None):
        """Record only a previously accepted immutable result; no model access."""
        hash_id(result_sha256); now = self._time(now)
        with self.transaction():
            previous = self.db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
            if previous is not None and previous["status"] == "complete" and previous["result_sha256"] == result_sha256:
                self._verify_result(previous, result_sha256)
                return
            row = self._owned(identity, token, now)
            self._verify_result(row, result_sha256)
            self.db.execute("UPDATE jobs SET status='complete',result_sha256=?,worker=NULL,token=NULL,lease_until=NULL WHERE id=?",
                            (result_sha256, identity))
            self._event(identity, "complete", {"result_sha256": result_sha256}, now)

    def _verify_result(self, row, result_sha256):
        payload = json.loads(row["payload"])
        if digest(payload) != row["payload_sha256"]:
            raise ValueError("batch payload is corrupt")
        store = AdventureStore.open(payload["adventure_path"])
        try:
            if digest(store.manifest) != payload["adventure_manifest_sha256"] or digest(store.individual(row["owner_id"])) != payload["individual_sha256"]:
                raise ValueError("job's adventure/genome input changed")
            if row["stage"] != "conversion-review":
                accepted = store.accepted(row["owner_id"], row["stage"])
                if accepted is None or accepted["sha256"] != result_sha256:
                    raise ValueError("complete requires the store's accepted immutable result")
                store.object_bytes(accepted)
            else:
                path = self.path / "reviews" / (result_sha256 + ".json")
                review = json.loads(path.read_bytes())
                if digest(review) != result_sha256 or review.get("individual_id") != row["owner_id"]:
                    raise ValueError("conversion-review identity/checksum mismatch")
                _bounded_note(review.get("review_note"))
                art = store.accepted(row["owner_id"], "source-art")
                if not art or review.get("source_sha256") != art["sha256"]:
                    raise ValueError("conversion review changed the accepted source")
                for role in ("front", "back", "icon"):
                    item = review.get("assets", {}).get(role, {})
                    raw = Path(item["path"]).read_bytes()
                    if sha256(raw).hexdigest() != item.get("sha256"):
                        raise ValueError("conversion review asset changed")
                    from genetics.roster import gba_asset
                    gba_asset(raw, width=32 if role == "icon" else 64, height=64)
        finally:
            store.close()

    def finish_review(self, identity: str, token: str, art_directory: str | Path, note: str, *, now=None):
        _bounded_note(note); now = self._time(now)
        row = self._owned(identity, token, now, ("leased",))
        if row["stage"] != "conversion-review":
            raise ValueError("only conversion-review jobs accept reviewed native assets")
        store = AdventureStore.open(json.loads(row["payload"])["adventure_path"])
        try:
            source = store.accepted(row["owner_id"], "source-art")
            if source is None: raise ValueError("accepted source art is missing")
            assets = {}
            from genetics.roster import gba_asset
            palettes = {}
            for role in ("front", "back", "icon"):
                path = (Path(art_directory) / (role + ".png")).resolve()
                raw = path.read_bytes()
                _, palettes[role] = gba_asset(raw, width=32 if role == "icon" else 64, height=64)
                assets[role] = {"path": str(path), "sha256": sha256(raw).hexdigest()}
            if palettes["front"] != palettes["back"]:
                raise ValueError("reviewed front/back must share the native palette")
            review = {"schema_version": 1, "individual_id": row["owner_id"], "source_sha256": source["sha256"],
                      "assets": assets, "review_note": note}
            checksum = digest(review)
            _publish_file(self.path / "reviews" / (checksum + ".json"), canonical(review))
            self.complete(identity, token, checksum, now=now)
            return {"review_sha256": checksum}
        finally:
            store.close()

    def reconcile(self, identity: str, *, outcome: str, note: str, result_sha256: str | None = None, now=None):
        """Explicitly resolve a stopped worker; never silently reissue a call."""
        hash_id(identity); _bounded_note(note); now = self._time(now)
        if outcome not in ("accepted", "no_result", "failed"):
            raise ValueError("outcome must be accepted, no_result, or failed")
        with self.transaction():
            self._expire(now)
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (identity,)).fetchone()
            if row is not None and row["status"] == "complete" and outcome == "accepted" and row["result_sha256"] == result_sha256:
                self._verify_result(row, result_sha256)
                return
            if row is None or row["status"] in ("leased", "running", "complete"):
                raise ValueError("stop/reconcile only unclaimed pending, unknown, or failed jobs")
            if outcome == "accepted":
                hash_id(result_sha256); self._verify_result(row, result_sha256)
                status = "complete"
            elif outcome == "no_result":
                if row["status"] not in ("unknown", "failed"):
                    raise ValueError("no_result is only for an explicitly reconciled external attempt")
                status = "pending"
            else:
                status = "failed"
            self.db.execute("UPDATE jobs SET status=?,result_sha256=?,request_sha256=NULL WHERE id=?", (status, result_sha256, identity))
            self._event(identity, "reconciled", {"outcome": outcome, "note": note, "result_sha256": result_sha256}, now)

    def page(self, *, after: str | None = None, limit: int = 100, status: str | None = None) -> dict:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("page limit must be 1..1000")
        if after is not None: hash_id(after)
        if status is not None and status not in ("pending", "leased", "running", "unknown", "failed", "complete"):
            raise ValueError("unknown batch status")
        rows = self.db.execute("SELECT id,adventure_id,owner_id,stage,status,attempt,result_sha256 FROM jobs WHERE (? IS NULL OR id>?) AND (? IS NULL OR status=?) ORDER BY id LIMIT ?",
                               (after, after, status, status, limit + 1)).fetchall()
        return {"items": [dict(row) for row in rows[:limit]], "next_cursor": rows[limit-1]["id"] if len(rows) > limit else None}

    def summary(self) -> dict:
        return {"max_workers": self.max_workers, "counts": dict(self.db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))}


def _publish_file(path: Path, raw: bytes):
    # Sharing the package's fsync+hard-link no-replace helper does not load art.
    from genetics.adventure_package import publish
    publish(path, raw)


def _public_provenance(value: dict) -> dict:
    """No local paths, raw prompts, API responses, credentials or conversations."""
    allowed = {"mode", "model", "external_tool", "provider", "provider_profile", "provider_version", "lora",
               "script_sha256", "prompt_sha256", "context_sha256", "profile_sha256"}
    public = {}
    for key in sorted(allowed & value.keys()):
        item = value[key]
        if not isinstance(item, str) or not 1 <= len(item) <= 256:
            raise ValueError("public generation provenance must be bounded scalar metadata")
        if key.endswith("sha256"): hash_id(item)
        public[key] = item
    return public


def _public_reference(reference: dict) -> dict:
    result = {key: reference[key] for key in ("reference_id", "accession", "sequence_sha256", "transform_version")}
    metadata = reference.get("conditioning_payload", {}).get("reference_metadata", {})
    keys = ("organism", "common_name", "taxonomy_id", "molecule", "coordinates", "sequence_length",
            "source_record_url", "source_fasta_url", "source_genbank_url", "retrieved_at_utc")
    result["provenance"] = {key: metadata[key] for key in keys if key in metadata}
    result["usage"] = "Public nonhuman reference metadata only; fictional model context, not phenotype prediction."
    return result


def _dataset_card(rows, adventures, shards, *, gallery=False) -> bytes:
    category = "n<1K" if rows < 1000 else "1K<n<10K" if rows < 10000 else "10K<n<100K"
    # A JSONL-only pattern makes the Hub infer JSON and show filenames without
    # thumbnails. Include the images and declare ordered ImageFolder features.
    first = ["image", "generation", "individual_id", "parents", "expression_json", "adventure_id"]
    order = first + sorted(set(DATASET_SCHEMA) - set(first) - {"file_name"})
    features = ""
    for name in order:
        kind = "image" if name == "image" else DATASET_SCHEMA[name]
        dtype = "sequence: string" if kind == "list[string]" else "dtype: " + (kind if kind in {"image", "int64"} else "string")
        features += f"  - name: {name}\n    {dtype}\n"
    configs = f'''configs:
- config_name: original_art
  default: true
  data_files:
  - split: train
    path: data/shard-*/*
  features:
{features.rstrip()}'''
    if gallery:
        configs = '''configs:
- config_name: gallery
  default: true
  data_files:
  - split: train
    path: gallery/*.parquet
- config_name: original_art
  data_files:
  - split: train
    path: original-art/*.parquet'''
    return f'''---
language:
- en
pretty_name: Aurora original fictional creature families
size_categories:
- {category}
task_categories:
- image-to-text
tags:
- synthetic
- fictional-genetics
- original-art
{configs}
---
# Aurora original fictional creature families

This version retains **{rows} accepted individuals from {adventures} adventures**
in {shards} immutable shards. These are original synthetic fantasy creatures from
an independent fan project, not official Pokémon assets. No ROMs, save files,
upstream game graphics, user profiles, dialogue logs or credentials are included.

Each image is retained generated source artwork, not a playable ROM export.
The fictional diploid virtual genome conditions model-authored expression; it
is not a biological prediction. The shared versioned zebrafish fragment is
reference context; this dataset includes only its public provenance/checksum
metadata, not a claim that the source organism predicts a creature's phenotype.
Founders and descendants retain full 256-bit IDs, ancestry, genomes, mutations,
expression and sanitized generation provenance. Fixture rows are explicitly
marked if an export opted into fixtures. This initial inventory does not claim
hundreds of reviewed or playable individuals, scientific diversity, or model
training quality. The artwork's model/provenance fields identify generation.

## Load locally

```python
from datasets import load_dataset
rows = load_dataset("json", data_files="data/shard-*/metadata.jsonl", split="train")
images = load_dataset("imagefolder", data_dir="data", split="train")
```

{_gallery_card_text() if gallery else '''`file_name` is relative to its metadata shard. The default `original_art` config
loads the images and metadata together through ImageFolder, with the decoded
image column first. Raw JSONL remains available through the explicit JSON loader
above, with every original field and filename unchanged.'''}

The explicit
`schema.json` documents the columns. Structured genetics/expression/provenance
columns are canonical JSON strings to preserve a stable schema across large
families and shards. Hashes cover retained bytes and decoded virtual genomes.

## Privacy, rights and intended use

Adventure seeds stay private; only SHA-256 seed commitments are exported.
Deterministic genome re-derivation requires the owner's private seed, but public
checksums allow byte-integrity verification. No license is asserted here on
behalf of a model provider or other rights holder; downstream users must review
art provenance and rights for their use. Intended for inspection/research on
fictional inheritance and persistent generated art. Not medical or real genetic
advice. Publication does not imply endorsement by Nintendo, Game Freak or any
model provider. Original upstream game artwork is deliberately excluded.
'''.encode()


def _gallery_card_text():
    return '''The default `gallery` view has five columns: image, display ID, generation,
parents and the existing silhouette description. Display IDs are the first 12
characters of full individual IDs, checked for collisions; they are not names
or new identities. Parent labels use the same prefixes. No creature names or
genetic claims were inferred. Images embed the exact original source bytes.

Select `original_art` for all 25 original metadata columns, including full IDs,
virtual genomes and generation provenance. It is a lossless Parquet copy of the
unchanged JSONL; `file_name` remains relative to its original metadata shard.
Both Hub configs use Parquet for compatible multi-config loading. The original
PNGs and JSONL remain available at their original paths.

```python
gallery = load_dataset("todeschini/aurora-pokemons", "gallery", split="train")
technical = load_dataset("todeschini/aurora-pokemons", "original_art", split="train")
```'''


DATASET_SCHEMA = {
    "schema_version": "int64", "individual_id": "string (256-bit hex)", "adventure_id": "string (256-bit hex)",
    "seed_commitment": "string (SHA256, seed not exported)", "creation_mode": "string",
    "genetic_schema": "string", "genome_sha256": "string", "genotype_json": "canonical JSON string",
    "primer_ancestry_json": "canonical JSON string", "parents": "list[string]", "generation": "int64",
    "mutation_policy": "string", "mutations_json": "canonical JSON string", "parental_homologs_json": "canonical JSON string",
    "expression_json": "canonical JSON string", "reference_json": "canonical JSON string", "primers_json": "canonical JSON string",
    "profile_sha256": "string", "context_sha256": "string", "parent_profile_sha256": "list[string]",
    "parent_image_sha256": "list[string]", "source_sha256": "string", "profile_provenance_json": "canonical JSON string",
    "art_provenance_json": "canonical JSON string", "file_name": "relative source image path",
}


def export_dataset(adventures: Iterable[str | Path], output: str | Path, *, shard_rows: int = 500, allow_fixtures=False, gallery=False) -> dict:
    """Export an immutable, bounded-memory HF-compatible original-art snapshot.

    A new snapshot uses a new output directory. Retrying identical inputs is
    harmless; changing accepted content/inventory never overwrites an export.
    """
    if type(shard_rows) is not int or not 1 <= shard_rows <= MAX_SHARD_ROWS:
        raise ValueError("shard_rows must be 1..1000")
    output = Path(output)
    if output.is_symlink(): raise ValueError("symlinked output directory is refused")
    output = output.resolve()
    paths = sorted({str(Path(path).resolve()) for path in adventures})
    if not paths:
        raise ValueError("select at least one explicit adventure store")
    stores = [AdventureStore.open(path) for path in paths]
    try:
        stores.sort(key=lambda store: store.manifest["adventure_id"])
        if len({store.manifest["adventure_id"] for store in stores}) != len(stores):
            raise ValueError("duplicate adventure ID selected")
        source_inventory = [{"adventure_id": store.manifest["adventure_id"],
                             "seed_commitment": sha256(bytes.fromhex(store.manifest["seed"])).hexdigest(),
                             "individual_ids": [row[0] for row in store.db.execute("SELECT individual_id FROM births WHERE status='reserved' ORDER BY individual_id")]}
                            for store in stores]
        config = {"schema_version": 1, "shard_rows": shard_rows, "allow_fixtures": allow_fixtures,
                  "adventures": source_inventory}
        _publish_file(output / "selection.json", canonical(config) + b"\n")
        files = {}; rows = []; total = 0; shard = 0
        def write(name, data):
            _publish_file(output / name, data); files[name] = {"sha256": sha256(data).hexdigest(), "bytes": len(data)}
        def flush():
            nonlocal rows, shard
            if rows:
                write(f"data/shard-{shard:05d}/metadata.jsonl", b"".join(canonical(row) + b"\n" for row in rows))
                rows = []; shard += 1
        for store in stores:
            manifest = store.manifest
            # Validate inherited genomes and every recorded mutation before
            # exporting a scientific-looking lineage, not just its ID hashes.
            validate_family(manifest, store.list_individuals())
            if manifest["creation_mode"] != "os_csprng" and not allow_fixtures:
                raise ValueError("fixture adventures require explicit allow_fixtures")
            for result in store.db.execute("SELECT individual_id FROM births WHERE status='reserved' ORDER BY individual_id"):
                person = store.individual(result[0]); identity = person["id"]
                profile = store.accepted(identity, "profile"); art = store.accepted(identity, "source-art")
                if profile is None or art is None:
                    raise ValueError(f"individual {identity} still needs accepted expression/source art")
                if not allow_fixtures and (profile["provenance"].get("mode") == "fixture" or art["provenance"].get("mode") == "fixture"):
                    raise ValueError("fixture content cannot appear as production dataset art")
                profile_value = json.loads(store.object_bytes(profile))
                context = store.generation_context(identity)
                if profile_value["context_sha256"] != digest(context) or profile_value["genome_sha256"] != person["genome_sha256"]:
                    raise ValueError("accepted profile/genome/context binding differs")
                source = store.object_bytes(art)
                if source.startswith(b"\x89PNG\r\n\x1a\n"): extension = "png"
                elif source.startswith(b"\xff\xd8\xff"): extension = "jpg"
                elif source.startswith(b"RIFF") and source[8:12] == b"WEBP": extension = "webp"
                else: raise ValueError("unsupported original image bytes")
                image_name = f"{identity}.{extension}"
                write(f"data/shard-{shard:05d}/{image_name}", source)
                row = {"schema_version": 1, "individual_id": identity, "adventure_id": manifest["adventure_id"],
                       "seed_commitment": sha256(bytes.fromhex(manifest["seed"])).hexdigest(), "creation_mode": manifest["creation_mode"],
                       "genetic_schema": manifest["genetic_schema"], "genome_sha256": person["genome_sha256"],
                       "genotype_json": canonical(person["genotype"]).decode(), "primer_ancestry_json": canonical(person["primer_ancestry"]).decode(),
                       "parents": person["parents"] or [], "generation": person["generation"], "mutation_policy": person["mutation_policy"],
                       "mutations_json": canonical(person["mutations"]).decode(), "parental_homologs_json": canonical(person["parental_homologs"]).decode(),
                       "expression_json": canonical(profile_value["expression"]).decode(), "reference_json": canonical(_public_reference(manifest["reference"])).decode(),
                       "primers_json": canonical(context["primers"]).decode(), "profile_sha256": profile["sha256"],
                       "context_sha256": profile_value["context_sha256"], "parent_profile_sha256": profile_value["parent_profile_sha256"],
                       "parent_image_sha256": profile_value["parent_image_sha256"], "source_sha256": art["sha256"],
                       "profile_provenance_json": canonical(_public_provenance(profile["provenance"])).decode(),
                       "art_provenance_json": canonical(_public_provenance(art["provenance"])).decode(), "file_name": image_name}
                if set(row) != set(DATASET_SCHEMA): raise AssertionError("dataset schema mismatch")
                rows.append(row); total += 1
                if len(rows) == shard_rows: flush()
        flush()
        if not total: raise ValueError("no accepted individuals to export")
        write("schema.json", canonical({"schema_version": 1, "columns": DATASET_SCHEMA, "structured_encoding": "canonical-json-string"}) + b"\n")
        if gallery:
            from genetics.dataset_gallery import append_gallery
            files.update(append_gallery(output, files))
        write("README.md", _dataset_card(total, len(stores), shard, gallery=gallery))
        write("selection.json", canonical(config) + b"\n")
        report = {"schema_version": 1, "rows": total, "adventures": len(stores), "shards": shard,
                  "includes": ["original_source_art", "virtual_genomes", "lineage", "expression", "sanitized_provenance", "reference_metadata"],
                  "excludes": ["raw_adventure_seed", "roms", "saves", "upstream_game_art", "api_keys", "user_profiles", "dialogue"],
                  "files": files}
        report["dataset_sha256"] = digest(report)
        _publish_file(output / "dataset-manifest.json", canonical(report) + b"\n")
        return verify_dataset(output)
    finally:
        for store in stores: store.close()


def verify_dataset(directory: str | Path) -> dict:
    directory = Path(directory)
    if directory.is_symlink(): raise ValueError("symlinked dataset directory is refused")
    directory = directory.resolve()
    report = json.loads((directory / "dataset-manifest.json").read_bytes())
    if report.get("dataset_sha256") != digest({key: value for key, value in report.items() if key != "dataset_sha256"}):
        raise ValueError("dataset manifest checksum mismatch")
    expected = set(report["files"]) | {"dataset-manifest.json"}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != expected:
        raise ValueError("unlisted or missing dataset files; upload refused")
    count = 0
    for name, record in report["files"].items():
        if not re.fullmatch(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*", name) or ".." in name:
            raise ValueError("invalid dataset path")
        path = directory / name
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != directory.parent):
            raise ValueError("symlinked dataset data is refused")
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("dataset retained bytes changed")
        if name.endswith("metadata.jsonl"):
            for line in raw.splitlines():
                row = json.loads(line)
                if set(row) != set(DATASET_SCHEMA): raise ValueError("dataset row schema changed")
                hash_id(row["individual_id"]); hash_id(row["adventure_id"]); hash_id(row["seed_commitment"])
                image = path.parent / row["file_name"]
                if image.parent != path.parent or sha256(image.read_bytes()).hexdigest() != row["source_sha256"]:
                    raise ValueError("dataset row image binding mismatch")
                count += 1
    if count != report["rows"]:
        raise ValueError("dataset row count mismatch")
    return report


def repair_dataset_viewer(source: str | Path, output: str | Path, *, gallery=False) -> dict:
    """Stage a viewer repair from an already reviewed public snapshot.

    No AdventureStore, new content, or private inputs are consulted. Every source
    file except the card and its manifest stays byte-identical; source is untouched.
    Optional compact/full Parquet views contain only derived public content.
    """
    source, output = Path(source), Path(output)
    original = verify_dataset(source)
    if output.exists() or output.is_symlink():
        raise ValueError("viewer repair requires a new output directory")
    output.mkdir(parents=True)
    report = {**original, "files": {name: dict(record) for name, record in original["files"].items()}}
    for name, record in report["files"].items():
        raw = (source / name).read_bytes()
        if sha256(raw).hexdigest() != record["sha256"] or len(raw) != record["bytes"]:
            raise ValueError("source dataset changed during viewer staging")
        if name == "README.md":
            raw = _dataset_card(report["rows"], report["adventures"], report["shards"], gallery=gallery)
            record.update(sha256=sha256(raw).hexdigest(), bytes=len(raw))
        _publish_file(output / name, raw)
    if gallery:
        from genetics.dataset_gallery import append_gallery
        report["files"].update(append_gallery(output, report["files"]))
    report["dataset_sha256"] = digest({key: value for key, value in report.items() if key != "dataset_sha256"})
    _publish_file(output / "dataset-manifest.json", canonical(report) + b"\n")
    return verify_dataset(output)
