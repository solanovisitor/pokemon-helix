"""Bounded synthetic indicator assay; no individual DNA or save is interpreted.

The Hill response is a phenomenological teaching model with fictional units and
parameters, not a molecular prediction. Predictions affect only feedback. The
caller owns durable jobs, stale-state rejection, native effects and receipts.
"""
from __future__ import annotations

import hashlib
import json
import re

SCHEMA = "helix-lab-assay-v1"
MODEL = "helix-indicator-hill-v1"
CULTURE = "nanomon-indicator-v1"
MAX_REQUEST_BYTES = 768
MAX_RESULT_BYTES = 1536
_BINDING_KEYS = {"request_id", "save_lineage", "individual_id", "snapshot_sha256", "quest_revision"}
_CONDITIONS = {"sheltered": (1, 50, "stable"), "exposed": (2, 500, "sensitive")}


def canonical(value: object) -> bytes:
    """Frozen ASCII JSON codec for commitments; not a signature or ownership ID."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def indicator_signal(stimulus: int) -> int:
    """10 + round_half_up(80*s²/(500²+s²)), bounded to integer stimulus 0..1000.

    h=2 is an effective response-shape parameter, not a claim of two binding
    sites. This evaluates equilibrium directly: no real-time wait or RNG.
    """
    if type(stimulus) is not int or not 0 <= stimulus <= 1000:
        raise ValueError("stimulus must be an integer from 0 through 1000")
    denominator = 250_000 + stimulus * stimulus
    return 10 + (80 * stimulus * stimulus + denominator // 2) // denominator


def _bindings(value: dict) -> dict:
    if type(value) is not dict or set(value) != _BINDING_KEYS:
        raise ValueError("unsupported assay bindings")
    for key in ("request_id", "save_lineage", "individual_id"):
        if type(value[key]) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", value[key]) is None:
            raise ValueError(f"invalid {key}")
    if (type(value["snapshot_sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value["snapshot_sha256"]) is None):
        raise ValueError("invalid snapshot_sha256")
    if type(value["quest_revision"]) is not int or not 0 <= value["quest_revision"] <= 65535:
        raise ValueError("invalid quest_revision")
    return dict(value)


def simulate(condition: str, prediction: str, bindings: dict) -> dict:
    """Return a complete immutable-by-commitment observation, never game effects.

    Both protocols use the same synthetic culture, medium and perturbation
    (-50, 0, +50); only the environmental operating point differs. ``span`` is
    max minus min over controlled probes, not statistical variance/uncertainty.
    ``snapshot_sha256`` binds the caller's frozen state without reading its DNA.
    A job must retain the entire result, not merely its model name or hash.
    """
    if type(condition) is not str or condition not in _CONDITIONS:
        raise ValueError("unsupported assay condition")
    if type(prediction) is not str or prediction not in ("stable", "sensitive"):
        raise ValueError("unsupported assay prediction")
    request = {"schema": SCHEMA, "model": MODEL, "condition": condition,
               "prediction": prediction, "bindings": _bindings(bindings)}
    encoded = canonical(request)
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("assay request exceeds byte bound")
    code, baseline, interpretation = _CONDITIONS[condition]
    stimuli = [baseline - 50, baseline, baseline + 50]
    values = [indicator_signal(value) for value in stimuli]
    result = {"schema": SCHEMA, "model": MODEL, "culture": CULTURE,
              "request": request, "input_sha256": hashlib.sha256(encoded).hexdigest(),
              "result_code": code, "stimuli": stimuli, "values": values,
              "signal": values[1], "span": values[-1] - values[0],
              "control": indicator_signal(0), "interpretation": interpretation,
              "prediction_match": prediction == interpretation}
    result["result_sha256"] = hashlib.sha256(canonical(result)).hexdigest()
    if len(canonical(result)) > MAX_RESULT_BYTES:
        raise ValueError("assay result exceeds byte bound")
    return result


def verify_result(result: dict, condition: str, prediction: str, bindings: dict) -> None:
    """Recompute against the *current expected* binding, refusing stale/extra data.

    Hashes alone do not authorize a result. This deliberately rejects even a
    correctly rehashed tampering, unknown version, or numeric bool substitution.
    Cancellation and deadlines remain the caller's job before this function.
    """
    if type(result) is not dict:
        raise ValueError("invalid assay result")
    try:
        encoded = canonical(result)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("invalid assay result encoding") from exc
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("assay result exceeds byte bound")
    if encoded != canonical(simulate(condition, prediction, bindings)):
        raise ValueError("assay result is stale, altered, or unsupported")
