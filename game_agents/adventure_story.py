"""Versioned, bounded North Pool grammar; accepted graphs are immutable content.

This is authored deterministic story generation, not live model output. Only the
compiled variant can execute effects. The 256-bit seed selects a causal grammar;
accepted companion signal expression biases compatible grammar selection but
never makes progression depend on an unavailable expression or network call.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GENERATOR_VERSION = "north-pool-v1"


class StoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: Literal["accept", "reed", "stone", "encounter", "conclude"]
    kind: Literal["objective", "discovery", "double_encounter", "conclusion"]
    location: Literal["OldaleTown:9,13", "Route103:12,7", "Route103:7,7", "Route103:18,8"]
    requires: tuple[str, ...] = ()
    effect: Literal["accept_chapter", "hear_reed", "read_stone", "win_pair_battle", "reward_once"]


class StoryGraph(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    generator_version: Literal["north-pool-v1"] = GENERATOR_VERSION
    seed_commitment: str = Field(pattern=r"^[a-f0-9]{64}$")
    primer_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,95}$")
    signal_score: int = Field(ge=0, le=15)
    compiled_variant: Literal[1, 2]
    title: Literal["The Reed's Answer", "Two Banks, One Nursery"]
    nodes: tuple[StoryNode, ...]

    @model_validator(mode="after")
    def supported_solvable_graph(self) -> StoryGraph:
        expected = _nodes(self.compiled_variant)
        # A merely solvable but unimplemented graph is unsafe to accept: the
        # compiler must realize exactly these versioned causal dependencies.
        if self.nodes != expected:
            raise ValueError("graph does not match a supported compiled causal grammar")
        title = "The Reed's Answer" if self.compiled_variant == 1 else "Two Banks, One Nursery"
        if self.title != title:
            raise ValueError("title and compiled variant disagree")
        return self

    def structure_fingerprint(self) -> str:
        """Exclude identity, title and wording: count actual effects/dependencies."""
        normalized = [{"kind": node.kind, "location": node.location,
                       "requires": sorted(node.requires), "effect": node.effect}
                      for node in sorted(self.nodes, key=lambda node: node.node_id)]
        return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def available(self, completed: set[str]) -> tuple[str, ...]:
        if completed - {node.node_id for node in self.nodes}:
            raise ValueError("unknown completed story node")
        return tuple(node.node_id for node in self.nodes
                     if node.node_id not in completed and set(node.requires) <= completed)


def _nodes(variant: int) -> tuple[StoryNode, ...]:
    accept = StoryNode(node_id="accept", kind="objective", location="OldaleTown:9,13", effect="accept_chapter")
    reed = StoryNode(node_id="reed", kind="discovery", location="Route103:12,7",
                     requires=("accept",) if variant == 1 else ("encounter",), effect="hear_reed")
    battle = StoryNode(node_id="encounter", kind="double_encounter", location="Route103:18,8",
                       requires=("reed",) if variant == 1 else ("accept",), effect="win_pair_battle")
    conclusion = StoryNode(node_id="conclude", kind="conclusion", location="OldaleTown:9,13",
                           requires=("encounter",) if variant == 1 else ("reed", "stone"), effect="reward_once")
    if variant == 1:
        return accept, reed, battle, conclusion
    stone = StoryNode(node_id="stone", kind="discovery", location="Route103:7,7",
                      requires=("encounter",), effect="read_stone")
    return accept, battle, reed, stone, conclusion


def generate_story(adventure_seed: bytes, *, primer_id: str, signal_score: int = 8) -> StoryGraph:
    """Select grammar from full seed and bounded accepted signal expression.

    The finite grammar intentionally has two structural outcomes. It provides
    material variation, never a claim that every seed has a globally unique plot.
    Callers retain candidates and explicitly accept one rather than rerolling an
    accepted story. Identical inputs are independent of worker/request ordering.
    """
    if not isinstance(adventure_seed, bytes) or len(adventure_seed) != 32:
        raise ValueError("adventure seed must contain exactly 256 bits")
    if type(signal_score) is not int or not 0 <= signal_score <= 15:
        raise ValueError("signal expression must be an integer from 0 to 15")
    if not isinstance(primer_id, str):
        raise ValueError("primer ID must be a string")
    context = json.dumps({"primer_id": primer_id, "signal_band": signal_score // 4}, sort_keys=True).encode()
    stream = hmac.new(adventure_seed, b"aurora/story/north-pool-v1\0" + context, hashlib.sha256).digest()
    variant = 1 + (stream[0] & 1)
    return StoryGraph(seed_commitment=hashlib.sha256(adventure_seed).hexdigest(), primer_id=primer_id,
                      signal_score=signal_score, compiled_variant=variant,
                      title="The Reed's Answer" if variant == 1 else "Two Banks, One Nursery", nodes=_nodes(variant))


def accept_story(path: Path, graph: StoryGraph) -> StoryGraph:
    """Commit once, or return an identical accepted graph on an idempotent retry."""
    graph = StoryGraph.model_validate(graph.model_dump())
    payload = graph.model_dump_json(indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Publish a complete fsynced file without replacing another worker's output.
    # An interrupted writer can leave a temporary file, never a partial accepted
    # graph. Atomic no-replace linking also makes concurrent identical retries safe.
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".story-", delete=False) as stream:
            temporary = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            retained = StoryGraph.model_validate_json(path.read_text())
            if retained != graph:
                raise ValueError("accepted story is immutable; use a new adventure")
            return retained
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return graph
    finally:
        if temporary is not None:
            os.unlink(temporary)
