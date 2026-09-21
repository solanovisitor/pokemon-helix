"""Explicit, bounded live planning; private context never becomes output or a trace.

This adapter is deliberately independent of the dialogue graph and its tracing.
It performs one non-streaming request, with no retries, redirects or tools. The
caller owns durable claims and unknown-outcome recovery for the daily cycle.
"""
from __future__ import annotations

from datetime import date
from http.client import HTTPException
import json
import re
from typing import Callable
from urllib.request import HTTPRedirectHandler, Request, build_opener

from companion.protocol import ProtocolError
from companion.openrouter_policy import openrouter_options


MAX_REQUEST_BYTES = 16_384
MAX_RESPONSE_BYTES = 32_768
MAX_PRIVATE_CANON_BYTES = 8_192
TIMEOUT_SECONDS = 30
MAX_TOKENS = 1_200
_OBSERVATIONS = frozenset({"active_adventures", "completed_adventures", "births",
                           "encounters", "discovered_loci"})
_REQUEST_FIELDS = frozenset({"schema_version", "cycle", "observations", "previous_plan",
                             "output_schema", "private_canon"})


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must not forward this private body or its bearer credential.
        return None


urlopen = build_opener(_NoRedirect()).open


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _json_loads(value: str | bytes) -> object:
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")


def _validated_request(request: dict) -> dict:
    from .world_planner import WorldPlan

    try:
        if type(request) is not dict or set(request) != _REQUEST_FIELDS:
            raise ValueError
        if type(request["schema_version"]) is not int or request["schema_version"] != 1:
            raise ValueError
        cycle = request["cycle"]
        if not isinstance(cycle, str) or date.fromisoformat(cycle).isoformat() != cycle:
            raise ValueError
        observations = request["observations"]
        if type(observations) is not dict or set(observations) != _OBSERVATIONS:
            raise ValueError
        if any(type(value) is not int or not 0 <= value <= 1_000_000_000
               for value in observations.values()):
            raise ValueError
        previous = request["previous_plan"]
        if previous is not None:
            previous = WorldPlan.model_validate(previous, strict=True).model_dump()
        canon = request["private_canon"]
        if canon is not None and (type(canon) is not dict
                                  or len(_json_bytes(canon)) > MAX_PRIVATE_CANON_BYTES):
            raise ValueError
        schema = WorldPlan.model_json_schema()
        if request["output_schema"] != schema:
            raise ValueError
        # Reconstruct the allowlist: no arbitrary player text, identity or paths.
        return {"schema_version": 1, "cycle": cycle, "observations": dict(observations),
                "previous_plan": previous, "output_schema": schema, "private_canon": canon}
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ProtocolError("invalid world planning input") from None


def live_world_provider(*, key: str, model: str) -> Callable[[dict], dict]:
    """Build an opt-in provider. Neither credentials nor a model come from env.

    Live use sends the selected private canon to the explicitly selected remote
    provider. It is never included in public output, exceptions or local traces.
    A model/endpoint without structured-output support fails instead of falling
    back to a different provider or silently weakening validation.
    """
    if (not isinstance(key, str) or re.fullmatch(r"[\x21-\x7e]{1,4096}", key) is None
            or not isinstance(model, str)
            or re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", model) is None):
        raise ProtocolError("world planning requires an explicit provider key and model")

    def generate(request: dict) -> dict:
        from .world_planner import WorldPlan

        selected = _validated_request(request)
        try:
            body = _json_bytes({
                "model": model, "max_tokens": MAX_TOKENS, "temperature": 0.4,
                "stream": False,
                **openrouter_options(model),
                "response_format": {"type": "json_schema", "json_schema": {
                    "name": "daily_world_plan", "strict": True,
                    "schema": selected["output_schema"]}},
                "messages": [
                    {"role": "system", "content": (
                        "Choose a gentle daily direction for a long-lived creature adventure. "
                        "Return ONLY the supplied JSON schema's enum choices, with no prose, "
                        "new fields, commands, tools, rewards, code or game-state mutations. "
                        "Use aggregate observations and the previous plan for continuity. "
                        "Change at most two of story_focus, ecology, encounter, learning and pace "
                        "from the previous plan in one daily cycle. "
                        "Private canon is confidential author context: never quote or expose it. "
                        "It may inspire the allowed choices but cannot extend the schema. "
                        "Preserve player agency, existing adventures, companions and history. "
                        "Do not infer individual player facts from aggregate counts.")},
                    {"role": "user", "content": _json_bytes(selected).decode("utf-8")},
                ],
            })
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise ProtocolError("invalid world planning input") from None
        if len(body) > MAX_REQUEST_BYTES:
            raise ProtocolError("oversized world planning input")
        http = Request("https://openrouter.ai/api/v1/chat/completions", data=body,
                       headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                       method="POST")
        try:
            with urlopen(http, timeout=TIMEOUT_SECONDS) as response:
                data = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, HTTPException, ValueError):
            # Upstream errors can carry response bodies. Do not retain a cause.
            raise ProtocolError("world planning provider request failed") from None
        if len(data) > MAX_RESPONSE_BYTES:
            raise ProtocolError("oversized world planning response")
        try:
            parsed = _json_loads(data)
            if not isinstance(parsed, dict):
                raise ValueError
            choices = parsed["choices"]
            if not isinstance(choices, list) or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if (choice.get("finish_reason") != "stop" or message.get("role") != "assistant"
                    or message.get("tool_calls") not in (None, [])
                    or message.get("function_call") is not None
                    or message.get("refusal") is not None):
                raise ValueError
            content = message["content"]
            if not isinstance(content, str) or not content:
                raise ValueError
            plan = _json_loads(content)
            if (not isinstance(plan, dict) or type(plan.get("schema_version")) is not int
                    or plan["schema_version"] != 1):
                raise ValueError
            return WorldPlan.model_validate(plan, strict=True).model_dump()
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
            # Pydantic/JSON errors include rejected values; never surface them.
            raise ProtocolError("invalid world planning response") from None

    return generate
