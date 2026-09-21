"""Fixture-only public LangGraph CLI entrypoint; live use is explicit in the library."""
from __future__ import annotations

import os

from game_agents.builder import DEFAULT_MEMORY, create_graph

# A contributor's inherited tracing configuration must not export fixture state.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
graph = create_graph(mode="fixture", memory_path=os.getenv("GAME_AGENT_MEMORY_PATH", str(DEFAULT_MEMORY)))
