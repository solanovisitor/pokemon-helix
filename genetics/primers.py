"""Versioned metadata catalog; primers are templates, never native species IDs.

The real sequence is stored once. All baseline alleles here are explicitly
fictional and carry no allele-to-appearance or allele-to-stat interpretation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

GENETIC_SCHEMA = "aurora-virtual-genome-v2"
LOCI = 96
ALLELES = 16
LINKAGE_GROUP_SIZE = 12


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value: str, label: str = "identifier") -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,79}", value):
        raise ValueError(f"invalid {label}")
    return value


def hash_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("expected a canonical 256-bit hash")
    return value


@dataclass(frozen=True)
class VirtualGenome:
    haplotypes: tuple[tuple[int, ...], tuple[int, ...]]

    def __post_init__(self) -> None:
        owned = tuple(tuple(h) for h in self.haplotypes)
        if len(owned) != 2 or any(len(h) != LOCI for h in owned):
            raise ValueError("virtual genome requires two 96-locus haplotypes")
        if any(type(a) is not int or not 0 <= a < ALLELES for h in owned for a in h):
            raise ValueError("virtual alleles must be integers 0..15")
        object.__setattr__(self, "haplotypes", owned)

    def pack(self) -> bytes:
        flat = self.haplotypes[0] + self.haplotypes[1]
        return bytes(flat[i] | flat[i + 1] << 4 for i in range(0, 2 * LOCI, 2))

    def canonical_pack(self) -> bytes:
        # Homolog labels are irrelevant to duplicate-genome detection, but phase
        # inside each chromosome remains relevant to inheritance.
        left, right = [], []
        for start in range(0, LOCI, LINKAGE_GROUP_SIZE):
            pair = sorted(h[start:start + LINKAGE_GROUP_SIZE] for h in self.haplotypes)
            left.extend(pair[0])
            right.extend(pair[1])
        return VirtualGenome((tuple(left), tuple(right))).pack()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_pack()).hexdigest()

    def to_dict(self) -> dict:
        return {"schema": GENETIC_SCHEMA, "loci": LOCI, "ploidy": 2,
                "alleles": ALLELES, "packed_hex": self.pack().hex()}

    @classmethod
    def from_dict(cls, value: dict) -> VirtualGenome:
        if (not isinstance(value, dict) or set(value) != {"schema", "loci", "ploidy", "alleles", "packed_hex"}
                or value["schema"] != GENETIC_SCHEMA
                or any(type(value[k]) is not int or value[k] != v for k, v in (("loci", LOCI), ("ploidy", 2), ("alleles", ALLELES)))
                or not isinstance(value["packed_hex"], str)
                or not re.fullmatch(r"[0-9a-f]{192}", value["packed_hex"])):
            raise ValueError("unsupported or malformed virtual genome")
        flat = tuple(a for b in bytes.fromhex(value["packed_hex"]) for a in (b & 15, b >> 4))
        return cls((flat[:LOCI], flat[LOCI:]))


@dataclass(frozen=True)
class ReferenceBinding:
    reference_id: str
    accession: str
    sequence_sha256: str
    transform_version: str
    payload_json: str

    def __post_init__(self) -> None:
        identifier(self.reference_id)
        hash_id(self.sequence_sha256)
        if not self.accession or len(self.accession) > 128 or not self.transform_version or len(self.transform_version) > 128:
            raise ValueError("bounded reference accession and transform required")
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict) or len(canonical(payload)) > 65536:
            raise ValueError("reference context must be a bounded object")
        sequence = payload.get("sequence")
        if (not isinstance(sequence, str) or not 1 <= len(sequence) <= 4096
                or set(sequence) - set("ACGT") or hashlib.sha256(sequence.encode()).hexdigest() != self.sequence_sha256):
            raise ValueError("reference sequence checksum mismatch")
        object.__setattr__(self, "payload_json", canonical(payload).decode())

    def to_dict(self) -> dict:
        return {"reference_id": self.reference_id, "accession": self.accession,
                "sequence_sha256": self.sequence_sha256, "transform_version": self.transform_version,
                "conditioning_payload": json.loads(self.payload_json)}

    @classmethod
    def from_dict(cls, value: dict) -> ReferenceBinding:
        return cls(value["reference_id"], value["accession"], value["sequence_sha256"],
                   value["transform_version"], canonical(value["conditioning_payload"]).decode())

    @classmethod
    def from_legacy_reference(cls, reference: Any) -> ReferenceBinding:
        return cls("zebrafish-fragment-v1", reference.accession, reference.checksum_sha256,
                   reference.transform_version, canonical(reference.conditioning_payload()).decode())


@dataclass(frozen=True)
class PrimerDefinition:
    primer_id: str
    version: int
    label: str
    baseline: VirtualGenome
    reference_id: str
    base_phenotype: str
    visual_constraints: tuple[str, ...]
    compatibility_group: str = "lumifin"
    reference_art_sha256: str | None = None
    gameplay_defaults_json: str = '{"experience_curve":"medium_fast","role":"authored_water_companion"}'

    def __post_init__(self) -> None:
        identifier(self.primer_id)
        identifier(self.reference_id)
        identifier(self.compatibility_group)
        if type(self.version) is not int or not 1 <= self.version <= 65535:
            raise ValueError("primer version must be 1..65535")
        if not isinstance(self.baseline, VirtualGenome):
            raise ValueError("primer requires a virtual baseline genome")
        if not isinstance(self.label, str) or not 1 <= len(self.label) <= 96:
            raise ValueError("bounded primer label required")
        if not isinstance(self.base_phenotype, str) or not 10 <= len(self.base_phenotype) <= 2000:
            raise ValueError("bounded base phenotype required")
        constraints = tuple(self.visual_constraints)
        if not 1 <= len(constraints) <= 16 or any(not isinstance(v, str) or not 1 <= len(v) <= 512 for v in constraints):
            raise ValueError("bounded visual constraints required")
        object.__setattr__(self, "visual_constraints", constraints)
        if self.reference_art_sha256 is not None:
            hash_id(self.reference_art_sha256)
        defaults = json.loads(self.gameplay_defaults_json)
        if not isinstance(defaults, dict) or len(canonical(defaults)) > 4096:
            raise ValueError("bounded authored gameplay defaults required")
        object.__setattr__(self, "gameplay_defaults_json", canonical(defaults).decode())

    def to_dict(self) -> dict:
        return {"schema_version": 1, "primer_id": self.primer_id, "version": self.version, "label": self.label,
                "genetic_schema": GENETIC_SCHEMA, "baseline_virtual_genotype": self.baseline.to_dict(),
                "reference_id": self.reference_id, "base_phenotype": self.base_phenotype,
                "visual_constraints": list(self.visual_constraints), "compatibility_group": self.compatibility_group,
                "reference_art_sha256": self.reference_art_sha256,
                "gameplay_defaults": json.loads(self.gameplay_defaults_json)}

    @classmethod
    def from_dict(cls, value: dict) -> PrimerDefinition:
        expected = {"schema_version", "primer_id", "version", "label", "genetic_schema", "baseline_virtual_genotype",
                    "reference_id", "base_phenotype", "visual_constraints", "compatibility_group", "reference_art_sha256", "gameplay_defaults"}
        if not isinstance(value, dict) or set(value) != expected or value["schema_version"] != 1 or value["genetic_schema"] != GENETIC_SCHEMA:
            raise ValueError("unsupported primer definition")
        return cls(value["primer_id"], value["version"], value["label"], VirtualGenome.from_dict(value["baseline_virtual_genotype"]),
                   value["reference_id"], value["base_phenotype"], tuple(value["visual_constraints"]),
                   value["compatibility_group"], value["reference_art_sha256"], canonical(value["gameplay_defaults"]).decode())


def baseline_for_primer(primer_id: str, version: int = 1) -> VirtualGenome:
    """Explicitly fictional baseline; real sequence bases are not virtual alleles."""
    identifier(primer_id)
    raw = hashlib.shake_256(canonical([GENETIC_SCHEMA, "primer-baseline", primer_id, version])).digest(LOCI)
    flat = tuple(a for b in raw for a in (b & 15, b >> 4))
    return VirtualGenome((flat[:LOCI], flat[LOCI:]))


def fixture_primer(index: int, reference_id: str = "zebrafish-fragment-v1") -> PrimerDefinition:
    if type(index) is not int or not 0 <= index < 1_000_000:
        raise ValueError("fixture primer index outside bounds")
    name = f"fixture-primer-{index:06d}"
    return PrimerDefinition(name, 1, f"Metadata fixture {index}", baseline_for_primer(name), reference_id,
                            "Metadata-only fictional aquatic archetype; not accepted or playable artwork.",
                            ("Original compact aquatic family with luminous sensory structures.",),
                            reference_art_sha256=hashlib.sha256(f"unloaded-fixture-asset:{index}".encode()).hexdigest())


class PrimerCatalog:
    """SQLite keyset pagination never resolves image bytes or invokes a model."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS shared_references(reference_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS primers(
                primer_id TEXT NOT NULL, version INTEGER NOT NULL, reference_id TEXT NOT NULL,
                baseline_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(primer_id, version), FOREIGN KEY(reference_id) REFERENCES shared_references(reference_id));
            CREATE INDEX IF NOT EXISTS primer_baselines ON primers(baseline_sha256);
        """)

    def close(self) -> None:
        self.db.close()

    def register_reference(self, binding: ReferenceBinding) -> None:
        serialized = canonical(binding.to_dict()).decode()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            old = self.db.execute("SELECT payload FROM shared_references WHERE reference_id=?", (binding.reference_id,)).fetchone()
            if old and old[0] != serialized:
                raise ValueError("reference version already has different immutable data")
            self.db.execute("INSERT OR IGNORE INTO shared_references VALUES(?,?)", (binding.reference_id, serialized))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def put_many(self, primers: Iterable[PrimerDefinition]) -> int:
        count = 0
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for primer in primers:
                serialized = canonical(primer.to_dict()).decode()
                old = self.db.execute("SELECT payload FROM primers WHERE primer_id=? AND version=?", (primer.primer_id, primer.version)).fetchone()
                if old:
                    if old[0] != serialized:
                        raise ValueError("primer version already has different immutable data")
                else:
                    collision = self.db.execute("SELECT primer_id FROM primers WHERE baseline_sha256=? AND primer_id<>? LIMIT 1",
                                                (primer.baseline.sha256, primer.primer_id)).fetchone()
                    if collision:
                        raise ValueError("distinct primers require distinct baseline virtual genomes")
                    self.db.execute("INSERT INTO primers VALUES(?,?,?,?,?)", (primer.primer_id, primer.version, primer.reference_id,
                                                                              primer.baseline.sha256, serialized))
                    count += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return count

    def put(self, primer: PrimerDefinition) -> None:
        self.put_many((primer,))

    def get(self, primer_id: str, version: int = 1) -> PrimerDefinition:
        row = self.db.execute("SELECT payload FROM primers WHERE primer_id=? AND version=?", (primer_id, version)).fetchone()
        if row is None:
            raise KeyError((primer_id, version))
        return PrimerDefinition.from_dict(json.loads(row[0]))

    def page(self, *, limit: int = 50, after: tuple[str, int] | None = None) -> dict:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("page limit must be 1..200")
        if after is None:
            rows = self.db.execute("SELECT primer_id,version,payload FROM primers ORDER BY primer_id,version LIMIT ?", (limit + 1,)).fetchall()
        else:
            if len(after) != 2 or type(after[1]) is not int:
                raise ValueError("invalid catalog cursor")
            identifier(after[0])
            rows = self.db.execute("SELECT primer_id,version,payload FROM primers WHERE (primer_id,version)>(?,?) ORDER BY primer_id,version LIMIT ?",
                                   (*after, limit + 1)).fetchall()
        selected = rows[:limit]
        return {"items": [json.loads(row[2]) for row in selected],
                "next_cursor": (selected[-1][0], selected[-1][1]) if len(rows) > limit else None}

    def count(self) -> int:
        return self.db.execute("SELECT count(*) FROM primers").fetchone()[0]
