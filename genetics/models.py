"""Versioned, immutable values for a fictional diploid inheritance model."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any

SCHEMA_VERSION = 1
MODEL_VERSION = "aurora-inheritance-v1"
LOCI = 32
ALLELES = 4


def unit(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{label} must be a finite number in [0, 1]")
    return float(value)


@dataclass(frozen=True)
class Genotype:
    """Two owned haplotypes, 32 loci each, four alleles per locus (16 bytes)."""

    haplotypes: tuple[tuple[int, ...], tuple[int, ...]]

    def __post_init__(self) -> None:
        owned = tuple(tuple(haplotype) for haplotype in self.haplotypes)
        if len(owned) != 2 or any(len(haplotype) != LOCI for haplotype in owned):
            raise ValueError("genotype requires two haplotypes of 32 loci")
        if any(type(allele) is not int or not 0 <= allele < ALLELES for haplotype in owned for allele in haplotype):
            raise ValueError("alleles must be integers 0..3")
        object.__setattr__(self, "haplotypes", owned)

    def pack(self) -> bytes:
        flat = self.haplotypes[0] + self.haplotypes[1]
        return bytes(sum(flat[i + j] << (j * 2) for j in range(4)) for i in range(0, 64, 4))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "loci": LOCI, "ploidy": 2, "packed_hex": self.pack().hex()}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Genotype:
        if not isinstance(value, dict) or set(value) != {"schema_version", "loci", "ploidy", "packed_hex"}:
            raise ValueError("invalid genotype fields")
        if any(type(value[key]) is not int or value[key] != expected for key, expected in
               (("schema_version", SCHEMA_VERSION), ("loci", LOCI), ("ploidy", 2))):
            raise ValueError("unsupported genotype schema")
        if not isinstance(value["packed_hex"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["packed_hex"]):
            raise ValueError("packed genotype must be 16 canonical bytes")
        flat = tuple((byte >> (offset * 2)) & 3 for byte in bytes.fromhex(value["packed_hex"]) for offset in range(4))
        return cls((flat[:LOCI], flat[LOCI:]))


@dataclass(frozen=True)
class SpeciesConfig:
    species_id: str = "aurora_lumifin"
    label: str = "Lumifin (experimental family)"
    reference_metadata_json: str = '{"source":"authored-neutral-template"}'
    reference_features_json: str = '{}'
    reference_payload_json: str = '{}'
    visual_constraints: tuple[str, ...] = (
        "Original small fish/amphibian creature, family Lumifin; not an existing Pokemon design.",
        "Readable 32x32 pixel-art silhouette, 15 opaque colors plus transparent background.",
        "Shared family anatomy: compact body, short fins or limbs, luminous sensory organ.",
        "Individual appearance is a model interpretation of genome, lineage and visual references.",
        "No allele has a predefined color, body part, ability, score or biological meaning.",
    )
    mutation_rate: float = 0.001
    crossover_rate: float = 0.12

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,47}", self.species_id):
            raise ValueError("invalid species identifier")
        if not isinstance(self.label, str) or not 1 <= len(self.label) <= 96:
            raise ValueError("invalid species label")
        unit(self.mutation_rate, "mutation_rate")
        unit(self.crossover_rate, "crossover_rate")
        metadata = json.loads(self.reference_metadata_json)
        if not isinstance(metadata, dict):
            raise ValueError("reference metadata must be an object")
        # Canonical JSON owns its data; callers cannot mutate the species indirectly.
        object.__setattr__(self, "reference_metadata_json", json.dumps(metadata, sort_keys=True, allow_nan=False))
        features = json.loads(self.reference_features_json)
        if not isinstance(features, dict):
            raise ValueError("reference features must be an object")
        object.__setattr__(self, "reference_features_json", json.dumps(features, sort_keys=True, allow_nan=False))
        payload = json.loads(self.reference_payload_json)
        if not isinstance(payload, dict):
            raise ValueError("reference payload must be an object")
        object.__setattr__(self, "reference_payload_json", json.dumps(payload, sort_keys=True, allow_nan=False))
        constraints = tuple(self.visual_constraints)
        if not 1 <= len(constraints) <= 16 or any(not isinstance(value, str) or not 1 <= len(value) <= 512 for value in constraints):
            raise ValueError("one to sixteen bounded visual constraints required")
        object.__setattr__(self, "visual_constraints", constraints)

    @classmethod
    def from_reference(cls, reference: Any, **options: Any) -> SpeciesConfig:
        return cls(reference_features_json=json.dumps(reference.features, sort_keys=True, allow_nan=False),
                   reference_metadata_json=json.dumps(reference.metadata, sort_keys=True, allow_nan=False),
                   reference_payload_json=json.dumps(reference.conditioning_payload(), sort_keys=True, allow_nan=False), **options)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.species_id, "label": self.label, "reference": json.loads(self.reference_metadata_json),
                "reference_features": json.loads(self.reference_features_json), "visual_constraints": list(self.visual_constraints),
                "reference_context": json.loads(self.reference_payload_json),
                "mutation_rate": self.mutation_rate, "crossover_rate": self.crossover_rate,
                "linkage_groups": [list(range(start, start + 8)) for start in range(0, LOCI, 8)]}


@dataclass(frozen=True)
class Mutation:
    haplotype: int
    locus: int
    before: int
    after: int

    def __post_init__(self) -> None:
        if (type(self.haplotype) is not int or self.haplotype not in (0, 1)
                or type(self.locus) is not int or not 0 <= self.locus < LOCI
                or any(type(value) is not int or not 0 <= value < ALLELES for value in (self.before, self.after))
                or self.before == self.after):
            raise ValueError("mutation must change one valid virtual allele")

    def to_dict(self) -> dict[str, int]:
        return {"haplotype": self.haplotype, "locus": self.locus, "before": self.before, "after": self.after}


@dataclass(frozen=True)
class Individual:
    id: str
    species_id: str
    generation: int
    genotype: Genotype
    parents: tuple[str, str] | None = None
    mutations: tuple[Mutation, ...] = ()

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,47}", self.species_id):
            raise ValueError("invalid species identifier")
        if not re.fullmatch(r"[0-9a-f]{24}", self.id):
            raise ValueError("invalid individual identifier")
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError("invalid generation")
        if not isinstance(self.genotype, Genotype):
            raise ValueError("invalid genotype")
        if self.parents is not None:
            owned = tuple(self.parents)
            if len(owned) != 2 or owned[0] == owned[1] or any(not re.fullmatch(r"[0-9a-f]{24}", parent) for parent in owned):
                raise ValueError("two distinct parent identifiers required")
            object.__setattr__(self, "parents", owned)
        if (self.generation == 0) != (self.parents is None):
            raise ValueError("founders have no parents; descendants require parents")
        object.__setattr__(self, "mutations", tuple(self.mutations))
        if len({(mutation.haplotype, mutation.locus) for mutation in self.mutations}) != len(self.mutations):
            raise ValueError("only one mutation per inherited allele is supported")
        if any(self.genotype.haplotypes[mutation.haplotype][mutation.locus] != mutation.after for mutation in self.mutations):
            raise ValueError("mutation records must match inherited genotype")
