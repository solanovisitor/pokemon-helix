"""Verified, offline DNA reference context for generative individual artwork.

These descriptors are model input. They do not calculate a phenotype, stat,
colour, cold tolerance, or Aurora sensitivity.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re

DATA_DIR = Path(__file__).resolve().parents[1] / "examples/genetics"
DESCRIPTOR_VERSION = "aurora-reference-descriptors-v1"
MAX_REFERENCE_BASES = 4096


def sequence_metrics(sequence: str) -> dict:
    """Describe actual base composition and overlapping motifs without trait labels."""
    if not sequence or len(sequence) > MAX_REFERENCE_BASES or set(sequence) - set("ACGT"):
        raise ValueError("reference context requires 1..4096 unambiguous uppercase DNA bases")
    counts = Counter(sequence)
    fractions = {base: counts[base] / len(sequence) for base in "ACGT"}
    entropy = -sum(frequency * math.log2(frequency) for frequency in fractions.values() if frequency)
    motifs = {motif: sum(sequence.startswith(motif, index) for index in range(len(sequence) - len(motif) + 1))
              for motif in ("CG", "AT")}
    return {
        "length_bp": len(sequence),
        "base_counts": {base: counts[base] for base in "ACGT"},
        "base_fractions": fractions,
        "gc_fraction": fractions["G"] + fractions["C"],
        "base_composition_entropy_bits": entropy,
        "normalized_base_composition_entropy": entropy / 2,
        "overlapping_dinucleotide_counts": motifs,
        "overlapping_dinucleotide_fractions": {motif: count / max(1, len(sequence) - 1) for motif, count in motifs.items()},
        "longest_homopolymer_bp": max(len(run.group()) for run in re.finditer(r"([ACGT])\1*", sequence)),
    }


@dataclass(frozen=True)
class DNAReference:
    accession: str
    sequence: str
    checksum_sha256: str
    transform_version: str
    features: dict
    metadata: dict

    def conditioning_payload(self) -> dict:
        """Actual bounded bases, provenance and descriptors for a model prompt."""
        return {
            "role": "nonhuman_reference_context_only",
            "reference_metadata": self.metadata,
            "sequence": self.sequence,
            "sequence_descriptors": self.features,
            "interpretation_rule": (
                "Use this verified nonhuman DNA fragment as creative conditioning alongside the fictional individual genotype "
                "and parent visual references. It does not specify real or game traits. Generate an individual design, "
                "then persist that chosen visual asset for the individual; do not claim a biologically predicted phenotype."
            ),
            "deterministic_phenotype_mapping": False,
        }


def load_reference(metadata_path: str | Path | None = None) -> DNAReference:
    """Load and verify the committed fixture. This function never accesses the network."""
    metadata_path = Path(metadata_path) if metadata_path is not None else DATA_DIR / "reference.json"
    metadata = json.loads(metadata_path.read_text())
    if metadata.get("schema_version") != 1 or metadata.get("transform_version") != DESCRIPTOR_VERSION:
        raise ValueError("unsupported reference metadata or descriptor version")
    coordinates = metadata["coordinates"]
    if coordinates.get("coordinate_system") != "1-based inclusive" or coordinates.get("orientation") != "+" or coordinates.get("efetch_strand") != 1:
        raise ValueError("unsupported reference coordinate convention")
    start, end = coordinates["start"], coordinates["end"]
    if type(start) is not int or type(end) is not int or start < 1 or not 1 <= end - start + 1 <= MAX_REFERENCE_BASES:
        raise ValueError("invalid reference interval")
    fasta_name = metadata["fasta_file"]
    if not isinstance(fasta_name, str) or Path(fasta_name).name != fasta_name:
        raise ValueError("reference FASTA must be a file next to its metadata")
    raw = (metadata_path.parent / fasta_name).read_bytes()
    if len(raw) > 10000 or sha256(raw).hexdigest() != metadata["fasta_sha256"]:
        raise ValueError("reference FASTA checksum mismatch")
    lines = raw.decode("ascii").splitlines()
    expected_header = f">{metadata['reference_accession']}:{start}-{end} "
    if not lines or not lines[0].startswith(expected_header) or any(line.startswith(">") for line in lines[1:]):
        raise ValueError("reference FASTA record does not match accession and coordinates")
    if lines[0][1:] != metadata["record_title"] or metadata["organism"] not in lines[0]:
        raise ValueError("reference title or organism mismatch")
    sequence = "".join(line.strip() for line in lines[1:] if line.strip())
    if len(sequence) != end - start + 1 or len(sequence) != metadata["sequence_length"]:
        raise ValueError("reference sequence length mismatch")
    checksum = sha256(sequence.encode("ascii")).hexdigest()
    if checksum != metadata["sequence_sha256"]:
        raise ValueError("reference sequence checksum mismatch")
    record_name = metadata["source_genbank_file"]
    if not isinstance(record_name, str) or Path(record_name).name != record_name:
        raise ValueError("GenBank provenance must be a file next to its metadata")
    record = (metadata_path.parent / record_name).read_bytes()
    if sha256(record).hexdigest() != metadata["source_genbank_sha256"]:
        raise ValueError("GenBank provenance checksum mismatch")
    metrics = sequence_metrics(sequence)
    windows = []
    for offset in range(0, len(sequence), 512):
        fragment = sequence[offset:offset + 512]
        windows.append({"start": start + offset, "end": start + offset + len(fragment) - 1,
                        "orientation": "+", "metrics": sequence_metrics(fragment)})
    features = {"whole_fragment": metrics, "windows": windows,
                "descriptor_version": DESCRIPTOR_VERSION, "use": "prompt_context_not_trait_weights"}
    return DNAReference(metadata["reference_accession"], sequence, checksum, DESCRIPTOR_VERSION, features, metadata)


def build_manifest(reference: DNAReference) -> dict:
    """A stable audit record; identical local inputs produce identical JSON data."""
    return {
        "schema_version": 1,
        "descriptor_version": reference.transform_version,
        "accession": reference.accession,
        "sequence_sha256": reference.checksum_sha256,
        "fasta_sha256": reference.metadata["fasta_sha256"],
        "genbank_sha256": reference.metadata["source_genbank_sha256"],
        "coordinates": reference.metadata["coordinates"],
        "source_fasta_url": reference.metadata["source_fasta_url"],
        "retrieved_at_utc": reference.metadata["retrieved_at_utc"],
        "features": reference.features,
        "deterministic_phenotype_mapping": False,
        "output_contract": "Model-conditioning data, not creature stats, colours, sprites or phenotype predictions.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output", type=Path, help="Write the verified descriptor manifest")
    args = parser.parse_args()
    report = build_manifest(load_reference(args.metadata))
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
        print(f"Verified reference context: {args.output}")
    else:
        print(serialized, end="")


if __name__ == "__main__":
    main()
