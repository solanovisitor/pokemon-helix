"""Engine-independent dialogue contract and the local LangGraph implementation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from langsmith import tracing_context

from companion.protocol import ProtocolError, Request, parse_request
from .builder import DEFAULT_MEMORY, create_graph
from .schemas import Dialogue, GameEvent


class DialogueRuntime(Protocol):
    def dialogue(self, request: Request, *, save_id: str) -> str: ...


class LangGraphRuntime:
    def __init__(self, *, mode: str = "fixture", key: str | None = None, model: str | None = None,
                 memory_path: str | Path = DEFAULT_MEMORY, provider=None, draft_provider=None,
                 language: str = "en", world_store=None):
        self.mode = mode
        if language not in {"en", "pt-BR"}:
            raise ProtocolError("unsupported dialogue language")
        self.language = language
        self.graph = create_graph(mode=mode, key=key, model=model, memory_path=memory_path,
                                  provider=provider, draft_provider=draft_provider, world_store=world_store)

    def invoke(self, event: GameEvent | dict) -> dict:
        event = GameEvent.model_validate(event)
        enabled = (self.mode == "openrouter" and os.getenv("GBA_LANGSMITH_TRACING", "").lower() == "true"
                   and bool(os.getenv("LANGSMITH_API_KEY"))
                   and not event.trainer_context and not event.player_utterance)
        # A fixture run cannot emit traces because another project enabled tracing.
        with tracing_context(enabled=enabled, project_name="gba-ai-bridge"):
            return self.graph.invoke({"event": event.model_dump()})

    def dialogue(self, request: Request, *, save_id: str, trainer_context: dict | None = None,
                 player_utterance: str = "") -> str:
        _, request = parse_request(request.wire())
        from .personas import NPC_IDS
        event = GameEvent(kind="npc_dialogue", language=self.language, save_id=save_id, session=request.session,
                          epoch=request.epoch, sequence=request.request,
                          npc_id=NPC_IDS[request.npc], trainer_context=trainer_context,
                          player_id=trainer_context["trainer_id"] if trainer_context else "local-player",
                          player_utterance=player_utterance,
                          rom={"motivation": request.motivation, "quest": request.quest,
                               "map_id": "LittlerootTown" if request.npc == 1 else "HelixLaboratory"})
        result = self.invoke(event)
        if result["route"] != "npc":
            raise ProtocolError("only dialogue can cross the runtime bridge")
        return Dialogue.model_validate(result["result"]).text


def invoke_dialogue(request: Request, *, mode: str = "fixture", key: str | None = None,
                    model: str | None = None, save_id: str, memory_path: str | Path = DEFAULT_MEMORY,
                    language: str = "en", world_store=None, trainer_context: dict | None = None,
                    player_utterance: str = "") -> str:
    """Companion entry point. Returns validated four-line dialogue, never a game action."""
    return LangGraphRuntime(mode=mode, key=key, model=model, memory_path=memory_path,
                            language=language, world_store=world_store).dialogue(
                                request, save_id=save_id, trainer_context=trainer_context,
                                player_utterance=player_utterance)
