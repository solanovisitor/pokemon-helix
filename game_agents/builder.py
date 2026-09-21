"""The same LangGraph coordinator backs fixture play, live play, and authoring."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from companion import providers
from .drafts import fixture_draft, live_draft
from .memory import MemoryStore
from .personas import PERSONAS
from .schemas import DRAFT_SCHEMAS, Dialogue, GameEvent, make_dialogue

DEFAULT_MEMORY = Path(__file__).resolve().parents[1] / ".local/agents/memory.sqlite3"


class AgentInput(TypedDict):
    event: dict


class AgentOutput(TypedDict):
    route: str
    result: dict


class AgentState(AgentInput, AgentOutput, total=False):
    memory: list[dict]
    cached: str | None
    raw: str | dict | None
    operational_context: dict


DialogueProvider = Callable[[GameEvent, dict, list[dict]], str]
DraftProvider = Callable[[GameEvent], dict]


def create_graph(*, mode: str = "fixture", key: str | None = None, model: str | None = None,
                 memory_path: str | Path = DEFAULT_MEMORY, provider: DialogueProvider | None = None,
                 draft_provider: DraftProvider | None = None, world_store=None):
    if mode not in {"fixture", "openrouter"}:
        raise ValueError("unsupported agent mode")
    if mode == "openrouter" and (not key or not model):
        raise ValueError("live agent runtime requires explicit key and model")
    store = MemoryStore(memory_path)

    def validate_event(state: AgentState) -> dict:
        event = GameEvent.model_validate(state["event"])
        # Clear private channels when the server reuses a checkpointed graph thread.
        return {"event": event.model_dump(), "memory": [], "cached": None, "raw": None,
                "result": {}, "operational_context": {}}

    def coordinator(state: AgentState) -> dict:
        kind = state["event"]["kind"]
        route = {"npc_dialogue": "npc", "world_draft": "world", "scene_draft": "scene", "map_draft": "map"}[kind]
        context = {}
        if world_store is not None:
            event = GameEvent.model_validate(state["event"])
            if event.world_id != world_store.world_id:
                raise ValueError("event does not belong to the configured world")
            # Bind context to this exact local adventure/save scope. Client input
            # cannot choose a plan, impersonate a planner or carry private canon.
            adventure = hashlib.sha256(event.memory_scope.encode()).hexdigest()
            context = {
                "active_adventure": world_store.project_context(role=route, adventure_id=adventure),
                "current_world": world_store.project_context(role=route),
            }
        return {"route": route, "operational_context": context}

    def load_memory(state: AgentState) -> dict:
        memory = store.load(GameEvent.model_validate(state["event"]))
        return {"memory": memory["records"], "cached": memory["cached"]}

    def npc_dialogue(state: AgentState) -> dict:
        event = GameEvent.model_validate(state["event"])
        if state["cached"] is not None:
            return {"raw": state["cached"]}
        persona = deepcopy(PERSONAS[event.npc_id])
        if state["operational_context"]:
            persona["world_guidance"] = state["operational_context"]
        if event.trainer_context:
            # Provider needs declared prose, never the trainer's global identity.
            persona["selected_trainer_context"] = {
                "profile_revision": event.trainer_context.profile_revision,
                "declared_profile": event.trainer_context.declared_profile,
            }
        if provider is not None:
            return {"raw": provider(event, persona, state["memory"])}
        if mode == "fixture":
            text = providers.fixture(event.request(), language=event.language)
            selected = event.trainer_context.declared_profile if event.trainer_context else {}
            if selected.get("display_name"):
                text = str(selected["display_name"])[:24] + ", " + text
            if state["memory"]:
                text = ("You're back! " if event.language == "en" else "Voce voltou! ") + text
        else:
            text = providers.openrouter(event.request(), key=key, model=model, language=event.language,
                                        context={"persona": persona, "memory": state["memory"]},
                                        player_utterance=event.player_utterance)
        return {"raw": text}

    def design_draft(state: AgentState) -> dict:
        event = GameEvent.model_validate(state["event"])
        if draft_provider is not None:
            draft = draft_provider(event)
        elif mode == "fixture":
            draft = fixture_draft(event)
        else:
            draft = live_draft(event, key=key, model=model,
                               world_context=state["operational_context"] or None)
        return {"raw": draft}

    def validate_output(state: AgentState) -> dict:
        if state["route"] == "npc":
            output = make_dialogue(state["raw"], npc_id=state["event"]["npc_id"])
        else:
            output = DRAFT_SCHEMAS[state["event"]["kind"]].model_validate(state["raw"])
        return {"result": output.model_dump()}

    def remember(state: AgentState) -> dict:
        dialogue = Dialogue.model_validate(state["result"])
        text = store.remember(GameEvent.model_validate(state["event"]), dialogue.text)
        return {"result": make_dialogue(text, npc_id=state["event"]["npc_id"]).model_dump()}

    builder = StateGraph(AgentState, input_schema=AgentInput, output_schema=AgentOutput)
    builder.add_node("validate_event", validate_event)
    builder.add_node("coordinator", coordinator)
    builder.add_node("load_npc_memory", load_memory)
    builder.add_node("npc_dialogue", npc_dialogue)
    builder.add_node("world_designer", design_draft)
    builder.add_node("scene_writer", design_draft)
    builder.add_node("map_designer", design_draft)
    builder.add_node("validate_output", validate_output)
    builder.add_node("remember_generated_dialogue", remember)
    builder.add_edge(START, "validate_event")
    builder.add_edge("validate_event", "coordinator")
    builder.add_conditional_edges("coordinator", lambda state: state["route"],
                                  {"npc": "load_npc_memory", "world": "world_designer", "scene": "scene_writer", "map": "map_designer"})
    builder.add_edge("load_npc_memory", "npc_dialogue")
    for node in ("npc_dialogue", "world_designer", "scene_writer", "map_designer"):
        builder.add_edge(node, "validate_output")
    builder.add_conditional_edges("validate_output", lambda state: state["route"] == "npc",
                                  {True: "remember_generated_dialogue", False: END})
    builder.add_edge("remember_generated_dialogue", END)
    # LangGraph API owns graph checkpoints. NPC memory is a separate scoped SQLite store.
    return builder.compile(name="gba_game_coordinator")
