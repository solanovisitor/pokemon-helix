"""The public boundary shared by the coordinator and any future agent engine."""
from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from companion.protocol import CHARMAP, Request, encode_text, validate_encoded
from .public_lore import validate_public_encoded, validate_public_text, validate_public_value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ROMState(StrictModel):
    source: Literal["rom"] = "rom"
    motivation: int = Field(ge=0, le=2)
    quest: int = Field(ge=0, le=3)
    map_id: Literal["LittlerootTown", "HelixLaboratory"] = "LittlerootTown"

    @model_validator(mode="after")
    def consistent_choice(self) -> ROMState:
        if self.quest > 0 and self.motivation == 0:
            raise ValueError("quest requires the ROM's saved motivation")
        return self


class SelectedTrainerContext(StrictModel):
    trainer_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    profile_revision: int = Field(ge=1)
    declared_profile: dict[str, str | list[str]]

    @model_validator(mode="after")
    def selected_only(self) -> SelectedTrainerContext:
        allowed = {"display_name", "pronouns", "appearance", "motivation", "values", "boundaries", "soul"}
        if set(self.declared_profile) - allowed or len(json.dumps(self.declared_profile)) > 6000:
            raise ValueError("unsupported or oversized selected trainer context")
        return self


class GameEvent(StrictModel):
    language: Literal["en", "pt-BR"] = "en"
    schema_version: int = Field(default=1, ge=1, le=1)
    origin: Literal["local_host"] = "local_host"
    kind: Literal["npc_dialogue", "world_draft", "scene_draft", "map_draft"]
    world_id: str = Field(default="local-world", pattern=r"^[A-Za-z0-9_-]{1,80}$")
    player_id: str = Field(default="local-player", pattern=r"^[A-Za-z0-9_-]{1,80}$")
    save_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    npc_id: Literal["ivo", "reception", "geneticist", "nursery"] = "ivo"
    session: str = Field(pattern=r"^[a-f0-9]{16,64}-[0-9]{1,10}$")
    epoch: int = Field(ge=1, le=0xFFFFFFFF)
    sequence: int = Field(ge=1, le=0xFFFFFFFF)
    rom: ROMState
    brief: str = Field(default="", max_length=600)
    trainer_context: SelectedTrainerContext | None = None
    player_utterance: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def scope(self) -> GameEvent:
        if self.kind == "npc_dialogue" and self.brief:
            raise ValueError("runtime dialogue accepts structured ROM facts only")
        if self.kind != "npc_dialogue" and not self.brief.strip():
            raise ValueError("an authoring draft requires a brief")
        return self

    def request(self) -> Request:
        from .personas import NPC_IDS
        npc = next(key for key, value in NPC_IDS.items() if value == self.npc_id)
        return Request(self.session, self.epoch, self.sequence, npc, self.rom.motivation, self.rom.quest)

    @property
    def event_key(self) -> str:
        return f"{self.kind}:{self.session}:{self.epoch}:{self.sequence}"

    @property
    def memory_scope(self) -> str:
        # Colons cannot occur in these validated identifiers. Future network adapters
        # must derive all three IDs from authenticated ownership, not client claims.
        return f"{self.world_id}:{self.player_id}:{self.save_id}"


class PublicOutput(StrictModel):
    model_config = ConfigDict(hide_input_in_errors=True, revalidate_instances="always")

    @model_validator(mode="before")
    @classmethod
    def public_content(cls, value):
        validate_public_value(value.model_dump() if isinstance(value, BaseModel) else value)
        return value


class Dialogue(PublicOutput):
    action: Literal["dialogue"] = "dialogue"
    npc_id: Literal["ivo", "reception", "geneticist", "nursery"] = "ivo"
    text: str = Field(min_length=1, max_length=123)
    encoded_hex: str = Field(pattern=r"^[0-9a-f]+$", max_length=478)
    delivery: Literal["generated_unconfirmed"] = "generated_unconfirmed"

    @model_validator(mode="after")
    def bounded_encoding(self) -> Dialogue:
        encoded = bytes.fromhex(self.encoded_hex)
        validate_encoded(encoded)
        validate_public_encoded(encoded)
        if encode_text(self.text) != encoded:
            raise ValueError("text and encoded dialogue differ")
        return self


def make_dialogue(text: str, *, npc_id: str = "ivo") -> Dialogue:
    validate_public_text(text)
    encoded = encode_text(text)
    validate_public_encoded(encoded)
    inverse = {value: key for key, value in CHARMAP.items()}
    rendered = "".join(" " if value in {0xFB, 0xFE} else inverse[value] for value in encoded)
    return Dialogue(npc_id=npc_id, text=rendered, encoded_hex=encoded.hex())


class DraftBase(PublicOutput):
    status: Literal["draft"] = "draft"
    runtime_action: Literal["none"] = "none"
    title: str = Field(min_length=1, max_length=80)
    rationale: str = Field(min_length=1, max_length=500)


class WorldDraft(DraftBase):
    kind: Literal["world_draft"] = "world_draft"
    premise: str = Field(min_length=1, max_length=500)
    hooks: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(min_length=1, max_length=5)


class SceneDraft(DraftBase):
    kind: Literal["scene_draft"] = "scene_draft"
    location: Literal["LittlerootTown"] = "LittlerootTown"
    objective: str = Field(min_length=1, max_length=240)
    beats: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(min_length=1, max_length=5)
    dialogue: list[Annotated[str, Field(min_length=1, max_length=120)]] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def bounded_dialogue(self) -> SceneDraft:
        for line in self.dialogue:
            make_dialogue(line)
        return self


class MapObject(PublicOutput):
    kind: Literal["npc", "sign", "clue"]
    x: int = Field(ge=0, le=63)
    y: int = Field(ge=0, le=63)
    label: str = Field(min_length=1, max_length=60)


class MapDraft(DraftBase):
    kind: Literal["map_draft"] = "map_draft"
    width: int = Field(ge=4, le=64)
    height: int = Field(ge=4, le=64)
    # A topology sketch, not Porymap data, tile art, event scripts, or a compiled map.
    rows: list[str] = Field(min_length=4, max_length=64)
    objects: list[MapObject] = Field(max_length=12)

    @model_validator(mode="after")
    def topology(self) -> MapDraft:
        if len(self.rows) != self.height or any(len(row) != self.width for row in self.rows):
            raise ValueError("map dimensions and row lengths disagree")
        if any(set(row) - set(".#S") for row in self.rows) or sum(row.count("S") for row in self.rows) != 1:
            raise ValueError("map needs one spawn S and only . # S topology symbols")
        occupied = set()
        for obj in self.objects:
            if obj.x >= self.width or obj.y >= self.height or self.rows[obj.y][obj.x] != ".":
                raise ValueError("object must occupy a walkable tile within the map")
            if (obj.x, obj.y) in occupied:
                raise ValueError("map objects cannot overlap")
            occupied.add((obj.x, obj.y))
        spawn = next((x, y) for y, row in enumerate(self.rows) for x, value in enumerate(row) if value == "S")
        reachable, pending = {spawn}, [spawn]
        while pending:
            x, y = pending.pop()
            for adjacent in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                ax, ay = adjacent
                if (0 <= ax < self.width and 0 <= ay < self.height and self.rows[ay][ax] != "#"
                        and adjacent not in reachable):
                    reachable.add(adjacent)
                    pending.append(adjacent)
        if not occupied <= reachable:
            raise ValueError("all proposed objects must be reachable from the spawn")
        return self


DRAFT_SCHEMAS = {"world_draft": WorldDraft, "scene_draft": SceneDraft, "map_draft": MapDraft}
