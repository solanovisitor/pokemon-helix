"""Durable adventure identities and birth intents; no networking or ROM mutation.

Each intent owns independent full-entropy streams. Reservation sequence numbers
are audit data, never randomness inputs. An accepted output is retained as bytes,
not reconstructed by a model on reopen. Legacy genetics remain format v1.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
from typing import Any

from genetics.primers import (ALLELES, GENETIC_SCHEMA, LINKAGE_GROUP_SIZE, LOCI, PrimerDefinition,
                             ReferenceBinding, VirtualGenome, canonical, digest, hash_id, identifier)

GENERATOR_VERSION = "aurora-adventures-v1"
MANIFEST_VERSION = 1
MAX_ASSET_BYTES = 32 * 1024 * 1024
MAX_IN_FLIGHT_GENERATIONS = 4


def derive_stream(seed: str, domain: str, *parts: Any) -> bytes:
    """HMAC-SHA256 keeps all 256 seed bits; length-delimited JSON domains."""
    hash_id(seed)
    identifier(domain)
    return hmac.new(bytes.fromhex(seed), canonical([GENERATOR_VERSION, domain, parts]), hashlib.sha256).digest()


class _Stream:
    def __init__(self, key: bytes):
        self.key, self.counter, self.buffer = key, 0, b""

    def read(self, size: int) -> bytes:
        while len(self.buffer) < size:
            self.buffer += hmac.new(self.key, self.counter.to_bytes(16, "big"), hashlib.sha256).digest()
            self.counter += 1
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def below(self, bound: int) -> int:
        size = max(1, (bound.bit_length() + 7) // 8)
        limit = 256 ** size - 256 ** size % bound
        while True:
            value = int.from_bytes(self.read(size), "big")
            if value < limit:
                return value % bound

    def chance(self, probability: float) -> bool:
        return int.from_bytes(self.read(8), "big") < int(probability * (1 << 64))


@dataclass(frozen=True)
class MutationPolicy:
    version: str = "aurora-diversity-mutation-v1"
    founder_variation_rate: float = 0.5
    mutation_rate: float = 0.002
    crossover_rate: float = 0.12
    minimum_changes: int = 16

    def __post_init__(self) -> None:
        if self.version != "aurora-diversity-mutation-v1":
            raise ValueError("unsupported mutation policy")
        for value in (self.founder_variation_rate, self.mutation_rate, self.crossover_rate):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError("mutation probabilities must be finite values in [0,1]")
        if type(self.minimum_changes) is not int or not 0 <= self.minimum_changes <= 2 * LOCI:
            raise ValueError("minimum virtual allele changes must be 0..192")


class DiversityExhausted(ValueError):
    """A committed birth candidate collided. It remains pending for explicit review."""


def _mutate(genome: VirtualGenome, rng: _Stream, probability: float,
            minimum_changes: int, natural_reason: str) -> tuple[VirtualGenome, list[dict]]:
    flat = list(genome.haplotypes[0] + genome.haplotypes[1])
    changes = {}
    for index in range(2 * LOCI):
        if rng.chance(probability):
            changes[index] = natural_reason
    # A finite, intent-derived permutation supplies diversity even for fully
    # homozygous/related parents. No retry draws depend on the known population.
    available = [index for index in range(2 * LOCI) if index not in changes]
    while len(changes) < minimum_changes:
        position = rng.below(len(available))
        changes[available.pop(position)] = "diversity_floor"
    records = []
    for index, reason in sorted(changes.items()):
        before = flat[index]
        flat[index] = (before + 1 + rng.below(ALLELES - 1)) % ALLELES
        records.append({"haplotype": index // LOCI, "locus": index % LOCI,
                        "before": before, "after": flat[index], "reason": reason})
    return VirtualGenome((tuple(flat[:LOCI]), tuple(flat[LOCI:]))), records


def inherit_genome(first: VirtualGenome, second: VirtualGenome, *, seed: str, intent_id: str,
                   policy: MutationPolicy = MutationPolicy()) -> tuple[VirtualGenome, list[dict], list[list[int]]]:
    """Linked parental homolog selection, followed by fully recorded mutation."""
    rng = _Stream(derive_stream(seed, "meiosis", intent_id))
    gametes, sources = [], []
    for parent in (first, second):
        alleles, origins = [], []
        for start in range(0, LOCI, LINKAGE_GROUP_SIZE):
            homolog = rng.below(2)
            for locus in range(start, start + LINKAGE_GROUP_SIZE):
                if locus > start and rng.chance(policy.crossover_rate):
                    homolog = 1 - homolog
                alleles.append(parent.haplotypes[homolog][locus])
                origins.append(homolog)
        gametes.append(tuple(alleles))
        sources.append(origins)
    result, mutations = _mutate(VirtualGenome(tuple(gametes)), _Stream(derive_stream(seed, "mutation", intent_id)),
                                policy.mutation_rate, policy.minimum_changes, "germline_mutation")
    return result, mutations, sources


def validate_family(manifest: dict, individuals: list[dict]) -> dict[str, dict]:
    """Re-derive the complete frozen family without SQLite or external assets.

    Validation includes actual genotype, linkage origins, every mutation, primer
    ancestry and generation, not merely rehashed attacker-supplied genomes.
    """
    seed = hash_id(manifest["seed"])
    if (manifest.get("schema_version") != MANIFEST_VERSION or manifest.get("generator_version") != GENERATOR_VERSION
            or manifest.get("genetic_schema") != GENETIC_SCHEMA
            or manifest.get("adventure_id") != derive_stream(seed, "adventure-identity").hex()):
        raise ValueError("unsupported or inconsistent family manifest")
    reference = ReferenceBinding.from_dict(manifest["reference"])
    policy = MutationPolicy(**manifest["mutation_policy"])
    primers = {(p["primer_id"], p["version"]): PrimerDefinition.from_dict(p) for p in manifest["primers"]}
    if len(primers) != len(manifest["primers"]) or any(p.reference_id != reference.reference_id for p in primers.values()):
        raise ValueError("invalid frozen family primers")
    pending = {value["id"]: value for value in individuals}
    if not individuals or len(pending) != len(individuals):
        raise ValueError("nonempty unique family identities required")
    verified, intents, genomes = {}, set(), set()
    while pending:
        advanced = False
        for key, value in list(pending.items()):
            intent_id = value.get("intent_id")
            if not isinstance(intent_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}", intent_id):
                raise ValueError("invalid family birth intent")
            parents = value.get("parents")
            genesis = value.get("genesis")
            if genesis is not None:
                from genetics.genesis import derive_genesis, genesis_request
                request = genesis_request(**genesis)
                if request["donor_id"] not in verified:
                    continue
                genotype, mutations, sources, ancestry, genesis = derive_genesis(manifest, intent_id, request, verified[request["donor_id"]])
                generation = 0
                if parents is not None:
                    raise ValueError("ancient reconstruction cannot fabricate living parents")
            elif parents is None:
                ancestry = value.get("primer_ancestry")
                if not isinstance(ancestry, list) or len(ancestry) != 1:
                    raise ValueError("founder requires exactly one frozen primer")
                primer = primers.get((ancestry[0].get("primer_id"), ancestry[0].get("version")))
                if primer is None:
                    raise ValueError("founder primer is not frozen")
                request = {"kind": "founder", "primer_id": primer.primer_id, "primer_version": primer.version}
                genotype, mutations = _mutate(primer.baseline, _Stream(derive_stream(seed, "founder-variation", intent_id)),
                                              policy.founder_variation_rate, policy.minimum_changes, "founder_variation")
                generation, sources = 0, None
                ancestry = [{"primer_id": primer.primer_id, "version": primer.version}]
            else:
                if not isinstance(parents, list) or len(parents) != 2 or parents[0] == parents[1]:
                    raise ValueError("two distinct lineage parents required")
                if any(parent not in verified for parent in parents):
                    continue
                first, second = (verified[parent] for parent in parents)
                groups = {primers[(p["primer_id"], p["version"])].compatibility_group for p in first["primer_ancestry"] + second["primer_ancestry"]}
                if len(groups) != 1:
                    raise ValueError("incompatible family lineage")
                request = {"kind": "offspring", "parents": parents}
                genotype, mutations, sources = inherit_genome(VirtualGenome.from_dict(first["genotype"]), VirtualGenome.from_dict(second["genotype"]),
                                                               seed=seed, intent_id=intent_id, policy=policy)
                generation = 1 + max(first["generation"], second["generation"])
                ancestry = [json.loads(v) for v in sorted({canonical(p).decode() for p in first["primer_ancestry"] + second["primer_ancestry"]})]
            expected = {"schema_version": 1, "id": derive_stream(seed, "individual-identity", intent_id, request).hex(),
                        "adventure_id": manifest["adventure_id"], "intent_id": intent_id, "generation": generation,
                        "primer_ancestry": ancestry, "genotype": genotype.to_dict(), "genome_sha256": genotype.sha256,
                        "parents": parents, "mutations": mutations, "parental_homologs": sources,
                        "mutation_policy": policy.version, "reference_id": reference.reference_id}
            if genesis is not None:
                expected["genesis"] = genesis
            if value != expected or intent_id in intents or genotype.sha256 in genomes:
                raise ValueError("family differs from its frozen deterministic inheritance or duplicates an accepted genome")
            intents.add(intent_id)
            genomes.add(genotype.sha256)
            verified[key] = json.loads(canonical(expected))
            del pending[key]
            advanced = True
        if not advanced:
            raise ValueError("family lineage has missing parents or a cycle")
    return verified


def _write_once(path: Path, data: bytes) -> None:
    """Publish complete durable bytes without exposing partial final files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".publish-", delete=False) as output:
            temporary = output.name
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise ValueError("immutable retained content differs")
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            os.unlink(temporary)


