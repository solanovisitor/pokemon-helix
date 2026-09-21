"""Offline universal-individual contracts, deliberately separate from v1/v2.

Fictional alleles do not determine art, personality, IVs or battle statistics.
This module does not issue Pokémon, edit saves, or unlock CORAL.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import re

GENOME_SCHEMA = "helix-universal-genome-v3"
INHERITANCE_VERSION = "helix-linked-inheritance-v3"
LOCI = 96
ALLELES = 16
LINKAGE_GROUP_SIZE = 12


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _hex(value: str, length: int, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{%d}" % length, value) is None:
        raise ValueError(f"invalid {label}")
    return value


def _uint(value: int, maximum: int, label: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class Genome:
    """96 loci, two phased homologs, four bits per fictional allele."""

    haplotypes: tuple[tuple[int, ...], tuple[int, ...]]

    def __post_init__(self) -> None:
        owned = tuple(tuple(h) for h in self.haplotypes)
        if len(owned) != 2 or any(len(h) != LOCI for h in owned):
            raise ValueError("v3 requires two 96-locus homologs")
        for h in owned:
            for a in h:
                _uint(a, 15, "allele")
        object.__setattr__(self, "haplotypes", owned)

    def pack(self) -> bytes:
        flat = self.haplotypes[0] + self.haplotypes[1]
        return bytes(flat[i] | flat[i + 1] << 4 for i in range(0, 192, 2))

    @property
    def sha256(self) -> str:
        # Includes schema and ordered phase. This is content, never identity.
        return hashlib.sha256(canonical(self.to_dict())).hexdigest()

    def to_dict(self) -> dict:
        return {"schema": GENOME_SCHEMA, "loci": 96, "ploidy": 2,
                "alleles": 16, "packed_hex": self.pack().hex()}

    @classmethod
    def from_dict(cls, value: dict) -> Genome:
        if (not isinstance(value, dict)
                or set(value) != {"schema", "loci", "ploidy", "alleles", "packed_hex"}
                or value["schema"] != GENOME_SCHEMA
                or any(type(value[k]) is not int or value[k] != v
                       for k, v in (("loci", 96), ("ploidy", 2), ("alleles", 16)))):
            raise ValueError("unsupported genome; v1/v2 cannot be reinterpreted as v3")
        packed = bytes.fromhex(_hex(value["packed_hex"], 192, "genome"))
        flat = tuple(a for byte in packed for a in (byte & 15, byte >> 4))
        return cls((flat[:96], flat[96:]))


@dataclass(frozen=True)
class Individual:
    """A host contract; native IDs may be represented by a different tagged codec.

    Acquisition/view state is intentionally absent. Origin provenance is retained
    as bounded canonical JSON, allowing an exact saved evidence binding.
    """

    individual_id: str
    genome: Genome
    origin: str
    provenance_json: str
    parents: tuple[str, str] | None = None
    expression_binding: str | None = None
    birth_date: str | None = None

    def __post_init__(self) -> None:
        _hex(self.individual_id, 64, "host individual ID")
        if not isinstance(self.genome, Genome):
            raise ValueError("explicit v3 genome required")
        if self.origin not in {"synthetic_fixture", "legacy_registration", "wild_encounter", "inherited"}:
            raise ValueError("unknown origin")
        if self.parents is not None:
            parents = tuple(self.parents)
            if len(parents) != 2 or parents[0] == parents[1] or self.individual_id in parents:
                raise ValueError("two distinct parents required")
            for parent in parents:
                _hex(parent, 64, "parent ID")
            object.__setattr__(self, "parents", parents)
        if self.origin == "inherited" and self.parents is None:
            raise ValueError("inherited individual needs recorded parents")
        if self.origin != "inherited" and self.parents is not None:
            raise ValueError("initial registration cannot invent parents")
        if self.expression_binding is not None:
            _hex(self.expression_binding, 64, "expression binding")
        if self.birth_date is not None:
            from datetime import date
            if (not isinstance(self.birth_date, str)
                    or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.birth_date) is None):
                raise ValueError("birth date must be recorded calendar date or unknown")
            date.fromisoformat(self.birth_date)
        try:
            provenance = json.loads(self.provenance_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("invalid origin provenance") from error
        budget = 32768 if self.origin == "inherited" else 4096
        if not isinstance(provenance, dict) or not provenance or len(canonical(provenance)) > budget:
            raise ValueError("bounded nonempty provenance required")
        object.__setattr__(self, "provenance_json", canonical(provenance).decode())

    def to_dict(self) -> dict:
        return {"schema": "helix-individual-v3", "id": self.individual_id,
                "genome": self.genome.to_dict(), "genome_sha256": self.genome.sha256,
                "origin": self.origin, "provenance": json.loads(self.provenance_json),
                "parents": list(self.parents) if self.parents else None,
                "expression_binding": self.expression_binding, "birth_date": self.birth_date}

    @classmethod
    def from_dict(cls, value: dict) -> Individual:
        fields = {"schema", "id", "genome", "genome_sha256", "origin", "provenance", "parents",
                  "expression_binding", "birth_date"}
        if (not isinstance(value, dict) or set(value) != fields or value["schema"] != "helix-individual-v3"
                or value["parents"] is not None and not isinstance(value["parents"], list)):
            raise ValueError("unsupported individual contract")
        genome = Genome.from_dict(value["genome"])
        if value["genome_sha256"] != genome.sha256:
            raise ValueError("individual genome binding differs")
        return cls(value["id"], genome, value["origin"], canonical(value["provenance"]).decode(),
                   tuple(value["parents"]) if value["parents"] is not None else None,
                   value["expression_binding"], value["birth_date"])


def derive_identity(namespace: str, intent: str) -> str:
    """Local intent identity, independent of genetics, species and PID/OT."""
    _hex(namespace, 64, "local identity namespace")
    if not isinstance(intent, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}", intent) is None:
        raise ValueError("invalid stable identity intent")
    return hmac.new(bytes.fromhex(namespace), canonical(["helix-identity-v3", intent]), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class InheritancePolicy:
    """Integer probabilities per million; no genome uniqueness requirement."""

    version: str = INHERITANCE_VERSION
    crossover_ppm: int = 120_000
    mutation_ppm: int = 2_000

    def __post_init__(self) -> None:
        if self.version != INHERITANCE_VERSION:
            raise ValueError("unsupported inheritance policy")
        _uint(self.crossover_ppm, 1_000_000, "crossover probability")
        _uint(self.mutation_ppm, 1_000_000, "mutation probability")


class _Stream:
    def __init__(self, seed: str, domain: str, intent: str):
        _hex(seed, 64, "inheritance seed")
        self.key = hmac.new(bytes.fromhex(seed), canonical([INHERITANCE_VERSION, domain, intent]), hashlib.sha256).digest()
        self.counter, self.buffer = 0, b""

    def below(self, bound: int) -> int:
        # Fixed four-byte draws plus rejection avoid modulo bias; no Python RNG.
        limit = (1 << 32) - (1 << 32) % bound
        while True:
            if not self.buffer:
                self.buffer = hmac.new(self.key, self.counter.to_bytes(8, "little"), hashlib.sha256).digest()
                self.counter += 1
            draw, self.buffer = int.from_bytes(self.buffer[:4], "little"), self.buffer[4:]
            if draw < limit:
                return draw % bound


def inherit(first: Individual, second: Individual, *, namespace: str, intent: str,
            seed: str, policy: InheritancePolicy = InheritancePolicy()) -> tuple[Individual, dict]:
    """Synthetic host offspring only, with reconstructable meiosis/mutation audit.

    Duplicate genomes are valid. This function has no native issuance path.
    """
    child_id = derive_identity(namespace, intent)
    if first.individual_id == second.individual_id or child_id in (first.individual_id, second.individual_id):
        raise ValueError("child and parents must have distinct identities")
    meiosis, mutation = _Stream(seed, "meiosis", intent), _Stream(seed, "germline-mutation", intent)
    gametes, origins, changes = [], [], []
    for haplotype, parent in enumerate((first, second)):
        alleles, source = [], []
        for group in range(0, LOCI, LINKAGE_GROUP_SIZE):
            homolog = meiosis.below(2)
            for locus in range(group, group + LINKAGE_GROUP_SIZE):
                if locus > group and meiosis.below(1_000_000) < policy.crossover_ppm:
                    homolog ^= 1
                before = parent.genome.haplotypes[homolog][locus]
                after = before
                if mutation.below(1_000_000) < policy.mutation_ppm:
                    after = (before + 1 + mutation.below(15)) % 16
                    changes.append({"haplotype": haplotype, "locus": locus, "before": before,
                                    "after": after, "scope": "germline", "cause": "sampled_substitution"})
                alleles.append(after)
                source.append(homolog)
        gametes.append(tuple(alleles))
        origins.append(source)
    audit = {"schema": "helix-inheritance-audit-v3", "policy": asdict(policy),
             "seed": seed, "intent": intent, "namespace": namespace,
             "parents": [p.individual_id for p in (first, second)],
             "parent_genome_sha256": [p.genome.sha256 for p in (first, second)],
             "parental_homologs": origins, "mutations": changes}
    child = Individual(child_id, Genome(tuple(gametes)), "inherited", canonical(audit).decode(),
                       (first.individual_id, second.individual_id))
    return child, audit


def verify_inheritance(child: Individual, audit: dict, first: Individual, second: Individual) -> None:
    """Recompute, do not trust an attacker-updated outer checksum or mutation list."""
    if not isinstance(audit, dict) or set(audit) != {"schema", "policy", "seed", "intent", "namespace",
                                                    "parents", "parent_genome_sha256", "parental_homologs", "mutations"}:
        raise ValueError("invalid inheritance audit")
    try:
        actual_child, actual_audit = inherit(first, second, namespace=audit["namespace"], intent=audit["intent"],
                                            seed=audit["seed"], policy=InheritancePolicy(**audit["policy"]))
    except (KeyError, TypeError) as error:
        raise ValueError("invalid inheritance audit") from error
    if child != actual_child or audit != actual_audit:
        raise ValueError("inheritance differs from frozen inputs")


@dataclass(frozen=True)
class AcquiredState:
    """Phenotypic/gameplay state: none of these fields enters inheritance."""

    species: int
    form: int = 0
    experience: int = 0
    observed_maturity_days: int = 0
    somatic_revisions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, maximum in (("species", 65535), ("form", 65535), ("experience", 0xffffffff),
                              ("observed_maturity_days", 65535)):
            _uint(getattr(self, name), maximum, name)
        revisions = tuple(self.somatic_revisions)
        if len(revisions) > 16 or len(set(revisions)) != len(revisions):
            raise ValueError("bounded unique somatic revisions required")
        for revision in revisions:
            _hex(revision, 64, "somatic revision")
        object.__setattr__(self, "somatic_revisions", revisions)


def reconcile_observations(observations: list[dict]) -> dict[str, dict]:
    """Exact retries/copies coalesce; divergent histories never silently merge.

    This is not a database or a global identity/ownership authority.
    """
    result = {}
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {"individual", "state", "history_sha256"}:
            raise ValueError("invalid universal observation")
        individual = observation["individual"]
        if not isinstance(individual, Individual) or not isinstance(observation["state"], AcquiredState):
            raise ValueError("typed individual and acquired state required")
        _hex(observation["history_sha256"], 64, "history commitment")
        payload = {"individual": individual.to_dict(), "state": asdict(observation["state"]),
                   "history_sha256": observation["history_sha256"]}
        prior = result.get(individual.individual_id)
        if prior is not None and prior != payload:
            raise ValueError("conflicting histories for one individual; explicit reconciliation required")
        result[individual.individual_id] = payload
    return result
