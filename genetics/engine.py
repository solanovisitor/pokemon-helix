"""Seeded inheritance produces input for once-generated, persisted individual art.

There is intentionally no genotype-to-color, phenotype, ability or fitness formula.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
from statistics import fmean
from typing import Any

from genetics.models import ALLELES, LOCI, MODEL_VERSION, SCHEMA_VERSION, Genotype, Individual, Mutation, SpeciesConfig

VIRTUAL_REFERENCE = Genotype((tuple(i % 4 for i in range(LOCI)), tuple((i + 1) % 4 for i in range(LOCI))))


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _identity(*parts: Any) -> str:
    return hashlib.sha256(_canonical(parts)).hexdigest()[:24]


def founders(species: SpeciesConfig, *, seed: int, population_size: int) -> tuple[Individual, ...]:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ValueError("seed must be an unsigned 64-bit integer")
    if type(population_size) is not int or not 2 <= population_size <= 256:
        raise ValueError("population size must be 2..256")
    rng = random.Random(seed)
    result = []
    for index in range(population_size):
        genotype = Genotype(tuple(tuple(rng.randrange(ALLELES) for _ in range(LOCI)) for _ in range(2)))
        identifier = _identity(MODEL_VERSION, species.species_id, seed, "founder", index, genotype.to_dict())
        result.append(Individual(identifier, species.species_id, 0, genotype))
    return tuple(result)


def _gamete(genotype: Genotype, rng: random.Random, species: SpeciesConfig, haplotype: int) -> tuple[tuple[int, ...], tuple[Mutation, ...]]:
    alleles, mutations = [], []
    for start in range(0, LOCI, 8):
        homolog = rng.randrange(2)
        for locus in range(start, start + 8):
            if locus > start and rng.random() < species.crossover_rate:
                homolog = 1 - homolog
            before = allele = genotype.haplotypes[homolog][locus]
            if rng.random() < species.mutation_rate:
                allele = (allele + rng.randrange(1, ALLELES)) % ALLELES
                mutations.append(Mutation(haplotype, locus, before, allele))
            alleles.append(allele)
    return tuple(alleles), tuple(mutations)


def breed(first: Individual, second: Individual, *, species: SpeciesConfig, rng: random.Random,
          generation: int, index: int, namespace: str) -> Individual:
    if first.id == second.id or first.species_id != species.species_id or second.species_id != species.species_id:
        raise ValueError("breeding requires distinct parents of the configured family")
    if type(generation) is not int or generation <= max(first.generation, second.generation):
        raise ValueError("child generation must follow both parents")
    if type(index) is not int or index < 0 or not isinstance(namespace, str) or not 1 <= len(namespace) <= 128:
        raise ValueError("bounded lineage namespace and nonnegative offspring index required")
    left, left_mutations = _gamete(first.genotype, rng, species, 0)
    right, right_mutations = _gamete(second.genotype, rng, species, 1)
    genotype = Genotype((left, right))
    parent_ids = (first.id, second.id)
    identifier = _identity(MODEL_VERSION, species.species_id, namespace, generation, index, parent_ids, genotype.to_dict())
    return Individual(identifier, species.species_id, generation, genotype, parent_ids, left_mutations + right_mutations)


def variation(genotype: Genotype) -> dict[str, Any]:
    flat = genotype.haplotypes[0] + genotype.haplotypes[1]
    reference = VIRTUAL_REFERENCE.haplotypes[0] + VIRTUAL_REFERENCE.haplotypes[1]
    differences = [{"haplotype": i // LOCI, "locus": i % LOCI, "reference": before, "allele": after}
                   for i, (before, after) in enumerate(zip(reference, flat)) if before != after]
    return {"allele_counts": [flat.count(allele) for allele in range(ALLELES)],
            "heterozygosity": fmean(a != b for a, b in zip(*genotype.haplotypes)),
            "differences_from_virtual_reference": differences,
            "interpretation": "Descriptive virtual-allele variation only; no correspondence to real-sequence variants or fixed appearance effects."}


def _individual_dict(individual: Individual) -> dict[str, Any]:
    return {"id": individual.id, "species_id": individual.species_id, "generation": individual.generation,
            "parents": list(individual.parents) if individual.parents else None, "genotype": individual.genotype.to_dict(),
            "alleles": [list(haplotype) for haplotype in individual.genotype.haplotypes],
            "genome_sha256": hashlib.sha256(individual.genotype.pack()).hexdigest(), "variation": variation(individual.genotype),
            "mutations": [value.to_dict() for value in individual.mutations]}


def run_experiment(*, species: SpeciesConfig | None = None, seed: int = 20260920, generations: int = 10,
                   population_size: int = 64) -> dict[str, Any]:
    if type(generations) is not int or not 1 <= generations <= 100:
        raise ValueError("generations must be 1..100")
    species = species or SpeciesConfig()
    initial = founders(species, seed=seed, population_size=population_size)
    rng = random.Random(int(_identity(MODEL_VERSION, seed, "pedigree"), 16))
    population = initial
    lineage = list(initial)
    history = []
    for generation in range(generations + 1):
        history.append({"generation": generation, "population_size": len(population),
                        "mutation_count": sum(len(value.mutations) for value in population),
                        "heterozygosity": fmean(a != b for value in population for a, b in zip(*value.genotype.haplotypes))})
        if generation == generations:
            break
        children = []
        for index in range(population_size):
            # The first sibling pair always belongs to the first two parents, so
            # the four selected rendering jobs form an immediately usable family.
            first, second = population[:2] if index < 2 else rng.sample(population, 2)
            children.append(breed(first, second, species=species, rng=rng, generation=generation + 1,
                                  index=index, namespace=f"{seed}:pedigree"))
        population = tuple(children)
        lineage.extend(population)
    individuals = [_individual_dict(value) for value in lineage]
    chosen = [individuals[0], individuals[1], individuals[population_size], individuals[population_size + 1]]
    requests = []
    for role, individual in zip(("parent_a", "parent_b", "child_a", "child_b"), chosen):
        context = {"schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION, "individual": copy.deepcopy(individual),
                   "virtual_reference_genotype": VIRTUAL_REFERENCE.to_dict(), "species": species.to_dict(),
                   "expression_policy": "Interpret genome and lineage creatively with a generative model. Do not invent a fixed allele-to-appearance, trait, stat or fitness mapping. Preserve family resemblance through actual parent images."}
        requests.append({"individual_id": individual["id"], "role": role, "status": "pending",
                         "context": context, "context_sha256": hashlib.sha256(_canonical(context)).hexdigest(),
                         "prepared_request": None, "result": None})
    return {"schema_version": SCHEMA_VERSION, "model_version": MODEL_VERSION, "seed": seed,
            "population_size": population_size, "generations": generations, "species": species.to_dict(),
            "virtual_reference_genotype": VIRTUAL_REFERENCE.to_dict(), "history": history,
            "individuals": individuals, "generation_requests": requests,
            "interpretation": "Seeded inheritance is reproducible. Individual art is model-mediated, generated once and persisted; genotype does not deterministically specify appearance or biological traits.",
            "mating": "Distinct parents; first two children form a sibling pair from first two parents, others sampled uniformly. No fitness or environmental selection model."}


def _job(report: dict[str, Any], individual_id: str) -> dict[str, Any]:
    if report.get("schema_version") != SCHEMA_VERSION or report.get("model_version") != MODEL_VERSION:
        raise ValueError("unsupported experiment schema")
    matches = [job for job in report["generation_requests"] if job["individual_id"] == individual_id]
    if len(matches) != 1:
        raise ValueError("individual must have exactly one generation job")
    job = matches[0]
    if hashlib.sha256(_canonical(job["context"])).hexdigest() != job["context_sha256"]:
        raise ValueError("immutable genetic generation context changed")
    individual = job["context"]["individual"]
    genotype = Genotype.from_dict(individual["genotype"])
    if (individual["id"] != individual_id or individual["genome_sha256"] != hashlib.sha256(genotype.pack()).hexdigest()
            or individual["alleles"] != [list(haplotype) for haplotype in genotype.haplotypes]):
        raise ValueError("individual genotype, identity and hash must agree")
    prepared = job.get("prepared_request")
    if prepared is not None:
        if (prepared["individual_id"] != individual_id or prepared["context_sha256"] != job["context_sha256"]
                or hashlib.sha256(prepared["prompt"].encode()).hexdigest() != prepared["prompt_sha256"]):
            raise ValueError("prepared generation request changed")
        if prepared.get("expression_profile") is not None:
            profile = _expression_profile(prepared["expression_profile"], job)
            if (prepared.get("expression_profile_id") != profile["profile_id"]
                    or prepared.get("expression_profile_sha256") != hashlib.sha256(_canonical(profile)).hexdigest()):
                raise ValueError("prepared expression profile changed")
    return job


def _expression_profile(value: Any, job: dict[str, Any]) -> dict[str, Any]:
    # Lazy import avoids a cycle: expression uses inheritance descriptors, while
    # ordinary inheritance and image-only jobs have no expression dependency.
    from genetics.expression import ExpressionProfile
    profile = ExpressionProfile.model_validate(value.model_dump(mode="json") if isinstance(value, ExpressionProfile) else value)
    individual = job["context"]["individual"]
    if (profile.individual_id != job["individual_id"] or profile.species_id != individual["species_id"]
            or profile.provenance.genome_sha256 != individual["genome_sha256"]
            or profile.provenance.context_sha256 != job["context_sha256"]):
        raise ValueError("expression profile must match individual, genome and generation context")
    serialized = profile.model_dump(mode="json")
    if len(_canonical(serialized)) > 16000:
        raise ValueError("expression profile exceeds generation context limit")
    return serialized


def prepare_generation(report: dict[str, Any], individual_id: str, *, expression_profile: Any = None) -> dict[str, Any]:
    """Resolve real parent assets and lock the exact request before model invocation."""
    job = _job(report, individual_id)
    profile = _expression_profile(expression_profile, job) if expression_profile is not None else None
    profile_hash = hashlib.sha256(_canonical(profile)).hexdigest() if profile is not None else None
    if job["prepared_request"] is not None:
        if job["prepared_request"].get("expression_profile_sha256") != profile_hash:
            raise ValueError("prepared individual has a different expression profile; reuse the exact locked profile")
        return copy.deepcopy(job["prepared_request"])
    if job["status"] != "pending":
        raise ValueError("completed individual cannot be prepared again")
    references = []
    for parent_id in job["context"]["individual"]["parents"] or []:
        parent = _job(report, parent_id)
        if parent["status"] != "completed":
            raise ValueError("generate and persist both parent images before child image generation")
        artifact = parent["result"]
        path = Path(artifact["asset_path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["asset_sha256"]:
            raise ValueError("parent image is missing or changed")
        references.append({"individual_id": parent_id, "asset_path": str(path), "asset_sha256": artifact["asset_sha256"]})
    conditioning = {"context": job["context"], "parent_visual_references": references}
    if profile is not None:
        conditioning["model_authored_expression_profile"] = profile
    prompt = ("Create one original Lumifin individual as pixel art for Pokemon: Aurora Frequency. "
              "Use the supplied real DNA reference as creative conditioning, the virtual diploid genotype as this individual's inherited identity, "
              "and supplied parent images for family resemblance. These data do not biologically predict morphology. "
              "Make one coherent, distinctive individual; do not display text, charts, DNA or statistics in the artwork. "
              "No fixed allele-to-color/body/stat rules. Keep family anatomy and a readable small sprite.\n"
              + json.dumps(conditioning, ensure_ascii=False, sort_keys=True))
    prepared = {"individual_id": individual_id, "context_sha256": job["context_sha256"],
                "parent_visual_references": references, "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
    if profile is not None:
        prepared.update({"expression_profile": profile, "expression_profile_id": profile["profile_id"],
                         "expression_profile_sha256": profile_hash})
    job["prepared_request"] = prepared
    return copy.deepcopy(prepared)


def supersede_prepared_generation(report: dict[str, Any], individual_id: str, *, reason: str,
                                  confirm_not_invoked: bool) -> None:
    """Explicitly revise an uninvoked request, retaining its full audit history.

