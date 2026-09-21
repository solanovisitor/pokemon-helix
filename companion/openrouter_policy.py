"""Pure, explicit OpenRouter routing options; no discovery or network on import.

The exact low-effort IDs were checked against the public OpenRouter model
catalog on 2026-09-21. Unsupported/unknown IDs receive no reasoning override.
These routing preferences are not evidence of measured end-to-end latency.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re


POLICY_VERSION = "helix-openrouter-latency-v1"
LOW_EFFORT_MODELS = frozenset({"z-ai/glm-5.3", "z-ai/glm-5.3-flash"})


def openrouter_options(model: str) -> dict:
    """Return a fresh request/ChatOpenAI extra_body fragment for an explicit ID."""
    if not isinstance(model, str) or re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", model) is None:
        raise ValueError("an explicit supported model identifier is required")
    options = {"provider": {"sort": "latency", "require_parameters": True, "allow_fallbacks": False}}
    if model in LOW_EFFORT_MODELS:
        options["reasoning"] = {"effort": "low"}
    return options


def openrouter_policy_fingerprint(model: str) -> str:
    """Bind effective routing to a durable job without copying provider secrets."""
    value = {"version": POLICY_VERSION, "model": model, "options": openrouter_options(model)}
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
