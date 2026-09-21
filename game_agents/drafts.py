"""Typed authoring proposals. Nothing here writes game files or applies effects."""
from __future__ import annotations

import json
import re
from urllib.request import Request as HttpRequest, urlopen

from companion.protocol import ProtocolError
from companion.openrouter_policy import openrouter_options
from .schemas import DRAFT_SCHEMAS, GameEvent


def fixture_draft(event: GameEvent) -> dict:
    if event.language == "pt-BR":
        common = {"status": "draft", "runtime_action": "none", "title": "O sinal azul de Littleroot",
                  "rationale": "Proposta para revisao humana a partir do briefing: " + event.brief[:300]}
        if event.kind == "world_draft":
            return {**common, "kind": event.kind, "premise": "Pequenos sinais luminosos conectam historias dos moradores.",
                    "hooks": ["Ivo registra relatos sem afirmar a origem do sinal.", "O jogador escolhe investigar por curiosidade ou solidariedade."]}
        if event.kind == "scene_draft":
            return {**common, "kind": event.kind, "location": "LittlerootTown", "objective": "Investigar uma pista e retornar a Ivo.",
                    "beats": ["Ivo apresenta a pergunta.", "O jogador observa uma pista opcional.", "Ivo reconhece a escolha registrada pela ROM."],
                    "dialogue": ["Voce tambem percebeu aquela luz?", "Podemos observar juntos, com calma."]}
        if event.kind == "map_draft":
            return {**common, "kind": event.kind, "width": 8, "height": 6,
                    "rows": ["########", "#S.....#", "#......#", "#......#", "#......#", "########"],
                    "objects": [{"kind": "npc", "x": 2, "y": 2, "label": "Ivo"},
                                {"kind": "clue", "x": 5, "y": 3, "label": "Pista azul"}]}
        raise ProtocolError("unsupported authoring task")
    common = {"status": "draft", "runtime_action": "none", "title": "The blue signal of Littleroot",
              "rationale": "Human-reviewed proposal based on the brief: " + event.brief[:300]}
    if event.kind == "world_draft":
        return {**common, "kind": event.kind, "premise": "Small luminous signals connect the residents' stories.",
                "hooks": ["Ivo records reports without claiming to know the signal's origin.", "The player chooses to investigate out of curiosity or a wish to help."]}
    if event.kind == "scene_draft":
        return {**common, "kind": event.kind, "location": "LittlerootTown", "objective": "Investigate a clue and return to Ivo.",
                "beats": ["Ivo introduces the mystery.", "The player observes an optional clue.", "Ivo acknowledges the choice saved by the ROM."],
                "dialogue": ["Did you notice that light too?", "We can watch it together."]}
    if event.kind == "map_draft":
        return {**common, "kind": event.kind, "width": 8, "height": 6,
                "rows": ["########", "#S.....#", "#......#", "#......#", "#......#", "########"],
                "objects": [{"kind": "npc", "x": 2, "y": 2, "label": "Ivo"},
                            {"kind": "clue", "x": 5, "y": 3, "label": "Blue clue"}]}
    raise ProtocolError("unsupported authoring task")


def live_draft(event: GameEvent, *, key: str, model: str, world_context: dict | None = None) -> dict:
    if not key or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", model):
        raise ProtocolError("draft generation requires explicit provider key and model")
    schema = DRAFT_SCHEMAS[event.kind].model_json_schema()
    body = json.dumps({"model": model, "max_tokens": 1600, "temperature": 0.5, "stream": False,
        **openrouter_options(model),
        "messages": [
            {"role": "system", "content": "You are an authoring assistant for a gentle GBA mystery. Return ONLY one JSON object matching the supplied schema. The output is a human-reviewed draft, never an executed game action. Do not include code, commands, file paths, rewards, pointers, or claims that the ROM has changed. Keep text concise and understandable to a preteen in the requested language, English by default. For map sketches use small dimensions and reachable objects. Optional world guidance suggests future possibilities only: current ROM facts take precedence, accepted quests remain unchanged, and the player chooses their actions. Residents believe in Abad and stories of his opposite Giava; describe this as their belief, without inventing cosmological explanations."},
            {"role": "user", "content": json.dumps({"task": event.kind, "brief": event.brief, "language": event.language,
                "authoritative_rom_snapshot": event.rom.model_dump(), "json_schema": schema,
                "world_guidance": world_context})},
        ]}).encode()
    request = HttpRequest("https://openrouter.ai/api/v1/chat/completions", data=body,
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urlopen(request, timeout=15) as response:
        data = response.read(32769)
    if len(data) > 32768:
        raise ProtocolError("oversized draft response")
    try:
        choice = json.loads(data)["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("tool_calls"):
            raise ProtocolError("incomplete or executable draft response")
        content = json.loads(choice["message"]["content"])
        return DRAFT_SCHEMAS[event.kind].model_validate(content).model_dump()
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ProtocolError("invalid typed authoring proposal") from error
