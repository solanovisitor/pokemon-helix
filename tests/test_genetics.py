"""Inheritance and persisted generation contracts; no image/model/network calls."""
from __future__ import annotations

import base64
import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import random
import tempfile
import unittest

from genetics.engine import breed, complete_generation, founders, prepare_generation, run_experiment, supersede_prepared_generation
from genetics.models import Genotype, Individual, Mutation, SpeciesConfig

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jE2kAAAAASUVORK5CYII=")


class GenotypeTests(unittest.TestCase):
    def test_compact_roundtrip_owns_alleles_and_rejects_invalid_schema(self):
        source = [[i % 4 for i in range(32)], [(i + 1) % 4 for i in range(32)]]
        genotype = Genotype(source)
        source[0][0] = 3
        self.assertEqual(genotype.haplotypes[0][0], 0)
        self.assertEqual(len(genotype.pack()), 16)
        self.assertEqual(Genotype.from_dict(json.loads(json.dumps(genotype.to_dict()))), genotype)
        with self.assertRaises(FrozenInstanceError):
            genotype.haplotypes = ()
        for patch in ({"schema_version": 2}, {"loci": 31}, {"ploidy": True}, {"packed_hex": "00" * 15},
                      {"packed_hex": "AA" * 16}, {"extra": "not allowed"}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                Genotype.from_dict(genotype.to_dict() | patch)
        with self.assertRaises(ValueError):
            Genotype(([4] * 32, [0] * 32))

    def parents(self):
        return (Individual("a" * 24, "aurora_lumifin", 0, Genotype((tuple([0] * 32), tuple([1] * 32)))),
                Individual("b" * 24, "aurora_lumifin", 0, Genotype((tuple([2] * 32), tuple([3] * 32)))))

    def child(self, species, seed=7):
        return breed(*self.parents(), species=species, rng=random.Random(seed), generation=1, index=0, namespace="test")

    def test_parental_alleles_and_linked_groups_without_mutation(self):
        for seed in range(20):
            child = self.child(SpeciesConfig(mutation_rate=0, crossover_rate=0), seed)
            self.assertFalse(child.mutations)
            self.assertTrue(set(child.genotype.haplotypes[0]) <= {0, 1})
            self.assertTrue(set(child.genotype.haplotypes[1]) <= {2, 3})
            for haplotype in child.genotype.haplotypes:
                for start in range(0, 32, 8):
                    self.assertEqual(len(set(haplotype[start:start + 8])), 1)
        recombined = self.child(SpeciesConfig(mutation_rate=0, crossover_rate=1))
        for haplotype in recombined.genotype.haplotypes:
            for start in range(0, 32, 8):
                self.assertTrue(all(haplotype[locus] != haplotype[locus + 1] for locus in range(start, start + 7)))

    def test_mutation_bounds_and_records(self):
        child = self.child(SpeciesConfig(mutation_rate=1))
        self.assertEqual(len(child.mutations), 64)
        for mutation in child.mutations:
            self.assertNotEqual(mutation.before, mutation.after)
            self.assertIn(mutation.after, range(4))
            self.assertEqual(child.genotype.haplotypes[mutation.haplotype][mutation.locus], mutation.after)
        for rate in (-0.01, 1.01, float("nan"), True):
            with self.assertRaises(ValueError):
                SpeciesConfig(mutation_rate=rate)
        with self.assertRaises(ValueError):
            Mutation(2, 0, 0, 1)

    def test_no_selfing_cross_family_or_backward_generations(self):
        first, second = self.parents()
        for parents, generation in (((first, first), 1), ((first, replace(second, species_id="other_family")), 1), ((first, second), 0)):
            with self.assertRaises(ValueError):
                breed(*parents, species=SpeciesConfig(), rng=random.Random(0), generation=generation, index=0, namespace="test")


class PedigreeTests(unittest.TestCase):
    def test_ten_generations_64_individuals_replay_and_resolvable_genealogy(self):
        report = run_experiment(seed=91, generations=10, population_size=64)
        self.assertEqual(report, run_experiment(seed=91, generations=10, population_size=64))
        self.assertEqual(len(report["individuals"]), 704)
        known = {}
        for individual in report["individuals"]:
            self.assertNotIn(individual["id"], known)
            for parent in individual["parents"] or []:
                self.assertEqual(known[parent]["generation"], individual["generation"] - 1)
            known[individual["id"]] = individual
        self.assertEqual(report["history"][-1]["generation"], 10)
        self.assertNotEqual(founders(SpeciesConfig(), seed=91, population_size=2), founders(SpeciesConfig(), seed=92, population_size=2))
        self.assertGreater(sum(value["mutation_count"] for value in report["history"]), 0)

    def test_source_features_are_prompt_context_not_allele_or_phenotype_rules(self):
        original = SpeciesConfig()
        changed = replace(original, reference_features_json='{"gc_fraction":0.9}', reference_payload_json='{"sequence":"ACGT"}')
        left = run_experiment(species=original, population_size=2, generations=1)
        right = run_experiment(species=changed, population_size=2, generations=1)
        self.assertEqual(left["individuals"], right["individuals"])
        self.assertNotEqual(left["generation_requests"][0]["context_sha256"], right["generation_requests"][0]["context_sha256"])
        self.assertNotIn("phenotype", left["individuals"][0])
        self.assertNotIn("fitness", left["individuals"][0])

    def test_simulation_bounds(self):
        for arguments in ({"generations": 0}, {"generations": 101}, {"population_size": 1}, {"population_size": 257}, {"seed": -1}, {"seed": True}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                run_experiment(**arguments)


class GenerationIdentityTests(unittest.TestCase):
    def setUp(self):
        self.report = run_experiment(population_size=2, generations=1)
        self.parent_a, self.parent_b, self.child_a, self.child_b = [job["individual_id"] for job in self.report["generation_requests"]]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.asset = Path(self.temporary.name) / "parent.png"
        self.asset.write_bytes(PNG)

    def persist(self, identifier):
        request = prepare_generation(self.report, identifier)
        # Disk roundtrip represents the pre-inference request journal.
        self.report = json.loads(json.dumps(self.report))
        result = complete_generation(self.report, identifier, asset_path=self.asset, model="test-only-renderer")
        return request, result

    def test_children_require_actual_parent_assets_and_preserve_prompt_provenance(self):
        with self.assertRaisesRegex(ValueError, "both parent"):
            prepare_generation(self.report, self.child_a)
        self.persist(self.parent_a)
        self.persist(self.parent_b)
        request = prepare_generation(self.report, self.child_a)
        self.assertEqual([value["individual_id"] for value in request["parent_visual_references"]], [self.parent_a, self.parent_b])
        self.assertIn(self.report["individuals"][2]["genotype"]["packed_hex"], request["prompt"])
        self.assertIn("No fixed allele", request["prompt"])
        request["prompt"] = "caller mutation cannot change stored request"
        self.assertNotEqual(request, prepare_generation(self.report, self.child_a))

    def test_registration_is_idempotent_and_refuses_silent_regeneration(self):
        with self.assertRaisesRegex(ValueError, "prepare"):
            complete_generation(self.report, self.parent_a, asset_path=self.asset, model="test")
        _, result = self.persist(self.parent_a)
        self.assertEqual(result, complete_generation(self.report, self.parent_a, asset_path=self.asset, model="test-only-renderer"))
        with self.assertRaisesRegex(ValueError, "already has persisted"):
            complete_generation(self.report, self.parent_a, asset_path=self.asset, model="another-model")
        other = Path(self.temporary.name) / "different.png"
        other.write_bytes(PNG + b"different")
        with self.assertRaisesRegex(ValueError, "already has persisted"):
            complete_generation(self.report, self.parent_a, asset_path=other, model="test-only-renderer")

    def test_modified_parent_and_context_cannot_silently_condition_child(self):
        self.persist(self.parent_a)
        self.persist(self.parent_b)
        prepare_generation(self.report, self.child_a)
        self.asset.write_bytes(PNG + b"edited")
        with self.assertRaisesRegex(ValueError, "parent image changed"):
            complete_generation(self.report, self.child_a, asset_path=self.asset, model="test")
        altered = copy.deepcopy(self.report)
        altered["generation_requests"][0]["context"]["species"]["label"] = "changed"
        with self.assertRaisesRegex(ValueError, "context changed"):
            prepare_generation(altered, self.parent_a)
        self.report["generation_requests"][0]["prepared_request"]["prompt"] = "altered prompt"
        with self.assertRaisesRegex(ValueError, "request changed"):
            prepare_generation(self.report, self.parent_a)

    def test_model_expression_is_bound_before_render_and_cannot_change_on_resume(self):
        from genetics.expression import fixture_expression
        from genetics.reference import load_reference
        self.report = run_experiment(species=SpeciesConfig.from_reference(load_reference()), population_size=2, generations=1)
        job = self.report["generation_requests"][0]
        profile = fixture_expression(job)
        prepared = prepare_generation(self.report, self.parent_a, expression_profile=profile)
        self.assertEqual(prepared["expression_profile_id"], profile.profile_id)
        self.assertIn(profile.profile_id, prepared["prompt"])
        self.assertEqual(prepared, prepare_generation(self.report, self.parent_a, expression_profile=profile.model_dump(mode="json")))
        with self.assertRaisesRegex(ValueError, "different expression profile"):
            prepare_generation(self.report, self.parent_a)
        other = fixture_expression(self.report["generation_requests"][1])
        with self.assertRaisesRegex(ValueError, "must match individual"):
            prepare_generation(self.report, self.parent_a, expression_profile=other)
        result = complete_generation(self.report, self.parent_a, asset_path=self.asset, model="test-only-renderer")
        self.assertEqual(result["expression_profile_sha256"], prepared["expression_profile_sha256"])

    def test_explicit_uninvoked_request_revision_keeps_prior_prompt_and_frozen_context(self):
        prepared = prepare_generation(self.report, self.parent_a)
        original_context = copy.deepcopy(self.report["generation_requests"][0]["context"])
        with self.assertRaisesRegex(ValueError, "explicitly confirm"):
            supersede_prepared_generation(self.report, self.parent_a, reason="Add model-generated expression", confirm_not_invoked=False)
        supersede_prepared_generation(self.report, self.parent_a, reason="User requested graded model trait profile", confirm_not_invoked=True)
        job = self.report["generation_requests"][0]
        self.assertEqual(job["request_revisions"][0]["previous_request"], prepared)
        self.assertEqual(job["context"], original_context)
        self.assertIsNone(job["prepared_request"])
        self.persist(self.parent_a)
        with self.assertRaisesRegex(ValueError, "only a prepared, uncompleted"):
            supersede_prepared_generation(self.report, self.parent_a, reason="Cannot replace completed art", confirm_not_invoked=True)


if __name__ == "__main__":
    unittest.main()
