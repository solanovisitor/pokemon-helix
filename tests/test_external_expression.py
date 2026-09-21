"""Explicit external model provenance and crash-safe queue acceptance, no live calls."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from genetics.breeding import BreedingError, BreedingStore
from genetics.edits import EditStore
from genetics.engine import run_experiment
from genetics.expression import (ExpressionProfile, accept_external_expression, fixture_expression,
                                 prepare_external_expression)
from genetics.models import SpeciesConfig
from genetics.reference import load_reference
from test_roster import png


class ExternalExpressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = run_experiment(species=SpeciesConfig.from_reference(load_reference()), population_size=2, generations=1)["generation_requests"]
        cls.profiles = [fixture_expression(j) for j in cls.jobs[:2]]
        cls.body = cls.profiles[0].expression.model_dump(mode="json")
        cls.body["scores"]["curiosity"] = 79
        cls.body["rationale"] = "Externally authored test body for software verification. This is creative interpretation, not a DNA prediction."

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = BreedingStore(self.root / "store")
        image = self.root / "image.png"
        image.write_bytes(png())
        self.parents = [self.store.register_parent(j["context"], p, image, image_sha256=sha256(image.read_bytes()).hexdigest())
                        for j, p in zip(self.jobs, self.profiles)]
        self.store.enqueue("external", self.parents, seed=12)

    def test_prepared_context_paths_and_prompt_hash_bind_external_response_without_network(self):
        with patch("genetics.expression.build_opener") as network:
            reserved = self.store.start_external_expression("external", tool="codex", model="test-model")
            prepared = reserved["prepared"]
            self.assertNotIn("base64", str(prepared))
            self.assertEqual(len(prepared["image_paths"]), 2)
            self.assertNotIn(str(self.root), str(prepared["data"]))
            result = self.store.accept_external_expression("external", attempt_token=reserved["attempt"], body=self.body)
            self.assertEqual(result["state"], "pending_art")
            network.assert_not_called()
        saved = self.store.inspect("external")
        p = saved["profile"]["provenance"]
        self.assertEqual(p["mode"], "external_model")
        self.assertEqual(p["external_tool"], "codex")
        self.assertEqual(p["model"], "test-model")
        self.assertEqual(p["prompt_sha256"], prepared["prompt_sha256"])
        self.assertEqual(self.store.accept_external_expression("external", attempt_token=reserved["attempt"], body=self.body), result)
        altered = deepcopy(self.body)
        altered["scores"]["curiosity"] = 80
        with self.assertRaisesRegex(BreedingError, "cannot be replaced"):
            self.store.accept_external_expression("external", attempt_token=reserved["attempt"], body=altered)

    def test_crash_after_response_is_recoverable_with_no_second_external_invocation(self):
        reserved = self.store.start_external_expression("external", tool="codex", model="test-model")
        with patch.object(self.store, "recover_expression", side_effect=RuntimeError("simulated crash")):
            with self.assertRaises(RuntimeError):
                self.store.accept_external_expression("external", attempt_token=reserved["attempt"], body=self.body)
        reopened = BreedingStore(self.store.directory)
        with self.assertRaisesRegex(BreedingError, "unknown"):
            reopened.start_external_expression("external", tool="codex", model="test-model")
        self.assertEqual(reopened.recover_expression("external")["state"], "pending_art")
        self.assertEqual(len(reopened.inspect("external")["attempts"]), 1)

    def test_rejects_wrong_attempt_extra_fields_score_bounds_and_stale_prompt(self):
        reserved = self.store.start_external_expression("external", tool="codex", model="test-model")
        with self.assertRaises(BreedingError):
            self.store.accept_external_expression("external", attempt_token="0" * 32, body=self.body)
        for bad_score in (101, -1, True, 50.0):
            body = deepcopy(self.body)
            body["scores"]["curiosity"] = bad_score
            with self.assertRaises(ValueError):
                self.store.accept_external_expression("external", attempt_token=reserved["attempt"], body=body)
        body = {**self.body, "unsupported_action": "change-game"}
        with self.assertRaises(ValueError):
            self.store.accept_external_expression("external", attempt_token=reserved["attempt"], body=body)
        self.assertEqual(self.store.status("external")["state"], "expression_outcome_unknown")
        request = self.jobs[0]["context"]
        with self.assertRaisesRegex(ValueError, "prompt"):
            accept_external_expression(self.body, request, tool="codex", model="test-model", prompt_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "bounded"):
            accept_external_expression({"rationale": "x" * 32769}, request, tool="codex", model="test-model", prompt_sha256="0" * 64)

    def test_existing_profile_hashes_unchanged_and_external_profiles_can_accept_edit(self):
        self.assertNotIn("external_tool", self.profiles[0].model_dump()["provenance"])
        # Synthetic profiles are the only historical-input fixtures in this export.
        for profile in self.profiles:
            reopened = ExpressionProfile.model_validate_json(profile.model_dump_json())
            self.assertEqual(reopened.profile_id, profile.profile_id)
        edits = EditStore(self.store)
        first = self.jobs[0]["context"]["individual"]
        preview = edits.preview(self.parents[0], scope="somatic", copy=0, locus=0, allele=(first["alleles"][0][0] + 1) % 4)
        inputs = edits.inputs(preview["revision_id"])
        request = inputs.pop("context")
        prepared = prepare_external_expression(request, **inputs)
        profile = accept_external_expression(self.body, request, tool="codex", model="test-model",
                                             prompt_sha256=prepared["prompt_sha256"], **inputs)
        self.assertEqual(edits.accept_profile(preview["revision_id"], profile)["state"], "pending_art")