The caller must know the external invocation never started. A pending job alone
does not establish that after a crash; completed visual identities are immutable.
"""
    job = _job(report, individual_id)
    if confirm_not_invoked is not True:
        raise ValueError("must explicitly confirm that no image model invocation started")
    if job["status"] != "pending" or job["result"] is not None or job["prepared_request"] is None:
        raise ValueError("only a prepared, uncompleted generation request can be superseded")
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 512:
        raise ValueError("a bounded explicit revision reason is required")
    history = job.setdefault("request_revisions", [])
    history.append({"revision": len(history) + 1, "reason": reason,
                    "operator_confirmation": "No image model invocation started for this request.",
                    "previous_request": copy.deepcopy(job["prepared_request"])})
    job["prepared_request"] = None


def complete_generation(report: dict[str, Any], individual_id: str, *, asset_path: str | Path,
                        model: str, tool: str = "imagegen") -> dict[str, Any]:
    """Register a real generated file, refusing to silently replace an identity."""
    job = _job(report, individual_id)
    if job["prepared_request"] is None:
        raise ValueError("prepare and persist the request before invoking the image model")
    if not isinstance(model, str) or not 1 <= len(model) <= 256 or not isinstance(tool, str) or not 1 <= len(tool) <= 128:
        raise ValueError("bounded model/tool provenance required")
    path = Path(asset_path).resolve()
    if not path.is_file():
        raise ValueError("generated asset must exist")
    asset = path.read_bytes()
    if not asset or len(asset) > 32 * 1024 * 1024:
        raise ValueError("generated asset must be nonempty and at most 32 MiB")
    if not (asset.startswith(b"\x89PNG\r\n\x1a\n") or asset.startswith(b"\xff\xd8\xff")
            or (asset.startswith(b"RIFF") and asset[8:12] == b"WEBP")):
        raise ValueError("generated asset must be a PNG, JPEG or WebP image")
    for reference in job["prepared_request"]["parent_visual_references"]:
        parent_path = Path(reference["asset_path"])
        if not parent_path.is_file() or hashlib.sha256(parent_path.read_bytes()).hexdigest() != reference["asset_sha256"]:
            raise ValueError("parent image changed after request preparation")
    result = {"individual_id": individual_id, "asset_path": str(path), "asset_sha256": hashlib.sha256(asset).hexdigest(),
              "model": model, "tool": tool, "context_sha256": job["context_sha256"],
              "prompt_sha256": job["prepared_request"]["prompt_sha256"],
              "parent_visual_references": copy.deepcopy(job["prepared_request"]["parent_visual_references"])}
    if job["prepared_request"].get("expression_profile") is not None:
        result.update({"expression_profile_id": job["prepared_request"]["expression_profile_id"],
                       "expression_profile_sha256": job["prepared_request"]["expression_profile_sha256"]})
    if job["status"] == "completed":
        if job["result"] != result:
            raise ValueError("individual already has persisted art; explicit new identity/version required to replace it")
        return copy.deepcopy(job["result"])
    if job["status"] != "pending":
        raise ValueError("unsupported generation status")
    job["result"] = result
    job["status"] = "completed"
    return copy.deepcopy(result)
