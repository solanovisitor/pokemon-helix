"""Offline provenance and conditioning checks; no phenotype inference."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from genetics.reference import DATA_DIR, DESCRIPTOR_VERSION, build_manifest, load_reference, sequence_metrics


class GeneticsReferenceTests(unittest.TestCase):
    def test_pinned_ncbi_fragment_loads_offline_and_matches_exact_provenance(self):
        with patch("socket.socket", side_effect=AssertionError("reference loading must be offline")):
            reference = load_reference()
        self.assertEqual(reference.accession, "NC_002333.2")
        self.assertEqual(reference.metadata["organism"], "Danio rerio")
        self.assertEqual(reference.metadata["coordinates"], {
            "start": 1, "end": 1536, "coordinate_system": "1-based inclusive", "orientation": "+", "efetch_strand": 1,
        })
        self.assertEqual(len(reference.sequence), 1536)
        self.assertEqual(reference.checksum_sha256, "a6ec23c256a203fcf64a2f420d1ae5b7015aae3ae077f1d8013a2f68b61b9df1")
        self.assertEqual(sha256(reference.sequence.encode()).hexdigest(), reference.checksum_sha256)

    def test_descriptors_measure_bases_not_a_hash_seed_or_trait_weights(self):
        simple = sequence_metrics("ACGT" * 4)
        self.assertEqual(simple["gc_fraction"], 0.5)
        self.assertEqual(simple["normalized_base_composition_entropy"], 1)
        self.assertEqual(sequence_metrics("ATAT")["overlapping_dinucleotide_counts"]["AT"], 2)
        self.assertEqual(sequence_metrics("AAAA")["longest_homopolymer_bp"], 4)
        reference = load_reference()
        self.assertAlmostEqual(reference.features["whole_fragment"]["gc_fraction"], 571 / 1536)
        self.assertEqual(reference.features["whole_fragment"]["overlapping_dinucleotide_counts"], {"CG": 40, "AT": 166})
        self.assertEqual(reference.features["use"], "prompt_context_not_trait_weights")
        self.assertFalse({"pigmentation", "cold_tolerance", "aurora_sensitivity"} & reference.features.keys())

    def test_reference_windows_cover_the_fragment_without_coordinate_shift(self):
        windows = load_reference().features["windows"]
        self.assertEqual([(row["start"], row["end"]) for row in windows], [(1, 512), (513, 1024), (1025, 1536)])
        self.assertEqual(sum(row["metrics"]["length_bp"] for row in windows), 1536)

    def test_model_payload_contains_actual_reference_and_no_deterministic_phenotype(self):
        reference = load_reference()
        payload = reference.conditioning_payload()
        self.assertEqual(payload["sequence"], reference.sequence)
        self.assertEqual(payload["reference_metadata"]["reference_accession"], reference.accession)
        self.assertFalse(payload["deterministic_phenotype_mapping"])
        self.assertIn("parent visual references", payload["interpretation_rule"])
        json.dumps(payload)

    def test_committed_build_metadata_is_reproducible_from_local_fixture(self):
        recorded = json.loads((DATA_DIR / "reference-build.json").read_text())
        self.assertEqual(recorded, build_manifest(load_reference()))
        self.assertEqual(recorded["descriptor_version"], DESCRIPTOR_VERSION)

    def test_fasta_corruption_and_incorrect_coordinates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "reference"
            shutil.copytree(DATA_DIR, directory)
            metadata = json.loads((directory / "reference.json").read_text())
            fasta = directory / metadata["fasta_file"]
            original = fasta.read_bytes()
            fasta.write_bytes(original.replace(b"ACGG", b"TCGG", 1))
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                load_reference(directory / "reference.json")
            fasta.write_bytes(original)
            metadata["coordinates"]["start"] = 2
            (directory / "reference.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "accession and coordinates"):
                load_reference(directory / "reference.json")

    def test_ambiguous_or_unbounded_sequences_are_not_silently_reinterpreted(self):
        for sequence in ("", "ACGN", "acgt", "A" * 4097):
            with self.subTest(sequence=sequence[:8]), self.assertRaises(ValueError):
                sequence_metrics(sequence)


if __name__ == "__main__":
    unittest.main()
