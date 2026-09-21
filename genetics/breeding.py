"""Durable host breeding jobs. Nothing here runs on the emulator frame loop.

Inheritance is local; expression is an explicit bounded worker; image rendering
is a separately claimed external job. A claim is durable before an invocation,
so an interrupted provider call can never be silently replayed.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import tempfile
import uuid

from companion.openrouter_policy import openrouter_policy_fingerprint
from genetics.engine import VIRTUAL_REFERENCE, _individual_dict, breed
from genetics.expression import ExpressionProfile, _context, _prepare, fixture_expression, generate_expression, prepare_external_expression, accept_external_expression
from genetics.models import Genotype, Individual, MODEL_VERSION, Mutation, SpeciesConfig

MAX_IMAGE = 2 * 1024 * 1024
MAX_JSON = 256 * 1024


class BreedingError(ValueError):
    """A bounded status suitable for displaying without provider text or secrets."""


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value: object) -> str:
    return sha256(canonical(value)).hexdigest()


def _request_key(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise BreedingError("request key must be 1-64 letters, digits, underscores or hyphens")


def read_bytes(path: Path | str, limit: int) -> bytes:
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError:
        raise BreedingError("required local object is unavailable") from None
    if not 1 <= len(raw) <= limit:
        raise BreedingError("local object is empty or exceeds its size bound")
    return raw


def read_json(path: Path | str) -> dict:
    try:
        value = json.loads(read_bytes(path, MAX_JSON))
    except (ValueError, UnicodeError):
        raise BreedingError("invalid local JSON object") from None
    if not isinstance(value, dict):
        raise BreedingError("local JSON object must be a dictionary")
    return value


def _image(raw: bytes) -> None:
    if not 1 <= len(raw) <= MAX_IMAGE or not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
        raise BreedingError("artwork must be a PNG/JPEG of at most 2 MiB")


def _publish(path: Path, raw: bytes) -> None:
    """Publish complete bytes create-only; a conflicting file is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(name, path)
        except FileExistsError:
            if read_bytes(path, max(MAX_JSON, MAX_IMAGE)) != raw:
                raise BreedingError("existing immutable object differs") from None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.unlink(name)


def _individual(data: dict) -> Individual:
    value = Individual(data["id"], data["species_id"], data["generation"],
                       Genotype.from_dict(data["genotype"]), data["parents"],
                       tuple(Mutation(**m) for m in data["mutations"]))
    if _individual_dict(value) != data:
        raise BreedingError("individual descriptors do not match the immutable genome")
    return value


def _species(data: dict) -> SpeciesConfig:
    value = SpeciesConfig(species_id=data["id"], label=data["label"],
                          reference_metadata_json=json.dumps(data["reference"]),
                          reference_features_json=json.dumps(data["reference_features"]),
                          reference_payload_json=json.dumps(data["reference_context"]),
                          visual_constraints=tuple(data["visual_constraints"]),
                          mutation_rate=data["mutation_rate"], crossover_rate=data["crossover_rate"])
    if value.to_dict() != data:
        raise BreedingError("unsupported inheritance configuration")
    return value


def _bind_profile(context: dict, profile: ExpressionProfile) -> None:
    p = profile.provenance
    if (profile.individual_id != context["individual"]["id"]
            or profile.species_id != context["individual"]["species_id"]
            or p.context_sha256 != digest(context)
            or p.genome_sha256 != context["individual"]["genome_sha256"]):
        raise BreedingError("profile does not match the individual's frozen genetic context")


