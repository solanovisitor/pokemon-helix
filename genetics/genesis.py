"""Ancient-sample reconstruction, synthetic DNA boundary and durable lab stages."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3

from genetics.primers import LOCI, PrimerDefinition, VirtualGenome, canonical, digest, hash_id, identifier

TRANSFORMATION = "helix-synthetic-contribution-v1"


def synthetic_contribution(sequence: str, *, local_salt: str, synthetic_fixture: bool) -> dict:
    """Fictional influence only. Real personal files remain deliberately disabled.

    Caller provides a test sequence, not a file. Raw input and salt are neither
    retained nor included in the result. No anonymity or biological claim.
    """
    if synthetic_fixture is not True:
        raise ValueError("real personal DNA intake is disabled pending an explicit format/retention/export agreement")
    if not isinstance(sequence, str) or not re.fullmatch(r"[ACGT]{16,8192}", sequence):
        raise ValueError("synthetic fixture requires 16..8192 uppercase ACGT bases")
    key = bytes.fromhex(hash_id(local_salt))
    block = hmac.new(key, canonical([TRANSFORMATION, sequence]), hashlib.sha256).digest()
    stream = hashlib.shake_256(block).digest(LOCI)
    payload = {"schema_version": 1, "mode": "synthetic_fixture", "transformation": TRANSFORMATION,
               "virtual_alleles": [value & 15 for value in stream]}
    return payload | {"derivative_sha256": digest(payload)}


def validate_contribution(value: dict | None) -> dict | None:
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {"schema_version", "mode", "transformation", "virtual_alleles", "derivative_sha256"}
            or value["schema_version"] != 1 or value["mode"] != "synthetic_fixture" or value["transformation"] != TRANSFORMATION
            or not isinstance(value["virtual_alleles"], list) or len(value["virtual_alleles"]) != LOCI
            or any(type(v) is not int or not 0 <= v < 16 for v in value["virtual_alleles"])
            or value["derivative_sha256"] != digest({k: v for k, v in value.items() if k != "derivative_sha256"})):
        raise ValueError("invalid synthetic contribution")
    return json.loads(canonical(value))


def genesis_request(ancient_sample: dict, donor_id: str, contribution: dict | None = None) -> dict:
    if (not isinstance(ancient_sample, dict) or set(ancient_sample) != {"sample_id", "primer_id", "primer_version", "provenance", "age_class"}
            or ancient_sample["age_class"] != "extinct-millennia" or type(ancient_sample["primer_version"]) is not int
            or ancient_sample["primer_version"] < 1 or not isinstance(ancient_sample["provenance"], str)
            or not 16 <= len(ancient_sample["provenance"]) <= 1000):
        raise ValueError("ancient sample requires explicit bounded provenance, distinct from a living parent")
    identifier(ancient_sample["sample_id"])
    identifier(ancient_sample["primer_id"])
    hash_id(donor_id)
    return {"kind": "genesis", "ancient_sample": json.loads(canonical(ancient_sample)), "donor_id": donor_id,
            "contribution": validate_contribution(contribution)}


def derive_genesis(manifest: dict, intent_id: str, request: dict, donor: dict) -> tuple:
    """One ancient baseline and one living donor; no ancient-parent fabrication."""
    from genetics.adventures import MutationPolicy, inherit_genome
    request = genesis_request(request["ancient_sample"], request["donor_id"], request["contribution"])
    if donor["id"] != request["donor_id"]:
        raise ValueError("genesis donor differs")
    sample = request["ancient_sample"]
    primers = {(p["primer_id"], p["version"]): PrimerDefinition.from_dict(p) for p in manifest["primers"]}
    ancient = primers.get((sample["primer_id"], sample["primer_version"]))
    if ancient is None:
        raise ValueError("ancient sample primer is not frozen")
    if not any((p["primer_id"], p["version"]) != (ancient.primer_id, ancient.version) for p in donor["primer_ancestry"]):
        raise ValueError("hybrid reconstruction requires a donor with a distinct lineage")
    groups = {ancient.compatibility_group} | {primers[(p["primer_id"], p["version"])].compatibility_group for p in donor["primer_ancestry"]}
    if len(groups) != 1:
        raise ValueError("genesis uses the prototype's explicit shared compatibility group")
    genotype, mutations, sources = inherit_genome(ancient.baseline, VirtualGenome.from_dict(donor["genotype"]),
        seed=manifest["seed"], intent_id=intent_id, policy=MutationPolicy(**manifest["mutation_policy"]))
    contribution = request["contribution"]
    if contribution is not None:
        changed = [list(h) for h in genotype.haplotypes]
        # Fictional, versioned local influence; never maps DNA to traits/health.
        for locus in range(0, LOCI, 8):
            before = changed[0][locus]
            changed[0][locus] = (before + 1 + contribution["virtual_alleles"][locus] % 15) % 16
            mutations.append({"haplotype": 0, "locus": locus, "before": before, "after": changed[0][locus], "reason": "synthetic_trainer_contribution"})
        genotype = VirtualGenome(tuple(tuple(h) for h in changed))
    ancestry = [json.loads(v) for v in sorted({canonical(p).decode() for p in donor["primer_ancestry"] + [{"primer_id": ancient.primer_id, "version": ancient.version}]})]
    return genotype, mutations, sources, ancestry, {k: v for k, v in request.items() if k != "kind"}


class GenesisProjectStore:
    """Stages refer to an immutable AdventureStore reservation; cancellation pauses.

    Preparation/art generation happens externally and never in the frame loop.
    Admission is a separate reviewed package + local registry transaction.
    """
    STAGES = ("registered", "analyzed", "prepared", "incubating", "ready", "admitted")

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS projects(intent_id TEXT PRIMARY KEY, binding TEXT NOT NULL, stage TEXT NOT NULL, paused INTEGER NOT NULL, receipt TEXT)")
        self.db.commit()

    def close(self):
        self.db.close()

    def reserve(self, intent_id: str, *, trainer_id: str, adventure_id: str, individual_id: str) -> dict:
        identifier(intent_id)
        binding = canonical({"trainer_id": hash_id(trainer_id), "adventure_id": hash_id(adventure_id), "individual_id": hash_id(individual_id)}).decode()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT binding FROM projects WHERE intent_id=?", (intent_id,)).fetchone()
            if old and old[0] != binding:
                raise ValueError("genesis project intent is permanently bound; resume it without reroll")
            self.db.execute("INSERT OR IGNORE INTO projects VALUES(?,?,'registered',0,NULL)", (intent_id, binding))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get(intent_id)

    def get(self, intent_id: str) -> dict:
        row = self.db.execute("SELECT * FROM projects WHERE intent_id=?", (intent_id,)).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return {"intent_id": intent_id, **json.loads(row["binding"]), "stage": row["stage"], "paused": bool(row["paused"]), "receipt": json.loads(row["receipt"]) if row["receipt"] else None}

    def pause(self, intent_id: str, paused: bool = True) -> dict:
        if type(paused) is not bool:
            raise ValueError("explicit pause boolean required")
        self.get(intent_id)
        with self.db:
            self.db.execute("UPDATE projects SET paused=? WHERE intent_id=? AND stage<>'admitted'", (paused, intent_id))
        return self.get(intent_id)

    def advance(self, intent_id: str, stage: str, *, store=None) -> dict:
        if stage not in self.STAGES or stage == "admitted":
            raise ValueError("admission requires an explicit canonical registry receipt")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.get(intent_id)
            if current["paused"]:
                raise ValueError("resume the same project before advancing")
            index = self.STAGES.index(current["stage"])
            target = self.STAGES.index(stage)
            if target != index and target != index + 1:
                raise ValueError("laboratory stages must advance in order")
            if stage == "ready":
                if store is None or store.manifest["adventure_id"] != current["adventure_id"]:
                    raise ValueError("retained adventure store required")
                individual = store.individual(current["individual_id"])
                if "genesis" not in individual or any(store.accepted(individual["id"], role) is None for role in ("profile", "source-art")):
                    raise ValueError("ready requires accepted genesis expression and actual art")
            self.db.execute("UPDATE projects SET stage=? WHERE intent_id=?", (stage, intent_id))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get(intent_id)

    def admit(self, intent_id: str, *, store, registry, package_sha256: str) -> dict:
        # Serialize against cancellation and another admission of this project.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            current = self.get(intent_id)
            if current["paused"] or current["stage"] not in ("ready", "admitted"):
                raise ValueError("only a ready, resumed project can be admitted")
            individual = store.individual(current["individual_id"])
            if store.manifest["adventure_id"] != current["adventure_id"] or "genesis" not in individual:
                raise ValueError("project individual binding differs")
            profile, art = (store.accepted(individual["id"], role) for role in ("profile", "source-art"))
            if profile is None or art is None:
                raise ValueError("admission requires retained expression and artwork")
            receipt = registry.mint(event_id="genesis:" + individual["id"], individual_id=individual["id"], owner_id=current["trainer_id"],
                birth_key=digest([current["adventure_id"], individual["intent_id"]]), genesis_sha256=digest(individual),
                package_sha256=package_sha256, profile_sha256=profile["sha256"], art_sha256=art["sha256"], kind="genesis")
            # Registry first is recoverable: after a crash the same mint returns
            # the exact receipt even if this local transaction did not commit.
            self.db.execute("UPDATE projects SET stage='admitted',receipt=? WHERE intent_id=?", (canonical(receipt).decode(), intent_id))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.get(intent_id)
