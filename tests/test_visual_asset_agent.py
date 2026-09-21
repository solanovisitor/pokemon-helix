"""Real SDK executes the optional visual capability with an offline model."""
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(importlib.util.find_spec("deepagents"), "optional generation extra not installed")
class VisualAgentTests(unittest.TestCase):
    def test_real_agent_calls_visual_tool_then_returns_validated_asset_reference(self):
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import AIMessage, ToolMessage
        from langchain_core.outputs import ChatGeneration, ChatResult
        from pydantic import BaseModel, PrivateAttr
        from game_agents.deepagents_adapter import build_candidate_agent
        from game_agents.visual_asset_tool import VisualAssetRuntime

        class VisualCandidate(BaseModel):
            asset_id: str
            native_admission: str

        class OfflineModel(ChatOpenAI):
            _calls: int = PrivateAttr(default=0)
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                self._calls += 1
                if self._calls == 1:
                    call = {"name": "generate_visual_asset", "id": "visual-request",
                            "args": {"asset_type": "item_icon", "prompts": ["An original brass field lens."]}}
                else:
                    tool_message = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
                    result = json.loads(tool_message.content)
                    if result["status"] != "ready" or result["scope"] != "validated_asset_only":
                        raise AssertionError("tool must return its actual validated result")
                    call = {"name": "VisualCandidate", "id": "visual-candidate", "args": {
                        "asset_id": result["asset_id"], "native_admission": result["native_admission"]}}
                return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])

        with tempfile.TemporaryDirectory() as temp, \
                patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            runtime = VisualAssetRuntime(temp)
            model = OfflineModel(model="helix-visual-fixture", api_key="fixture-unused", max_retries=0)
            graph = build_candidate_agent(context={"public_brief": "One original field tool."},
                schema=VisualCandidate, system_prompt="Prepare a public asset candidate only.",
                chat_model=model, visual_assets=runtime)
            self.assertEqual(set(graph.get_graph().nodes["tools"].data.tools_by_name),
                             {"read_file", "read_approved_context", "generate_visual_asset"})
            result = graph.invoke({"messages": [{"role": "user", "content": "Prepare a field lens."}]},
                                  config={"recursion_limit": 16})
            candidate = result["structured_response"]
            manifest = json.loads(next(Path(temp).glob("*/manifest.json")).read_text())
            self.assertEqual(candidate.asset_id, manifest["asset_id"])
            self.assertEqual(candidate.native_admission, "none")
            self.assertEqual(model._calls, 2)
            self.assertEqual(runtime.generate("item_icon", ["An original brass field lens."])["asset_id"],
                             candidate.asset_id)


if __name__ == "__main__":
    unittest.main()
