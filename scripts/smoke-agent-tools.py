#!/usr/bin/env python3
"""Run public agent fixtures with temporary data and all socket connects denied."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_agents.npc_quest_generator import NpcQuestQueue, export_candidate, request
from game_agents.schemas import GameEvent
from game_agents.service import LangGraphRuntime
from game_agents.visual_asset_tool import VisualAssetRuntime


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="helix-public-fixture-") as directory:
        root = Path(directory)
        with patch("socket.socket.connect", side_effect=AssertionError("Fixture attempted network access")):
            runtime = LangGraphRuntime(mode="fixture", memory_path=root / "memory.sqlite3")
            event = GameEvent(kind="npc_dialogue", save_id="synthetic-save", session="a" * 32 + "-0",
                              epoch=100, sequence=1, rom={"motivation": 1, "quest": 1})
            dialogue = runtime.invoke(event)
            assert dialogue["route"] == "npc"
            assert LangGraphRuntime(memory_path=root / "memory.sqlite3").invoke(event) == dialogue
            queue = NpcQuestQueue(root / "quest.sqlite3")
            try:
                queue.plan(request(27))
                candidate = queue.run()
                assert candidate["status"] == "draft" and candidate["runtime_action"] == "none"
                assert queue.run() == candidate
                export_candidate(candidate, root / "candidate.json")
            finally:
                queue.close()
            visual = VisualAssetRuntime(root / "assets")
            brief = ["An original blue watering pot with a wide handle."]
            first = visual.generate("item_icon", brief)
            second = VisualAssetRuntime(root / "assets").generate("item_icon", brief)
            assert first["status"] == "ready" and first["fixture"]
            assert first["native_admission"] == "none" and second["cache_hit"]
            assert {**first, "cache_hit": True} == second
        print(json.dumps({"network": "denied", "dialogue_restart_replay": "passed",
                          "quest_draft_and_replay": "passed", "visual_fixture_and_cache": "passed",
                          "native_admission": "none"}, indent=2))


if __name__ == "__main__":
    main()
