"""Synthetic public output-policy example; never included in provider context.

This lexical guard complements narrative review. It covers normalized names and
explicit EN/PT disclosures, not every paraphrase, cipher or semantic implication.
No rejected text is returned in an exception or substituted into a public reply.
"""
from __future__ import annotations

import re
import unicodedata

from companion.protocol import CHARMAP, ProtocolError, validate_encoded


class PublicLoreError(ProtocolError):
    """A public output must be discarded without reflecting its contents."""


_REJECTION = "Public content is unavailable."
# Synthetic public policy only: these are test markers, not game-world canon.
# Extend this immutable versioned source explicitly. NPC and visual producers
# hash this file, so a policy edit changes cache identities; no env override.
POLICY_VERSION = "public-output-synthetic-v1"
_RESERVED_TERMS = ("veilwarden",)
_RESTRICTED_SENTENCES = re.compile(
    r"\b(?:fixture secret is amber|segredo de teste e ambar)\b"
)


def validate_public_text(text: str) -> None:
    """Reject before lossy encoding/truncation, without changing accepted text."""
    if not isinstance(text, str):
        raise PublicLoreError(_REJECTION)
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized
                         if not unicodedata.combining(char)
                         and unicodedata.category(char) != "Cf")
    # Join punctuation/spacing and the common 0/1/4 substitutions solely for the
    # reserved name. Sentence words remain separated for precise disclosure rules.
    compact = "".join(char for char in normalized if char.isalnum()).translate(
        str.maketrans({"0": "o", "1": "i", "4": "a"}))
    words = " ".join("".join(char if char.isalnum() else " " for char in normalized).split())
    if any(term in compact for term in _RESERVED_TERMS) or _RESTRICTED_SENTENCES.search(words):
        raise PublicLoreError(_REJECTION)


def validate_public_value(value: object) -> None:
    """Check every string in an output tree, including nested labels and keys."""
    pending = [(value, 0)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 10000:
            raise PublicLoreError(_REJECTION)
        if isinstance(current, str):
            validate_public_text(current)
        elif isinstance(current, dict):
            pending.extend((part, depth + 1) for pair in current.items() for part in pair)
        elif isinstance(current, (list, tuple)):
            pending.extend((part, depth + 1) for part in current)


def validate_public_encoded(encoded: bytes) -> None:
    """Also inspect the exact supported characters that would reach the ROM."""
    validate_encoded(encoded)
    inverse = {value: char for char, value in CHARMAP.items()}
    rendered = "".join(" " if value in {0xFB, 0xFE} else inverse[value] for value in encoded)
    validate_public_text(rendered)
