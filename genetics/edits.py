"""Immutable virtual one-locus revisions, separate from each individual's identity.

Edits describe fictional alleles only. Nothing predicts real biological effects.
Changed appearance requires a newly accepted expression and image invocation.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import uuid

from genetics.breeding import (BreedingError, BreedingStore, MAX_IMAGE, _bind_profile, _individual,
                               _publish, canonical, digest, read_bytes)
from genetics.engine import _individual_dict
from genetics.expression import ExpressionProfile, fixture_expression
from genetics.models import Genotype, Individual
from genetics.roster import decode_png


def _revision(store, db, revision_id: str) -> dict:
    if not isinstance(revision_id, str) or not re.fullmatch(r"[0-9a-f]{64}", revision_id):
        raise BreedingError("invalid virtual edit revision identifier")
    row = db.execute("SELECT * FROM virtual_edits WHERE revision_id=?", (revision_id,)).fetchone()
    if row is None:
        raise BreedingError("virtual edit revision is not registered")
    result = dict(row)
    result["preview"] = json.loads(result["preview"])
    if digest(result["preview"]) != revision_id:
        raise BreedingError("virtual edit preview changed")
    for key in ("context", "germline_context"):
        _individual(result["preview"][key]["individual"])
    result["profile"] = ExpressionProfile.model_validate_json(row["profile"]) if row["profile"] else None
    if result["profile"]:
        _bind_profile(result["preview"]["context"], result["profile"])
    result["art_request"] = json.loads(row["art_request"]) if row["art_request"] else None
    result["artwork"] = json.loads(row["artwork"]) if row["artwork"] else None
    result["image"] = store._object(row["image_hash"]) if row["image_hash"] else None
    if result["art_request"]:
        request = result["art_request"]
        if (not result["profile"] or request.get("revision_id") != revision_id
                or request.get("profile_id") != result["profile"].profile_id
                or request.get("base_image_sha256") != result["preview"]["base_image_sha256"]
                or request.get("prompt_sha256") != sha256(request.get("prompt", "").encode()).hexdigest()):
            raise BreedingError("virtual edit artwork reservation changed")
    if result["image"]:
        artwork, request = result["artwork"], result["art_request"]
        if (not result["profile"] or not artwork or not request
                or artwork["revision_id"] != revision_id or artwork["image_sha256"] != row["image_hash"]
                or artwork["profile_id"] != result["profile"].profile_id
                or artwork["prompt_sha256"] != sha256(request["prompt"].encode()).hexdigest()):
            raise BreedingError("accepted edit lost its profile or artwork binding")
    return result


def edited_parent(store, db, individual_id: str, revision_id: str | None) -> dict:
    if revision_id is None:
        return store._load(db, individual_id, ready=True)
    try:
        revision = _revision(store, db, revision_id)
    except sqlite3.OperationalError:
        raise BreedingError("no virtual edit revisions are registered") from None
    preview = revision["preview"]
    if preview["individual_id"] != individual_id or not revision["profile"] or not revision["image"]:
        raise BreedingError("parent revision must belong to this individual and have accepted profile/art")
    return {"context": preview["context"], "germline_context": preview["germline_context"],
            "profile": revision["profile"], "image": revision["image"], "image_hash": revision["image_hash"],
            "artwork": revision["artwork"]}


class EditStore:
    def __init__(self, store: BreedingStore):
        self.store = store
        with store._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS virtual_edits (revision_id TEXT PRIMARY KEY, preview TEXT NOT NULL, profile TEXT, attempt TEXT, art_request TEXT, artwork TEXT, image_hash TEXT)")

    def preview(self, individual_id: str, *, scope: str, copy: int, locus: int, allele: int,
                base_revision: str | None = None) -> dict:
        if scope not in {"somatic", "germline"} or any(type(v) is not int for v in (copy, locus, allele)) or copy not in (0, 1) or not 0 <= locus < 32 or not 0 <= allele < 4:
            raise BreedingError("one virtual allele substitution requires scope, copy 0..1, locus 0..31 and allele 0..3")
        with self.store._transaction() as db:
            base = edited_parent(self.store, db, individual_id, base_revision)
            original = _individual(base["context"]["individual"])
            before = original.genotype.haplotypes[copy][locus]
            if before == allele:
                raise BreedingError("virtual edit must change exactly one allele")
            haplotypes = [list(h) for h in original.genotype.haplotypes]
            haplotypes[copy][locus] = allele
            edited = Individual(original.id, original.species_id, original.generation, Genotype(haplotypes),
                                original.parents, tuple(m for m in original.mutations if (m.haplotype, m.locus) != (copy, locus)))
            context = deepcopy(base["context"])
            context["individual"] = _individual_dict(edited)
            germline = deepcopy(base.get("germline_context", base["context"]))
            if scope == "germline":
                # Apply only this explicit locus to the germline. Earlier somatic
                # substitutions remain individual-only even in a later revision.
                germ = _individual(germline["individual"])
                germ_haps = [list(h) for h in germ.genotype.haplotypes]
                germ_haps[copy][locus] = allele
                germline["individual"] = _individual_dict(Individual(germ.id, germ.species_id, germ.generation,
                    Genotype(germ_haps), germ.parents, tuple(m for m in germ.mutations if (m.haplotype, m.locus) != (copy, locus))))
            preview = {"schema_version": 1, "individual_id": individual_id, "base_revision": base_revision,
                       "base_context_sha256": digest(base["context"]), "base_profile_id": base["profile"].profile_id,
                       "base_image_sha256": base["image_hash"], "scope": scope,
                       "substitution": {"copy": copy, "locus": locus, "before": before, "after": allele},
                       "context": context, "germline_context": germline,
                       "meaning": "Virtual one-locus experiment; expression and art require fresh acceptance; base identity unchanged."}
            revision_id = digest(preview)
            db.execute("INSERT OR IGNORE INTO virtual_edits VALUES (?, ?, NULL, NULL, NULL, NULL, NULL)",
                       (revision_id, canonical(preview).decode()))
        return {"revision_id": revision_id, **preview}

    def _inputs(self, db, row):
        preview = row["preview"]
        base = edited_parent(self.store, db, preview["individual_id"], preview["base_revision"])
        if (digest(base["context"]) != preview["base_context_sha256"] or base["profile"].profile_id != preview["base_profile_id"]
                or base["image_hash"] != preview["base_image_sha256"]):
            raise BreedingError("virtual edit base provenance changed")
        parents = [self.store._load(db, p, ready=True) for p in preview["context"]["individual"]["parents"] or []]
        return {"context": preview["context"],
                "parent_profiles": [p["profile"].model_dump(mode="json") for p in parents],
                "parent_images": [{"individual_id": p["context"]["individual"]["id"], "asset_path": str(p["image"]),
                                   "asset_sha256": p["image_hash"]} for p in parents],
                "individual_image": {"individual_id": preview["individual_id"], "asset_path": str(base["image"]),
                                     "asset_sha256": base["image_hash"]}}

    def inputs(self, revision_id: str) -> dict:
        with self.store._transaction() as db:
            return self._inputs(db, _revision(self.store, db, revision_id))

    def accept_profile(self, revision_id: str, profile: ExpressionProfile | dict) -> dict:
        profile = ExpressionProfile.model_validate(profile.model_dump() if isinstance(profile, ExpressionProfile) else profile)
        with self.store._transaction() as db:
            row = _revision(self.store, db, revision_id)
            inputs = self._inputs(db, row)
            expected = fixture_expression(inputs["context"], parent_profiles=inputs["parent_profiles"],
                                          parent_images=inputs["parent_images"], individual_image=inputs["individual_image"])
            _bind_profile(inputs["context"], profile)
            if profile.provenance.model_dump(exclude={"mode", "model", "external_tool"}) != expected.provenance.model_dump(exclude={"mode", "model", "external_tool"}):
                raise BreedingError("edit expression must reaccept the exact new context and original image references")
            if row["profile"] and row["profile"] != profile:
                raise BreedingError("accepted edit expression cannot be replaced")
            db.execute("UPDATE virtual_edits SET profile=? WHERE revision_id=? AND profile IS NULL", (profile.model_dump_json(), revision_id))
        return self.inspect(revision_id)

    def start_art(self, revision_id: str, *, tool: str, model: str) -> dict:
        if not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", tool) or not isinstance(model, str) or not 1 <= len(model) <= 160:
            raise BreedingError("bounded image model and tool provenance required")
        with self.store._transaction() as db:
            row = _revision(self.store, db, revision_id)
            if row["profile"] is None or row["attempt"] is not None:
                raise BreedingError("edit needs an accepted expression and an unclaimed artwork invocation")
            inputs = self._inputs(db, row)
            data = {"revision_id": revision_id, "preview": row["preview"], "expression": row["profile"].model_dump(mode="json")}
            prompt = ("Create revised artwork of this same original Lumifin individual, retaining recognizable identity. "
                      "Use attached current artwork and newly accepted expression as creative context for the specified virtual edit. "
                      "No biological predictions or fixed allele-to-appearance rules. Transparent background, readable pixel art, no text.\n" + canonical(data).decode())
            request = {"prompt": prompt, "prompt_sha256": sha256(prompt.encode()).hexdigest(), "tool": tool,
                       "model": model, "base_image_sha256": inputs["individual_image"]["asset_sha256"],
                       "profile_id": row["profile"].profile_id, "revision_id": revision_id}
            token = uuid.uuid4().hex
            db.execute("UPDATE virtual_edits SET attempt=?, art_request=? WHERE revision_id=?",
                       (token, canonical(request).decode(), revision_id))
        return {"attempt": token, "request": request, "image_path": inputs["individual_image"]["asset_path"]}

    def accept_art(self, revision_id: str, *, attempt_token: str, image_path: Path | str) -> dict:
        raw = read_bytes(image_path, MAX_IMAGE)
        decode_png(raw)
        image_hash = sha256(raw).hexdigest()
        with self.store._transaction() as db:
            row = _revision(self.store, db, revision_id)
            if not row["attempt"] or row["attempt"] != attempt_token:
                raise BreedingError("edit art must match its reserved invocation")
            if image_hash == row["preview"]["base_image_sha256"]:
                raise BreedingError("edit appearance requires newly accepted artwork; cannot reuse original pixels")
            request = row["art_request"]
            provenance = {"revision_id": revision_id, "attempt": attempt_token, "image_sha256": image_hash,
                          "profile_id": row["profile"].profile_id, "prompt_sha256": request["prompt_sha256"],
                          "tool": request["tool"], "model": request["model"]}
            if row["image"] and row["artwork"] != provenance:
                raise BreedingError("accepted edit artwork cannot be replaced")
            _publish(self.store.directory / "objects" / (image_hash + ".image"), raw)
            db.execute("UPDATE virtual_edits SET artwork=?, image_hash=? WHERE revision_id=? AND image_hash IS NULL",
                       (canonical(provenance).decode(), image_hash, revision_id))
        return self.inspect(revision_id)

    def inspect(self, revision_id: str) -> dict:
        with self.store._transaction() as db:
            row = _revision(self.store, db, revision_id)
            state = "completed" if row["image"] else "art_outcome_unknown" if row["attempt"] else "pending_art" if row["profile"] else "pending_profile"
            return {"revision_id": revision_id, "state": state, "preview": row["preview"],
                    "profile": row["profile"].model_dump(mode="json") if row["profile"] else None,
                    "art_request": row["art_request"], "artwork": row["artwork"], "attempt": row["attempt"],
                    "image_path": str(row["image"]) if row["image"] else None}

    def completed(self, revision_id: str) -> dict:
        result = self.inspect(revision_id)
        if result["state"] != "completed":
            raise BreedingError("virtual edit requires accepted expression and artwork")
        return {"context": result["preview"]["context"], "profile": result["profile"], "image_path": result["image_path"],
                "artwork": result["artwork"], "virtual_edit": result["preview"], "revision_id": revision_id}