class AdventureStore:
    def __init__(self, path: Path, manifest: dict):
        self.path = path
        self._manifest = manifest
        self.db = sqlite3.connect(path / "adventure.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS births(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT NOT NULL UNIQUE,
                request_json TEXT NOT NULL, individual_id TEXT NOT NULL UNIQUE,
                genome_sha256 TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS unique_accepted_genome ON births(genome_sha256) WHERE status='reserved';
            CREATE TABLE IF NOT EXISTS accepted(
                owner TEXT NOT NULL, role TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(owner,role));
            CREATE TABLE IF NOT EXISTS invocations(
                owner TEXT NOT NULL, role TEXT NOT NULL, request_json TEXT NOT NULL,
                status TEXT NOT NULL, PRIMARY KEY(owner,role));
        """)
        manifest_hash = digest(manifest)
        with self.db:
            row = self.db.execute("SELECT value FROM metadata WHERE key='manifest_sha256'").fetchone()
            if row and row[0] != manifest_hash:
                raise ValueError("adventure manifest does not match its durable store")
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES('manifest_sha256',?)", (manifest_hash,))

    @classmethod
    def create(cls, path: str | Path, *, primers: list[PrimerDefinition], reference: ReferenceBinding,
               fixture_seed: str | None = None, policy: MutationPolicy = MutationPolicy()) -> AdventureStore:
        path = Path(path)
        if (path / "manifest.json").exists():
            raise ValueError("adventure already exists; reopen it explicitly")
        if path.exists() and any(path.iterdir()):
            raise ValueError("create requires an empty adventure directory")
        if not 1 <= len(primers) <= 64 or any(p.reference_id != reference.reference_id for p in primers):
            raise ValueError("one to 64 primers must bind the shared reference")
        primer_keys = {(p.primer_id, p.version) for p in primers}
        if len(primer_keys) != len(primers) or len({p.baseline.sha256 for p in primers}) != len(primers):
            raise ValueError("adventure primer versions and baseline genomes must be distinct")
        seed = hash_id(fixture_seed) if fixture_seed is not None else secrets.token_hex(32)
        manifest = {"schema_version": MANIFEST_VERSION, "generator_version": GENERATOR_VERSION,
                    "genetic_schema": GENETIC_SCHEMA, "adventure_id": derive_stream(seed, "adventure-identity").hex(),
                    "seed": seed, "creation_mode": "deterministic_fixture" if fixture_seed is not None else "os_csprng",
                    "reference": reference.to_dict(), "primers": [p.to_dict() for p in sorted(primers, key=lambda p: (p.primer_id, p.version))],
                    "mutation_policy": asdict(policy), "linkage_group_size": LINKAGE_GROUP_SIZE,
                    "capacity": {"prepared_native_individuals": 2, "catalog_is_not_resident": True},
                    "legacy_namespace": "aurora-legacy-v1-preserved"}
        _write_once(path / "manifest.json", canonical(manifest) + b"\n")
        return cls(path, manifest)

    @classmethod
    def open(cls, path: str | Path) -> AdventureStore:
        path = Path(path)
        manifest = json.loads((path / "manifest.json").read_bytes())
        if (manifest.get("schema_version") != MANIFEST_VERSION or manifest.get("generator_version") != GENERATOR_VERSION
                or manifest.get("genetic_schema") != GENETIC_SCHEMA
                or manifest.get("adventure_id") != derive_stream(manifest["seed"], "adventure-identity").hex()):
            raise ValueError("unsupported or corrupt adventure manifest")
        ReferenceBinding.from_dict(manifest["reference"])
        for primer in manifest["primers"]:
            PrimerDefinition.from_dict(primer)
        MutationPolicy(**manifest["mutation_policy"])
        if not (path / "adventure.sqlite3").is_file():
            raise ValueError("adventure durable store is missing")
        return cls(path, manifest)

    @property
    def manifest(self) -> dict:
        return json.loads(canonical(self._manifest))

    def close(self) -> None:
        self.db.close()

    def _primer(self, primer_id: str, version: int) -> PrimerDefinition:
        matches = [p for p in self._manifest["primers"] if p["primer_id"] == primer_id and p["version"] == version]
        if len(matches) != 1:
            raise ValueError("primer is not frozen in this adventure")
        return PrimerDefinition.from_dict(matches[0])

    def _decode(self, row: sqlite3.Row) -> dict:
        value = json.loads(row["payload"])
        if digest(value) != row["payload_sha256"] or VirtualGenome.from_dict(value["genotype"]).sha256 != row["genome_sha256"]:
            raise ValueError("corrupt reserved individual")
        if row["status"] != "reserved":
            raise DiversityExhausted("birth candidate duplicates a known genome; intent remains diversity_exhausted")
        return value

    def individual(self, individual_id: str) -> dict:
        hash_id(individual_id)
        row = self.db.execute("SELECT * FROM births WHERE individual_id=?", (individual_id,)).fetchone()
        if row is None:
            raise KeyError(individual_id)
        return self._decode(row)

    def list_individuals(self) -> list[dict]:
        return [self._decode(row) for row in self.db.execute("SELECT * FROM births WHERE status='reserved' ORDER BY sequence")]

    def birth_status(self, intent_id: str) -> dict:
        row = self.db.execute("SELECT sequence,individual_id,status FROM births WHERE intent_id=?", (intent_id,)).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return dict(row)

    def reserve_founder(self, intent_id: str, primer_id: str, primer_version: int = 1) -> dict:
        return self._reserve(intent_id, {"kind": "founder", "primer_id": primer_id, "primer_version": primer_version})

    def reserve_offspring(self, intent_id: str, parent_a_id: str, parent_b_id: str) -> dict:
        hash_id(parent_a_id)
        hash_id(parent_b_id)
        if parent_a_id == parent_b_id:
            raise ValueError("two distinct parent identities required")
        return self._reserve(intent_id, {"kind": "offspring", "parents": [parent_a_id, parent_b_id]})

    def reserve_genesis(self, intent_id: str, *, ancient_sample: dict, donor_id: str, contribution: dict | None = None) -> dict:
        from genetics.genesis import genesis_request
        return self._reserve(intent_id, genesis_request(ancient_sample, donor_id, contribution))

    def _reserve(self, intent_id: str, request: dict) -> dict:
        if not isinstance(intent_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}", intent_id):
            raise ValueError("bounded stable birth intent required")
        request_json = canonical(request).decode()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            existing = self.db.execute("SELECT * FROM births WHERE intent_id=?", (intent_id,)).fetchone()
            if existing:
                if existing["request_json"] != request_json:
                    raise ValueError("birth intent is already bound to different parents or primer")
                self.db.commit()
                return self._decode(existing)
            seed = self._manifest["seed"]
            policy = MutationPolicy(**self._manifest["mutation_policy"])
            genesis = None
            if request["kind"] == "genesis":
                from genetics.genesis import derive_genesis
                genotype, mutations, sources, ancestry, genesis = derive_genesis(self._manifest, intent_id, request, self.individual(request["donor_id"]))
                parents, generation = None, 0
            elif request["kind"] == "founder":
                primer = self._primer(request["primer_id"], request["primer_version"])
                genotype, mutations = _mutate(primer.baseline, _Stream(derive_stream(seed, "founder-variation", intent_id)),
                                              policy.founder_variation_rate, policy.minimum_changes, "founder_variation")
                parents, generation, sources = None, 0, None
                ancestry = [{"primer_id": primer.primer_id, "version": primer.version}]
            else:
                parents = request["parents"]
                first, second = (self.individual(parent_id) for parent_id in parents)
                groups = {self._primer(p["primer_id"], p["version"]).compatibility_group for p in first["primer_ancestry"] + second["primer_ancestry"]}
                if len(groups) != 1:
                    raise ValueError("cross-primer breeding requires an explicitly shared compatibility group")
                genotype, mutations, sources = inherit_genome(VirtualGenome.from_dict(first["genotype"]), VirtualGenome.from_dict(second["genotype"]),
                                                               seed=seed, intent_id=intent_id, policy=policy)
                ancestry = [json.loads(v) for v in sorted({canonical(p).decode() for p in first["primer_ancestry"] + second["primer_ancestry"]})]
                generation = max(first["generation"], second["generation"]) + 1
            individual_id = derive_stream(seed, "individual-identity", intent_id, request).hex()
            value = {"schema_version": 1, "id": individual_id, "adventure_id": self._manifest["adventure_id"],
                     "intent_id": intent_id, "generation": generation, "primer_ancestry": ancestry,
                     "genotype": genotype.to_dict(), "genome_sha256": genotype.sha256, "parents": parents,
                     "mutations": mutations, "parental_homologs": sources,
                     "mutation_policy": policy.version, "reference_id": self._manifest["reference"]["reference_id"]}
            if genesis is not None:
                value["genesis"] = genesis
            # Zero automatic population-conditioned redraws: the candidate never
            # changes under scheduling or restart. A collision is a durable error.
            duplicate = self.db.execute("SELECT 1 FROM births WHERE genome_sha256=? AND status='reserved'", (genotype.sha256,)).fetchone()
            status = "diversity_exhausted" if duplicate else "reserved"
            self.db.execute("INSERT INTO births(intent_id,request_json,individual_id,genome_sha256,status,payload,payload_sha256) VALUES(?,?,?,?,?,?,?)",
                            (intent_id, request_json, individual_id, genotype.sha256, status, canonical(value).decode(), digest(value)))
            self.db.commit()
            if duplicate:
                raise DiversityExhausted("birth candidate duplicates a known genome; intent remains diversity_exhausted")
            return value
        except Exception:
            self.db.rollback()
            raise

    def _accepted(self, owner: str, role: str) -> dict | None:
        row = self.db.execute("SELECT payload FROM accepted WHERE owner=? AND role=?", (owner, role)).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        if (not isinstance(value, dict) or set(value) != {"sha256", "size", "role", "provenance"}
                or value["role"] != role or type(value["size"]) is not int
                or not 0 < value["size"] <= MAX_ASSET_BYTES or not isinstance(value["provenance"], dict)):
            raise ValueError("corrupt accepted content record")
        hash_id(value["sha256"])
        path = self.path / "objects" / value["sha256"]
        if path.is_symlink() or not path.is_file() or path.stat().st_size != value["size"]:
            raise ValueError("retained accepted object is missing or corrupt")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != value["sha256"]:
            raise ValueError("retained accepted object is missing or corrupt")
        if role == "profile":
            profile = json.loads(raw)
            individual = self.individual(owner)
            if (not isinstance(profile, dict) or profile.get("individual_id") != owner or profile.get("adventure_id") != self._manifest["adventure_id"]
                    or profile.get("genome_sha256") != individual["genome_sha256"]
                    or profile.get("provenance") != value["provenance"]
                    or profile.get("context_sha256") != value["provenance"].get("context_sha256")):
                raise ValueError("accepted profile owner/genome/provenance mismatch")
        elif role in ("source-art", "front", "back", "icon", "portrait"):
            profile = self._accepted(owner, "profile")
            if profile is None or value["provenance"].get("profile_sha256") != profile["sha256"]:
                raise ValueError("accepted artwork owner/profile mismatch")
        elif role == "story" and (owner != self._manifest["adventure_id"] or value["provenance"].get("adventure_id") != owner):
            raise ValueError("accepted story adventure mismatch")
        return value

    def accepted(self, individual_id: str, role: str) -> dict | None:
        return self._accepted(individual_id, role)

    def _freeze(self, owner: str, role: str, data: bytes, provenance: dict) -> dict:
        if not isinstance(provenance, dict) or len(canonical(provenance)) > 16384:
            raise ValueError("bounded provenance object required")
        content_hash = hashlib.sha256(data).hexdigest()
        record = {"sha256": content_hash, "size": len(data), "role": role, "provenance": provenance}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self._accepted(owner, role)
            if previous is not None:
                if previous != record:
                    raise ValueError("accepted content is immutable; retain the original output")
                self.db.commit()
                return previous
            _write_once(self.path / "objects" / content_hash, data)
            self.db.execute("INSERT INTO accepted VALUES(?,?,?)", (owner, role, canonical(record).decode()))
            self.db.execute("UPDATE invocations SET status='accepted' WHERE owner=? AND role=?", (owner, role))
            self.db.commit()
            return record
        except Exception:
            self.db.rollback()
            raise

    def object_bytes(self, accepted_record: dict) -> bytes:
        expected = hash_id(accepted_record["sha256"])
        data = (self.path / "objects" / expected).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("retained object checksum mismatch")
        return data

    def generation_context(self, individual_id: str) -> dict:
        individual = self.individual(individual_id)
        parent_records = []
        for parent_id in individual["parents"] or []:
            profile, image = self._accepted(parent_id, "profile"), self._accepted(parent_id, "source-art")
            if profile is None or image is None:
                raise ValueError("offspring generation requires both actual parent profiles and retained source-art images")
            parent_records.append({"individual_id": parent_id, "profile": json.loads(self.object_bytes(profile)),
                                   "image_sha256": image["sha256"]})
        context = {"schema_version": 1, "adventure_id": self._manifest["adventure_id"], "individual": individual,
                "reference": self._manifest["reference"],
                "primers": [self._primer(p["primer_id"], p["version"]).to_dict() for p in individual["primer_ancestry"]],
                "parents": parent_records,
                "interpretation": "Model-mediated fictional expression; no fixed allele-to-color, score, morphology or battle-stat mapping."}
        if "genesis" in individual:
            donor_id = individual["genesis"]["donor_id"]
            profile, image = self._accepted(donor_id, "profile"), self._accepted(donor_id, "source-art")
            if profile is None or image is None:
                raise ValueError("genesis expression requires the actual living donor profile and retained image")
            context["donors"] = [{"individual_id": donor_id, "profile": json.loads(self.object_bytes(profile)), "image_sha256": image["sha256"]}]
            context["genesis_interpretation"] = "Ancient sample provenance is not a living parent. Reconstruction awards no breeding XP. Synthetic trainer contribution is fictional and does not infer personal traits."
        return json.loads(canonical(context))

    def asset_path(self, individual_id: str, role: str = "source-art") -> Path:
        record = self._accepted(individual_id, role)
        if record is None:
            raise ValueError("individual asset is not accepted")
        return (self.path / "objects" / record["sha256"]).resolve()

    def begin_generation(self, individual_id: str, role: str, request: dict) -> dict:
        """Commit before external invocation. Unknown outcomes never auto-retry."""
        self.individual(individual_id)
        if role not in ("profile", "source-art") or not isinstance(request, dict) or len(canonical(request)) > 128 * 1024:
            raise ValueError("bounded profile or source-art request required")
        frozen = canonical(request).decode()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT request_json,status FROM invocations WHERE owner=? AND role=?", (individual_id, role)).fetchone()
            if old:
                if old["request_json"] != frozen:
                    raise ValueError("generation request already frozen")
                self.db.commit()
                return {"should_invoke": False, "status": old["status"], "request_sha256": digest(request)}
            if self._accepted(individual_id, role) is not None:
                self.db.commit()
                return {"should_invoke": False, "status": "accepted", "request_sha256": digest(request)}
            count = self.db.execute("SELECT count(*) FROM invocations WHERE status='outcome_unknown'").fetchone()[0]
            if count >= MAX_IN_FLIGHT_GENERATIONS:
                raise ValueError("bounded generation concurrency exhausted; resolve an existing invocation first")
            self.db.execute("INSERT INTO invocations VALUES(?,?,?,'outcome_unknown')", (individual_id, role, frozen))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return {"should_invoke": True, "status": "outcome_unknown", "request_sha256": digest(request)}

    def record_generation_failure(self, individual_id: str, role: str, *, reason: str, outcome_known: bool) -> None:
        """Release a failed external invocation only after its outcome is known.

        Failed requests remain durable and cannot automatically invoke again.
        A retained actual result can still be accepted without another model call.
        """
        if outcome_known is not True or not isinstance(reason, str) or not 8 <= len(reason) <= 512:
            raise ValueError("explicit known outcome and bounded failure reason required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT request_json,status FROM invocations WHERE owner=? AND role=?", (individual_id, role)).fetchone()
            if row is None or row["status"] not in ("outcome_unknown", "failed"):
                raise ValueError("no pending external invocation")
            self.db.execute("UPDATE invocations SET status='failed' WHERE owner=? AND role=?", (individual_id, role))
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES(?,?)", (f"failure:{individual_id}:{role}", reason))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def accept_profile(self, individual_id: str, profile: dict, provenance: dict) -> dict:
        from genetics.expression import ExpressionBody
        if not isinstance(provenance, dict) or len(canonical(provenance)) > 16384:
            raise ValueError("bounded profile provenance object required")
        body = ExpressionBody.model_validate(profile).model_dump(mode="json")
        context = self.generation_context(individual_id)
        if (provenance.get("mode") not in ("fixture", "external_model", "openrouter")
                or not isinstance(provenance.get("model"), str) or not 1 <= len(provenance["model"]) <= 160
                or (provenance["mode"] == "external_model" and not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", provenance.get("external_tool", "")))):
            raise ValueError("explicit bounded model/mode/tool provenance required")
        hash_id(provenance.get("prompt_sha256"))
        self._verify_reserved_request(individual_id, "profile", provenance)
        if provenance.get("context_sha256") != digest(context):
            raise ValueError("profile must bind the exact individual/genome/parent generation context")
        payload = {"schema_version": 1, "individual_id": individual_id, "adventure_id": self._manifest["adventure_id"],
                   "genome_sha256": context["individual"]["genome_sha256"], "context_sha256": digest(context),
                   "expression": body, "provenance": provenance,
                   "parent_profile_sha256": [self._accepted(p["individual_id"], "profile")["sha256"] for p in context["parents"]],
                   "parent_image_sha256": [p["image_sha256"] for p in context["parents"]]}
        return self._freeze(individual_id, "profile", canonical(payload), provenance)

    def _verify_reserved_request(self, individual_id: str, role: str, provenance: dict) -> None:
        row = self.db.execute("SELECT request_json FROM invocations WHERE owner=? AND role=?", (individual_id, role)).fetchone()
        if row is not None and provenance.get("prompt_sha256") != digest(json.loads(row["request_json"])):
            raise ValueError("accepted output must bind the exact reserved generation request")

    def accept_asset(self, individual_id: str, role: str, data: bytes, provenance: dict) -> dict:
        self.individual(individual_id)
        if not isinstance(provenance, dict) or len(canonical(provenance)) > 16384:
            raise ValueError("bounded artwork provenance object required")
        if role not in ("source-art", "front", "back", "icon", "portrait"):
            raise ValueError("unsupported individual asset role")
        if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_ASSET_BYTES:
            raise ValueError("asset must be 1 byte..32 MiB")
        # Decode before permanent acceptance. Native preparation currently uses
        # PNG only; a signature is not proof of valid complete image bytes.
        from genetics.roster import decode_png
        decode_png(data)
        profile = self._accepted(individual_id, "profile")
        if profile is None:
            raise ValueError("accept the model-authored profile before artwork")
        if provenance.get("profile_sha256", profile["sha256"]) != profile["sha256"]:
            raise ValueError("artwork provenance binds a different accepted profile")
        if role == "source-art":
            self.generation_context(individual_id)
            self._verify_reserved_request(individual_id, role, provenance)
        return self._freeze(individual_id, role, data, provenance | {"profile_sha256": profile["sha256"]})

    def accept_story(self, graph: dict, provenance: dict) -> dict:
        from game_agents.adventure_story import StoryGraph, generate_story
        if not isinstance(graph, dict) or len(canonical(graph)) > 128 * 1024:
            raise ValueError("bounded story graph required")
        validated = StoryGraph.model_validate(graph)
        if validated.seed_commitment != hashlib.sha256(bytes.fromhex(self._manifest["seed"])).hexdigest():
            raise ValueError("story graph must bind this adventure seed")
        if validated.primer_id not in {p["primer_id"] for p in self._manifest["primers"]}:
            raise ValueError("story primer is not frozen in this adventure")
        if validated != generate_story(bytes.fromhex(self._manifest["seed"]), primer_id=validated.primer_id, signal_score=validated.signal_score):
            raise ValueError("story graph differs from its frozen seeded causal grammar")
        return self._freeze(self._manifest["adventure_id"], "story", canonical(validated.model_dump(mode="json")),
                            provenance | {"adventure_id": self._manifest["adventure_id"]})

    def retained_story(self) -> dict | None:
        record = self._accepted(self._manifest["adventure_id"], "story")
        return json.loads(self.object_bytes(record)) if record else None

    def freeze_content_manifest(self, *, native_mapping: list[dict], rom_sha256: str, build_identity: dict) -> dict:
        """Freeze a small prepared selection; no primer/native-species equivalence."""
        hash_id(rom_sha256)
        if not 1 <= len(native_mapping) <= self._manifest["capacity"]["prepared_native_individuals"]:
            raise ValueError("prepared native selection exceeds the measured two-individual proof capacity")
        seen_ids, seen_species, accepted = set(), set(), []
        for mapping in native_mapping:
            if set(mapping) != {"individual_id", "native_species", "native_personality"}:
                raise ValueError("explicit full-ID/native-species/personality mapping required")
            individual_id, species = mapping["individual_id"], mapping["native_species"]
            self.individual(individual_id)
            if type(species) is not int or not 1 <= species < 2048 or type(mapping["native_personality"]) is not int or not 0 <= mapping["native_personality"] < 2**32:
                raise ValueError("native compatibility fields outside packed limits")
            if individual_id in seen_ids or species in seen_species:
                raise ValueError("prepared mappings cannot alias identity or compiled appearance")
            seen_ids.add(individual_id)
            seen_species.add(species)
            assets = {role: self._accepted(individual_id, role) for role in ("profile", "source-art", "front", "back", "icon")}
            if any(value is None for value in assets.values()):
                raise ValueError("all profile/source/front/back/icon outputs must be accepted before export")
            accepted.append(mapping | {"assets": assets})
        story = self._accepted(self._manifest["adventure_id"], "story")
        if story is None:
            raise ValueError("accept the validated adventure story before export")
        value = {"schema_version": 1, "adventure_id": self._manifest["adventure_id"], "adventure_manifest_sha256": digest(self._manifest),
                 "rom_sha256": rom_sha256, "build_identity": build_identity, "native_mapping": accepted, "story": story}
        return self._freeze(self._manifest["adventure_id"], "prepared-content", canonical(value), {"mode": "compiled_immutable_package"})