class BreedingStore:
    def __init__(self, directory: Path | str):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "breeding.sqlite3"
        with self._transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise BreedingError("unsupported breeding database schema")
            db.execute("CREATE TABLE IF NOT EXISTS individuals (id TEXT PRIMARY KEY, context TEXT NOT NULL, context_hash TEXT NOT NULL, profile TEXT, image_hash TEXT, artwork TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (request_key TEXT PRIMARY KEY, child_id TEXT UNIQUE NOT NULL REFERENCES individuals(id), parameters TEXT NOT NULL, state TEXT NOT NULL, attempt TEXT, art_request TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS attempts (token TEXT PRIMARY KEY, request_key TEXT NOT NULL REFERENCES jobs(request_key), stage TEXT NOT NULL, mode TEXT NOT NULL, model TEXT NOT NULL, request TEXT NOT NULL, state TEXT NOT NULL, note TEXT)")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _object(self, image_hash: str) -> Path:
        if not isinstance(image_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", image_hash):
            raise BreedingError("invalid immutable artwork hash")
        path = self.directory / "objects" / (image_hash + ".image")
        raw = read_bytes(path, MAX_IMAGE)
        if sha256(raw).hexdigest() != image_hash:
            raise BreedingError("persisted artwork checksum changed")
        _image(raw)
        return path

    def _load(self, db, individual_id: str, *, ready: bool = False) -> dict:
        row = db.execute("SELECT * FROM individuals WHERE id=?", (individual_id,)).fetchone()
        if row is None:
            raise BreedingError("individual is not registered")
        context = json.loads(row["context"])
        if digest(context) != row["context_hash"]:
            raise BreedingError("persisted genetic context changed")
        _context(context)
        _individual(context["individual"])
        profile = ExpressionProfile.model_validate_json(row["profile"]) if row["profile"] else None
        if profile:
            _bind_profile(context, profile)
        image = self._object(row["image_hash"]) if row["image_hash"] else None
        artwork = json.loads(row["artwork"]) if row["artwork"] else None
        if image and (not artwork or artwork.get("image_sha256") != row["image_hash"]):
            raise BreedingError("persisted artwork provenance changed")
        if image and artwork.get("origin") != "imported_saved_individual":
            if (profile is None or artwork.get("profile_id") != profile.profile_id
                    or artwork.get("context_sha256") != row["context_hash"]):
                raise BreedingError("persisted artwork lost its expression or genome binding")
        if ready and (profile is None or image is None):
            raise BreedingError("both parents require retained profiles and artwork")
        return {"context": context, "profile": profile, "image": image, "image_hash": row["image_hash"],
                "artwork": artwork}

    def register_parent(self, context: dict, profile: ExpressionProfile | dict, image_path: Path | str,
                        *, image_sha256: str) -> str:
        """Import a trusted saved individual; copy its pixels before publishing identity."""
        context = json.loads(canonical(context))
        _context(context)
        individual = _individual(context["individual"])
        profile = ExpressionProfile.model_validate(profile.model_dump() if isinstance(profile, ExpressionProfile) else profile)
        _bind_profile(context, profile)
        raw = read_bytes(image_path, MAX_IMAGE)
        _image(raw)
        if sha256(raw).hexdigest() != image_sha256:
            raise BreedingError("parent artwork differs from its supplied manifest hash")
        _publish(self.directory / "objects" / (image_sha256 + ".image"), raw)
        with self._transaction() as db:
            if db.execute("SELECT 1 FROM individuals WHERE id=?", (individual.id,)).fetchone():
                old = self._load(db, individual.id, ready=True)
                if old["context"] != context or old["profile"] != profile or old["image_hash"] != image_sha256:
                    raise BreedingError("registered individual identity cannot be replaced")
            else:
                db.execute("INSERT INTO individuals VALUES (?, ?, ?, ?, ?, ?)",
                           (individual.id, canonical(context).decode(), digest(context), profile.model_dump_json(),
                            image_sha256, canonical({"origin": "imported_saved_individual", "image_sha256": image_sha256}).decode()))
        return individual.id

    def enqueue(self, request_key: str, parent_ids: tuple[str, str] | list[str], *, seed: int,
                parent_revisions: tuple[str | None, str | None] | list[str | None] | None = None,
                observation_sha256: str | None = None) -> dict:
        """Commit one inherited genome offline; duplicate intent returns the same child."""
        _request_key(request_key)
        if (type(seed) is not int or not 0 <= seed < 2**64
                or not isinstance(parent_ids, (tuple, list)) or len(parent_ids) != 2
                or any(not isinstance(parent, str) or not re.fullmatch(r"[0-9a-f]{24}", parent) for parent in parent_ids)
                or parent_ids[0] == parent_ids[1]):
            raise BreedingError("two distinct parents and an unsigned 64-bit seed are required")
        parameters = {"parent_ids": list(parent_ids), "seed": seed, "model_version": MODEL_VERSION}
        if parent_revisions is not None:
            if (not isinstance(parent_revisions, (tuple, list)) or len(parent_revisions) != 2
                    or any(r is not None and (not isinstance(r, str) or not re.fullmatch(r"[0-9a-f]{64}", r)) for r in parent_revisions)):
                raise BreedingError("two explicit parent revision IDs or null values required")
            parameters["parent_revisions"] = list(parent_revisions)
        if observation_sha256 is not None:
            if not isinstance(observation_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", observation_sha256):
                raise BreedingError("source observation must be an immutable SHA-256 reference")
            observation = read_json(self.directory / "observations" / (observation_sha256 + ".json"))
            if digest(observation) != observation_sha256:
                raise BreedingError("source observation changed")
            parameters["observation_sha256"] = observation_sha256
        with self._transaction() as db:
            old = db.execute("SELECT parameters FROM jobs WHERE request_key=?", (request_key,)).fetchone()
            if old:
                if json.loads(old["parameters"]) != parameters:
                    raise BreedingError("request key already belongs to a different breeding intent")
            else:
                from genetics.edits import edited_parent
                parents = [edited_parent(self, db, p, r) for p, r in zip(parent_ids, parent_revisions or (None, None))]
                if parents[0]["context"]["species"] != parents[1]["context"]["species"]:
                    raise BreedingError("parents require the same frozen species configuration")
                first, second = [_individual(p.get("germline_context", p["context"])["individual"]) for p in parents]
                species = _species(parents[0]["context"]["species"])
                child = breed(first, second, species=species, rng=random.Random(seed),
                              generation=max(first.generation, second.generation) + 1,
                              index=0, namespace="breeding:" + request_key)
                context = {"schema_version": 1, "model_version": MODEL_VERSION, "individual": _individual_dict(child),
                           "virtual_reference_genotype": VIRTUAL_REFERENCE.to_dict(), "species": species.to_dict(),
                           "expression_policy": "Interpret inherited genome and saved parent profiles and images creatively; no fixed allele-to-appearance, score, stat or fitness mapping. Battle balance is independently authored."}
                _context(context)
                db.execute("INSERT INTO individuals VALUES (?, ?, ?, NULL, NULL, NULL)",
                           (child.id, canonical(context).decode(), digest(context)))
                db.execute("INSERT INTO jobs VALUES (?, ?, ?, 'pending_expression', NULL, NULL)",
                           (request_key, child.id, canonical(parameters).decode()))
        return self.status(request_key)

    def _job(self, db, request_key: str):
        _request_key(request_key)
        row = db.execute("SELECT * FROM jobs WHERE request_key=?", (request_key,)).fetchone()
        if row is None:
            raise BreedingError("breeding request is not registered")
        return row

    def _inputs(self, db, job):
        child = self._load(db, job["child_id"])
        from genetics.edits import edited_parent
        revisions = json.loads(job["parameters"]).get("parent_revisions", [None, None])
        parents = [edited_parent(self, db, p, r) for p, r in zip(child["context"]["individual"]["parents"], revisions)]
        profiles = [p["profile"] for p in parents]
        images = [{"individual_id": p["context"]["individual"]["id"], "asset_path": str(p["image"]),
                   "asset_sha256": p["image_hash"]} for p in parents]
        return child, profiles, images

    def _art_request(self, job, child, images):
        request = json.loads(job["art_request"])
        references = [{k: v for k, v in image.items() if k != "asset_path"} for image in images]
        if (set(request) != {"individual_id", "context_sha256", "profile_id", "prompt", "prompt_sha256", "parent_images"}
                or request["individual_id"] != job["child_id"]
                or request["context_sha256"] != digest(child["context"])
                or child["profile"] is None or request["profile_id"] != child["profile"].profile_id
                or request["parent_images"] != references
                or not isinstance(request["prompt"], str) or not 1 <= len(request["prompt"].encode()) <= MAX_JSON
                or sha256(request["prompt"].encode()).hexdigest() != request["prompt_sha256"]):
            raise BreedingError("frozen image request no longer matches the individual and parent pixels")
        return request

    def status(self, request_key: str) -> dict:
        with self._transaction() as db:
            job = self._job(db, request_key)
            child = self._load(db, job["child_id"])
            return {"request_key": request_key, "individual_id": job["child_id"], "state": job["state"],
                    "genotype": child["context"]["individual"]["genotype"],
                    "parents": child["context"]["individual"]["parents"],
                    "profile_id": child["profile"].profile_id if child["profile"] else None,
                    "image_sha256": child["image_hash"], "attempt": job["attempt"],
                    "rom_adoption": "requires_reviewed_export_and_rom_rebuild"}

    def work_expression(self, request_key: str, *, mode: str = "fixture", key: str | None = None,
                        model: str | None = None, timeout: float = 20) -> dict:
        """One invocation at most. Unknown outcomes remain claimed across restarts."""
        if not isinstance(mode, str) or mode not in {"fixture", "openrouter"}:
            raise BreedingError("worker mode must be fixture or explicit openrouter")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 30 or not math.isfinite(timeout):
            raise BreedingError("expression timeout must be 1-30 seconds")
        if mode == "openrouter" and (not isinstance(key, str) or not key.strip() or not isinstance(model, str)
                                     or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", model)):
            raise BreedingError("live expression requires an explicit model and external key")
        model = "authored-fixture-v1" if mode == "fixture" else model
        with self._transaction() as db:
            job = self._job(db, request_key)
            if job["state"] != "pending_expression":
                raise BreedingError("expression is already accepted or its invocation outcome is unknown")
            child, profiles, images = self._inputs(db, job)
            prepared = _prepare(child["context"], profiles, images, None)
            request = {"system": prepared[5], "data": json.loads(prepared[6]), "prompt_sha256": prepared[7]}
            if mode == "openrouter":
                request["provider_policy_sha256"] = openrouter_policy_fingerprint(model)
            token = uuid.uuid4().hex
            db.execute("INSERT INTO attempts VALUES (?, ?, 'expression', ?, ?, ?, 'outcome_unknown', NULL)",
                       (token, request_key, mode, model, canonical(request).decode()))
            db.execute("UPDATE jobs SET state='expression_outcome_unknown', attempt=? WHERE request_key=?", (token, request_key))
        try:
            profile = (fixture_expression(child["context"], parent_profiles=profiles, parent_images=images)
                       if mode == "fixture" else generate_expression(child["context"], key=key, model=model, timeout=timeout,
                                                                     parent_profiles=profiles, parent_images=images))
            # The response is durable before acceptance. Recovery can finish this
            # exact result after a process interruption without invoking a model.
            _publish(self.directory / "attempts" / (token + ".json"), canonical(profile.model_dump(mode="json")))
            return self.recover_expression(request_key)
        except Exception:
            raise BreedingError("expression outcome is unknown; inspect the saved attempt before recovery or an explicit retry") from None

    def start_external_expression(self, request_key: str, *, tool: str, model: str) -> dict:
        """Reserve a model invocation performed explicitly by an external tool."""
        if (not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", tool)
                or not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", model)):
            raise BreedingError("external expression requires explicit bounded tool and model identifiers")
        with self._transaction() as db:
            job = self._job(db, request_key)
            if job["state"] != "pending_expression":
                raise BreedingError("expression is already accepted or its invocation outcome is unknown")
            child, profiles, images = self._inputs(db, job)
            prepared = prepare_external_expression(child["context"], parent_profiles=profiles, parent_images=images)
            request = {key: prepared[key] for key in ("system", "data", "prompt_sha256")}
            request["external_tool"] = tool
            token = uuid.uuid4().hex
            db.execute("INSERT INTO attempts VALUES (?, ?, 'expression', 'external_model', ?, ?, 'outcome_unknown', NULL)",
                       (token, request_key, model, canonical(request).decode()))
            db.execute("UPDATE jobs SET state='expression_outcome_unknown', attempt=? WHERE request_key=?", (token, request_key))
        return {"attempt": token, "prepared": prepared, "tool": tool, "model": model,
                "instruction": "Read this exact prompt and inspect all referenced images; author one ExpressionBody, then accept it with this attempt token."}

    def accept_external_expression(self, request_key: str, *, attempt_token: str, body: dict) -> dict:
        """Durably retain an externally authored response before normal recovery."""
        with self._transaction() as db:
            job = self._job(db, request_key)
            attempt = db.execute("SELECT * FROM attempts WHERE token=? AND request_key=? AND stage='expression' AND mode='external_model'",
                                 (attempt_token, request_key)).fetchone()
            if attempt is None:
                raise BreedingError("external expression requires its reserved invocation")
            child, profiles, images = self._inputs(db, job)
            request = json.loads(attempt["request"])
            profile = accept_external_expression(body, child["context"], tool=request["external_tool"], model=attempt["model"],
                                                 prompt_sha256=request["prompt_sha256"], parent_profiles=profiles, parent_images=images)
            if child["profile"] is not None:
                if attempt["state"] != "accepted" or child["profile"] != profile:
                    raise BreedingError("accepted expression cannot be replaced")
                already_accepted = True
            else:
                if job["state"] != "expression_outcome_unknown" or job["attempt"] != attempt_token or attempt["state"] != "outcome_unknown":
                    raise BreedingError("external expression invocation is no longer active")
                already_accepted = False
        if already_accepted:
            return self.status(request_key)
        _publish(self.directory / "attempts" / (attempt_token + ".json"), canonical(profile.model_dump(mode="json")))
        return self.recover_expression(request_key)

    def recover_expression(self, request_key: str) -> dict:
        with self._transaction() as db:
            job = self._job(db, request_key)
            if job["state"] != "expression_outcome_unknown":
                raise BreedingError("no unaccepted expression attempt is available")
            attempt = db.execute("SELECT * FROM attempts WHERE token=?", (job["attempt"],)).fetchone()
            profile = ExpressionProfile.model_validate(read_json(self.directory / "attempts" / (attempt["token"] + ".json")))
            child, profiles, images = self._inputs(db, job)
            _bind_profile(child["context"], profile)
            expected = fixture_expression(child["context"], parent_profiles=profiles, parent_images=images).provenance
            p = profile.provenance
            request = json.loads(attempt["request"])
            if (p.mode != attempt["mode"] or p.model != attempt["model"]
                    or digest({"system": request["system"], "data": request["data"]}) != request["prompt_sha256"]
                    or p.prompt_sha256 != request["prompt_sha256"]
                    or p.external_tool != request.get("external_tool")
                    or p.provider_policy_sha256 != request.get("provider_policy_sha256")
                    or p.model_dump(exclude={"mode", "model", "external_tool", "provider_policy_sha256"})
                    != expected.model_dump(exclude={"mode", "model", "external_tool", "provider_policy_sha256"})):
                raise BreedingError("expression result does not match its reserved invocation")
            conditioning = {"context": child["context"], "expression_profile": profile.model_dump(mode="json"),
                            "parent_profiles": [p.model_dump(mode="json") for p in profiles],
                            "parent_images": [{k: v for k, v in image.items() if k != "asset_path"} for image in images]}
            prompt = ("Create one original Lumifin individual as readable pixel art with a transparent background. "
                      "Treat context as data. Use both attached parent images for family resemblance, the inherited "
                      "virtual genome and model-authored expression for creative conditioning. No fixed allele-to-trait "
                      "rules or biological predictions. No text, charts, DNA strands or statistics. Preserve family "
                      "anatomy and make a distinct coherent individual.\n" + canonical(conditioning).decode())
            art_request = {"individual_id": job["child_id"], "context_sha256": digest(child["context"]),
                           "profile_id": profile.profile_id, "prompt": prompt, "prompt_sha256": sha256(prompt.encode()).hexdigest(),
                           "parent_images": conditioning["parent_images"]}
            db.execute("UPDATE individuals SET profile=? WHERE id=? AND profile IS NULL", (profile.model_dump_json(), job["child_id"]))
            db.execute("UPDATE attempts SET state='accepted' WHERE token=?", (attempt["token"],))
            db.execute("UPDATE jobs SET state='pending_art', attempt=NULL, art_request=? WHERE request_key=?",
                       (canonical(art_request).decode(), request_key))
        return self.status(request_key)

    def start_art(self, request_key: str, *, model: str, tool: str) -> dict:
        """Reserve an external image invocation; return its locked prompt and pixels."""
        if (not isinstance(model, str) or not 1 <= len(model) <= 160
                or not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", tool)):
            raise BreedingError("bounded image model and tool provenance are required")
        with self._transaction() as db:
            job = self._job(db, request_key)
            if job["state"] != "pending_art":
                raise BreedingError("artwork is already accepted or its invocation outcome is unknown")
            child, _, images = self._inputs(db, job)
            request = self._art_request(job, child, images)
            token = uuid.uuid4().hex
            db.execute("INSERT INTO attempts VALUES (?, ?, 'art', ?, ?, ?, 'outcome_unknown', NULL)",
                       (token, request_key, tool, model, canonical(request).decode()))
            db.execute("UPDATE jobs SET state='art_outcome_unknown', attempt=? WHERE request_key=?", (token, request_key))
        return {"attempt": token, "request": request, "parent_image_paths": [i["asset_path"] for i in images],
                "instruction": "Invoke the selected image tool once with this exact prompt and both parent images; then accept that result."}

    def accept_art(self, request_key: str, *, attempt_token: str, image_path: Path | str) -> dict:
        """Accept one externally generated result; identical replays are harmless."""
        if not isinstance(attempt_token, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt_token):
            raise BreedingError("artwork requires a valid reserved attempt token")
        raw = read_bytes(image_path, MAX_IMAGE)
        _image(raw)
        image_hash = sha256(raw).hexdigest()
        with self._transaction() as db:
            job = self._job(db, request_key)
            child, _, images = self._inputs(db, job)
            attempt = db.execute("SELECT * FROM attempts WHERE token=? AND request_key=? AND stage='art'",
                                 (attempt_token, request_key)).fetchone()
            if attempt is None:
                raise BreedingError("artwork must belong to a reserved image invocation")
            art_request = self._art_request(job, child, images)
            if json.loads(attempt["request"]) != art_request:
                raise BreedingError("frozen image request changed")
            provenance = {"attempt": attempt_token, "model": attempt["model"], "tool": attempt["mode"],
                          "image_sha256": image_hash, "prompt_sha256": art_request["prompt_sha256"],
                          "profile_id": art_request["profile_id"], "context_sha256": art_request["context_sha256"]}
            if job["state"] == "completed":
                if child["artwork"] != provenance or child["image_hash"] != image_hash:
                    raise BreedingError("accepted individual artwork cannot be replaced")
            else:
                if job["state"] != "art_outcome_unknown" or job["attempt"] != attempt_token or attempt["state"] != "outcome_unknown":
                    raise BreedingError("image invocation is no longer the active attempt")
                # Validate the reservation before retaining any result bytes.
                # Publication is still durable before the accepting DB commit;
                # retrying after a crash safely reuses the immutable object.
                _publish(self.directory / "objects" / (image_hash + ".image"), raw)
                db.execute("UPDATE individuals SET image_hash=?, artwork=? WHERE id=? AND image_hash IS NULL",
                           (image_hash, canonical(provenance).decode(), job["child_id"]))
                db.execute("UPDATE attempts SET state='accepted' WHERE token=?", (attempt_token,))
                db.execute("UPDATE jobs SET state='completed' WHERE request_key=?", (request_key,))
        return self.status(request_key)

    def retry_unknown(self, request_key: str, *, attempt_token: str, confirm_worker_stopped: bool,
                      confirm_no_usable_result: bool, reason: str) -> dict:
        """Operator-audited retry only; elapsed time is never proof of nonexecution."""
        if (confirm_worker_stopped is not True or confirm_no_usable_result is not True
                or not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 512):
            raise BreedingError("retry requires both outcome confirmations and a bounded audit reason")
        with self._transaction() as db:
            job = self._job(db, request_key)
            if job["state"] not in {"expression_outcome_unknown", "art_outcome_unknown"} or job["attempt"] != attempt_token:
                raise BreedingError("only the current unknown invocation can be retried")
            if job["state"] == "expression_outcome_unknown" and (self.directory / "attempts" / (attempt_token + ".json")).exists():
                raise BreedingError("a saved expression response exists; recover it instead of regenerating")
            state = "pending_expression" if job["state"] == "expression_outcome_unknown" else "pending_art"
            db.execute("UPDATE attempts SET state='abandoned', note=? WHERE token=?", (reason, attempt_token))
            db.execute("UPDATE jobs SET state=?, attempt=NULL WHERE request_key=?", (state, request_key))
        return self.status(request_key)

    def inspect(self, request_key: str) -> dict:
        """Offline export of the frozen individual, inputs, output and attempt audit."""
        with self._transaction() as db:
            job = self._job(db, request_key)
            child = self._load(db, job["child_id"])
            attempts = [dict(a) for a in db.execute("SELECT * FROM attempts WHERE request_key=? ORDER BY rowid", (request_key,))]
            for attempt in attempts:
                attempt["request"] = json.loads(attempt["request"])
            return {"context": child["context"], "profile": child["profile"].model_dump(mode="json") if child["profile"] else None,
                    "image_path": str(child["image"]) if child["image"] else None, "artwork": child["artwork"],
                    "art_request": json.loads(job["art_request"]) if job["art_request"] else None, "attempts": attempts,
                    "breeding_parameters": json.loads(job["parameters"])}
