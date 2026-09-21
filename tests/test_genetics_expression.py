from __future__ import annotations

import base64
from copy import deepcopy
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from genetics.engine import run_experiment
from genetics.expression import (ExpressionBody, ExpressionGenerationError, ExpressionProfile,
                                 TRAIT_ANCHORS, fixture_expression, generate_expression, save_expression)
from genetics.models import SpeciesConfig
from genetics.reference import load_reference


class GeneticsExpressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.jobs = run_experiment(species=SpeciesConfig.from_reference(load_reference()),
                                  population_size=4, generations=1)["generation_requests"]
        cls.parents = [fixture_expression(job) for job in cls.jobs[:2]]

    def provider(self, body, *, finish_reason="stop", extra=None):
        message = {"content": json.dumps(body)}
        message.update(extra or {})
        return io.BytesIO(json.dumps({"choices": [{"finish_reason": finish_reason, "message": message}]}).encode())

    def test_fixture_is_explicit_and_not_a_genotype_score_formula(self):
        a, b = self.parents
        self.assertNotEqual(a.provenance.genome_sha256, b.provenance.genome_sha256)
        self.assertEqual(a.expression.scores, b.expression.scores)
        self.assertEqual(a.provenance.mode, "fixture")
        self.assertIn("not DNA inference", a.expression.rationale)
        self.assertEqual(set(a.expression.scores.model_dump()), set(TRAIT_ANCHORS))
        self.assertEqual(len(TRAIT_ANCHORS), 16)

    def test_scores_reject_float_bool_nan_out_of_range_extra_or_missing(self):
        body = self.parents[0].expression.model_dump()
        for value in (-1, 101, 1.0, True, float("nan"), float("inf"), "50"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                modified = deepcopy(body)
                modified["scores"]["body_size"] = value
                ExpressionBody.model_validate(modified)
        for edit in (lambda b: b.update(action="give_reward"),
                     lambda b: b["scores"].update(attack=99),
                     lambda b: b["scores"].pop("curiosity")):
            modified = deepcopy(body)
            edit(modified)
            with self.assertRaises(ValidationError):
                ExpressionBody.model_validate(modified)

    def test_child_requires_matching_parent_profiles_and_binds_their_ids(self):
        for parents in ([], [self.parents[0]], list(reversed(self.parents))):
            with self.assertRaises(ExpressionGenerationError):
                fixture_expression(self.jobs[2], parent_profiles=parents)
        child = fixture_expression(self.jobs[2], parent_profiles=self.parents)
        self.assertEqual(child.provenance.parent_profile_ids, [p.profile_id for p in self.parents])
        self.assertEqual(child.provenance.parent_individual_ids, self.jobs[2]["context"]["individual"]["parents"])
        self.assertEqual(child.provenance.visual_context, "profiles_only")
        self.assertNotEqual(child.profile_id, self.parents[0].profile_id)

    def test_stale_context_genome_and_reference_are_rejected(self):
        changed_job = deepcopy(self.jobs[0])
        changed_job["context"]["individual"]["generation"] += 1
        with self.assertRaisesRegex(ExpressionGenerationError, "context was changed"):
            fixture_expression(changed_job)
        for section, field, value in (("individual", "genome_sha256", "0" * 64),
                                      ("individual", "variation", {})):
            context = deepcopy(self.jobs[0]["context"])
            context[section][field] = value
            with self.assertRaises(ExpressionGenerationError):
                fixture_expression(context)
        context = deepcopy(self.jobs[0]["context"])
        context["species"]["reference_context"]["sequence"] = "A" * 1536
        with self.assertRaisesRegex(ExpressionGenerationError, "verified real reference"):
            fixture_expression(context)

    def test_prompt_has_actual_bases_and_descriptors_separate_from_scores_no_key(self):
        authored = self.parents[0].expression.model_dump()
        authored["scores"]["curiosity"] = 77
        with patch("genetics.expression.build_opener") as opener:
            opener.return_value.open.return_value = self.provider(authored)
            result = generate_expression(self.jobs[0], key="SECRET_TEST_ONLY", model="test/model")
        request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        prompt = payload["messages"][1]["content"]
        self.assertNotIn("SECRET_TEST_ONLY", prompt)
        self.assertNotIn("SECRET_TEST_ONLY", result.model_dump_json())
        self.assertEqual(request.get_header("Authorization"), "Bearer SECRET_TEST_ONLY")
        self.assertIn(load_reference().sequence, prompt)
        self.assertIn("base_composition_entropy_bits", prompt)
        self.assertIn("differences_from_virtual_reference", prompt)
        self.assertEqual(payload["max_tokens"], 1500)
        self.assertEqual(result.expression.scores.curiosity, 77)
        self.assertEqual(result.provenance.mode, "openrouter")
        self.assertEqual(result.provenance.genome_sha256, self.jobs[0]["context"]["individual"]["genome_sha256"])

    def test_provider_truncation_tools_oversize_and_invalid_actions_are_rejected(self):
        body = self.parents[0].expression.model_dump()
        cases = [self.provider(body, finish_reason="length"), self.provider(body, extra={"tool_calls": [{"name": "x"}]}),
                 self.provider({**body, "action": "give_item"}), io.BytesIO(b"x" * 32769), io.BytesIO(b"not json"),
                 io.BytesIO(b'{"choices":[{"message":[],"finish_reason":"stop"}]}'),
                 io.BytesIO(b'{"choices":[{"message":{},"finish_reason":{}}]}')]
        for response in cases:
            with self.subTest(response=response), patch("genetics.expression.build_opener") as opener:
                opener.return_value.open.return_value = response
                with self.assertRaises(ExpressionGenerationError):
                    generate_expression(self.jobs[0], key="TEST", model="test/model")

    def test_provider_diagnostics_identify_schema_location_without_values(self):
        body = self.parents[0].expression.model_dump()
        body["scores"]["curiosity"] = "DO_NOT_ECHO_THIS_VALUE"
        body["PRIVATE_UNKNOWN_FIELD"] = "DO_NOT_ECHO_THIS_VALUE"
        with patch("genetics.expression.build_opener") as opener:
            opener.return_value.open.return_value = self.provider(body)
            with self.assertRaises(ExpressionGenerationError) as failure:
                generate_expression(self.jobs[0], key="PRIVATE_KEY", model="test/model")
        message = str(failure.exception)
        self.assertIn("scores.curiosity:int_type", message)
        self.assertIn("[unknown-field]:extra_forbidden", message)
        for private in ("DO_NOT_ECHO_THIS_VALUE", "PRIVATE_UNKNOWN_FIELD", "PRIVATE_KEY"):
            self.assertNotIn(private, message)
        with patch("genetics.expression.build_opener") as opener:
            opener.return_value.open.return_value = self.provider(body, finish_reason="length")
            with self.assertRaisesRegex(ExpressionGenerationError, "did not finish: length"):
                generate_expression(self.jobs[0], key="TEST", model="test/model")

    def test_parent_pixels_are_verified_and_sent_separately_without_local_paths(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfN8AAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private-parent.png"
            path.write_bytes(png)
            images = [{"individual_id": p.individual_id, "asset_path": str(path), "asset_sha256": sha256(png).hexdigest()} for p in self.parents]
            with patch("genetics.expression.build_opener") as opener:
                opener.return_value.open.return_value = self.provider(self.parents[0].expression.model_dump())
                result = generate_expression(self.jobs[2], key="TEST", model="test/vision", parent_profiles=self.parents, parent_images=images)
            payload = json.loads(opener.return_value.open.call_args.args[0].data)
            content = payload["messages"][1]["content"]
            self.assertEqual(sum(part["type"] == "image_url" for part in content), 2)
            self.assertNotIn(tmp, json.dumps(payload))
            self.assertEqual(result.provenance.visual_context, "profiles_and_pixels")
            images[0]["asset_sha256"] = "0" * 64
            with self.assertRaisesRegex(ExpressionGenerationError, "checksum mismatch"):
                fixture_expression(self.jobs[2], parent_profiles=self.parents, parent_images=images)

    def test_profiles_are_hash_bound_and_persisted_once(self):
        profile = self.parents[0]
        modified = profile.model_dump()
        modified["expression"]["scores"]["body_size"] = 70
        with self.assertRaisesRegex(ValidationError, "checksum mismatch"):
            ExpressionProfile.model_validate(modified)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            save_expression(profile, path)
            save_expression(profile, path)
            with self.assertRaisesRegex(ExpressionGenerationError, "cannot be replaced"):
                save_expression(self.parents[1], path)
            self.assertEqual(ExpressionProfile.model_validate_json(path.read_text()), profile)

    def test_founder_profile_can_be_grounded_in_its_own_verified_pixels(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jfN8AAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "founder.png"
            path.write_bytes(png)
            image = {"individual_id": self.parents[0].individual_id, "asset_path": str(path), "asset_sha256": sha256(png).hexdigest()}
            with patch("genetics.expression.build_opener") as opener:
                opener.return_value.open.return_value = self.provider(self.parents[0].expression.model_dump())
                result = generate_expression(self.jobs[0], key="TEST", model="test/vision", individual_image=image)
            messages = json.loads(opener.return_value.open.call_args.args[0].data)["messages"]
            self.assertIn("do not redesign it", messages[0]["content"])
            self.assertEqual(sum(p["type"] == "image_url" for p in messages[1]["content"]), 1)
            self.assertIn("current individual", messages[1]["content"][1]["text"])
            self.assertEqual(result.provenance.individual_image.asset_sha256, image["asset_sha256"])
            self.assertEqual(result.provenance.visual_context, "none")  # No observed parent images.
            image["individual_id"] = self.parents[1].individual_id
            with self.assertRaisesRegex(ExpressionGenerationError, "current individual"):
                fixture_expression(self.jobs[0], individual_image=image)

    def test_invalid_timeout_and_model_fail_before_network(self):
        with patch("genetics.expression.build_opener") as opener:
            for timeout in (0, 31, True, float("inf"), float("nan")):
                with self.assertRaises(ExpressionGenerationError):
                    generate_expression(self.jobs[0], key="TEST", model="test/model", timeout=timeout)
            for model in ("", "https://bad host", "x" * 161):
                with self.assertRaises(ExpressionGenerationError):
                    generate_expression(self.jobs[0], key="TEST", model=model)
            opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
