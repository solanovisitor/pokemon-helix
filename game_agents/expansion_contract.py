"""Bounded declarative world fixture. No model output is executable code.

The converter emits a new map only. The named quest actions bind reviewed
native handlers in helix_expansion.c; this is not a general quest compiler.
"""
from __future__ import annotations

from collections import deque
from hashlib import sha256
import json
import re
from pathlib import Path
import struct

ACTIONS = {
    "accept": ("lia", {"unseen"}, {"remember_acceptance"}),
    "inspect_bed": ("bed", {"accepted"}, {"remember_bed_clue"}),
    "inspect_mouth": ("mouth", {"accepted"}, {"remember_mouth_clue"}),
    "observe": ("board", {"both_clues", "companion_ready", "prepared"}, {"remember_method"}),
    "screen_bed": ("board", {"tested", "companion_ready"}, {"remember_bed_screen"}),
    "screen_mouth": ("board", {"tested", "companion_ready"}, {"remember_mouth_screen"}),
    "review": ("board", {"resolved"}, set()),
}
SCRIPTS = {
    "HelixExpansion_EventScript_Lia", "HelixExpansion_EventScript_Tom",
    "HelixExpansion_EventScript_Return", "HelixExpansion_EventScript_Bed",
    "HelixExpansion_EventScript_Mouth", "HelixExpansion_EventScript_Board",
}

def require(value, message):
    if not value:
        raise ValueError(message)


def integer(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, label)


def point(value, width, height):
    require(isinstance(value, list) and len(value) == 2, "coordinate pair")
    integer(value[0], 0, width - 1, "x out of bounds")
    integer(value[1], 0, height - 1, "y out of bounds")
    return tuple(value)


def walkable(block):
    return block & 0xC00 == 0 and block >> 12 in (0, 3, 4)


def reachable(grid, spawn, occupied):
    width, height = len(grid[0]), len(grid)
    seen = {spawn}
    queue = deque([spawn])
    while queue:
        x, y = queue.popleft()
        for node in ((x-1, y), (x+1, y), (x, y-1), (x, y+1)):
            nx, ny = node
            if 0 <= nx < width and 0 <= ny < height and node not in occupied and node not in seen and walkable(grid[ny][nx]):
                seen.add(node)
                queue.append(node)
    return seen


def validate_expansion(data):
    require(set(data) == {"schema_version", "expansion_id", "revision", "status", "map", "entry", "dependencies", "state", "budget", "nodes", "locations", "texts", "dynamic_sites"}, "unknown expansion keys")
    require(data["schema_version"] == 1 and data["revision"] == 1 and data["expansion_id"] == "helix-quiet-garden-v1", "unsupported content version")
    require(data["status"] == "fixture", "fixture only; no inference or release")
    require(data["state"] == {"first_flag": 48, "bytes": 2, "magic": 24576, "mask": 65472}, "reserved state contract changed")
    require(data["budget"] == {"maps": 1, "cells": 400, "objects": 3, "save_bytes": 2, "view_bytes": 20, "provider_requests": 0}, "budget exceeded or unknown")
    deps = data["dependencies"]
    require(deps == {
        "individual_package_sha256": "0c6a6c3ab374e1731aab4cf9b0fe87e9e548236ec5798c327a901d168e3b8dc6",
        "care_accepted_rom_sha256": "38584c2c2e9e53d8718891bfee67d2e3c7aa2980bb3ff8651095537266c42c3c",
        "quest_candidate_rom_sha256": "31c1202c10fb30d1c0f00cec80537e825dffd9bedb67145345cf243d0c657db4",
    }, "pinned dependencies changed")
    m, nodes = data["map"], data["nodes"]
    require(m["group"] == 75 and m["number"] == 3 and m["name"] == "HelixQuietGarden", "map address changed")
    layout = m["layout"]
    width, height = layout["width"], layout["height"]
    require(width == height == 20, "reviewed map dimensions changed")
    require((width+15)*(height+14) <= 10240, "native map-buffer budget exceeded")
    require(layout["primary_tileset"] == "gTileset_General" and layout["secondary_tileset"] == "gTileset_Petalburg", "unreviewed tilesets")
    require(layout["id"] == "LAYOUT_HELIX_QUIET_GARDEN" and layout["blockdata_filepath"] == "data/layouts/HelixQuietGarden/map.bin" and layout["border_filepath"] == "data/layouts/HelixQuietGarden/border.bin", "unsafe output path")
    grid = m["grid"]
    require(len(grid) == height and all(len(row) == width for row in grid), "grid dimensions mismatch")
    for row in grid:
        for block in row:
            integer(block, 0, 65535, "invalid metatile block")
            require(block in {0x3001, 0x31D9, 0x5D4, 0x5D5, 0x5DC, 0x5DD, 0x14A1, 0x403}, "unreviewed metatile")
    require(m["border"] == [0x5D4, 0x5D5, 0x5DC, 0x5DD], "reviewed border required")
    spawn = point(m["spawn"], width, height)
    require(walkable(grid[spawn[1]][spawn[0]]), "spawn collision")
    native = m["native"]
    require(set(native) == {"id", "name", "layout", "music", "region", "region_map_section", "requires_flash", "weather", "map_type", "allow_cycling", "allow_escaping", "allow_running", "show_map_name", "battle_scene", "connections", "object_events", "warp_events", "coord_events", "bg_events"}, "unknown native map fields")
    expected_metadata = {"music":"MUS_OLDALE", "region":"REGION_HOENN", "region_map_section":"MAPSEC_OLDALE_TOWN", "requires_flash":False, "weather":"WEATHER_SUNNY", "map_type":"MAP_TYPE_TOWN", "allow_cycling":False, "allow_escaping":False, "allow_running":True, "show_map_name":False, "battle_scene":"MAP_BATTLE_SCENE_NORMAL"}
    require(all(native[key] == value and type(native[key]) is type(value) for key,value in expected_metadata.items()), "unsupported native metadata")
    require(native["id"] == "MAP_HELIX_QUIET_GARDEN" and native["name"] == m["name"] and native["layout"] == layout["id"], "native address mismatch")
    require(native["connections"] is None and native["warp_events"] == [] and native["coord_events"] == [], "unsupported native transition")
    require(len(native["object_events"]) == 3 and len(native["bg_events"]) == 3, "object/event budget exceeded")
    occupied, targets = set(), set()
    for obj in native["object_events"] + native["bg_events"]:
        pos = point([obj["x"], obj["y"]], width, height)
        require(pos not in targets, "overlapping interaction")
        require(obj["script"] in SCRIPTS, "unsupported native handler")
        targets.add(pos)
        if "graphics_id" in obj:
            require(set(obj) == {"graphics_id", "x", "y", "elevation", "movement_type", "movement_range_x", "movement_range_y", "trainer_type", "trainer_sight_or_berry_tree_id", "script", "flag"}, "unknown NPC field")
            require(obj["graphics_id"] in {"OBJ_EVENT_GFX_WOMAN_1", "OBJ_EVENT_GFX_SCIENTIST_1", "OBJ_EVENT_GFX_MAN_1"} and obj["movement_type"] in {"MOVEMENT_TYPE_FACE_DOWN", "MOVEMENT_TYPE_FACE_UP"}, "unapproved NPC appearance/movement")
            require(obj["flag"] == "0" and obj["trainer_type"] == "TRAINER_TYPE_NONE" and obj["trainer_sight_or_berry_tree_id"] == "0" and obj["elevation"] == 3, "unsupported NPC effect")
            require(walkable(grid[pos[1]][pos[0]]), "NPC inside collision")
            require(obj["movement_range_x"] == obj["movement_range_y"] == 0, "moving NPC unreviewed")
            occupied.add(pos)
        else:
            require(set(obj) == {"type", "x", "y", "elevation", "player_facing_dir", "script"} and obj["type"] == "sign" and obj["elevation"] == 0 and obj["player_facing_dir"] == "BG_EVENT_PLAYER_FACING_ANY", "unsupported sign effect")
        expected_targets = {"Lia":(7,14), "Tom":(15,8), "Return":(10,18), "Bed":(5,11), "Mouth":(15,5), "Board":(10,10)}
        require(pos == expected_targets[obj["script"].removeprefix("HelixExpansion_EventScript_")], "trusted handler target mismatch")
    require({obj["script"] for obj in native["object_events"] + native["bg_events"]} == SCRIPTS, "missing trusted interaction")
    require(spawn not in occupied, "spawn occupied")
    require(data["entry"] == {"map": "HelixShelterTrail", "target": [18,15]}, "entry connection mismatch")
    require(m["return_destination"] == {"map": "HelixShelterTrail", "position": [18,16]} and m["return_target"] == [10,18], "return connection mismatch")
    require(data["locations"] == {"lia":[7,14], "bed":[5,11], "mouth":[15,5], "board":[10,10], "tom":[15,8]}, "native location bindings changed")
    require(data["dynamic_sites"] == [{"solution":"bed_screen", "position":[6,10], "block":1027}, {"solution":"mouth_screen", "position":[14,6], "block":1027}], "unsupported dynamic effect")
    for extra in [set()] + [{tuple(site["position"])} for site in data["dynamic_sites"]]:
        cells = reachable(grid, spawn, occupied | extra)
        for x,y in targets:
            require(any(p in cells for p in ((x-1,y),(x+1,y),(x,y-1),(x,y+1))), "unreachable interaction or return")
        # Every walkable component must remain reachable, not only the objective.
        all_floor = {(x,y) for y,row in enumerate(grid) for x,b in enumerate(row) if walkable(b)} - occupied - extra
        require(cells == all_floor, "isolated floor or one-way trapping")
    require(len(nodes) == 7 and {n["action"] for n in nodes} == set(ACTIONS), "quest action budget or coverage mismatch")
    ids = {n["id"] for n in nodes}
    require(len(ids) == len(nodes) and "offer" in ids and "replay" in ids, "duplicate/missing node IDs")
    for n in nodes:
        require(set(n) == {"id", "location", "action", "preconditions", "effects", "next"}, "unknown node fields")
        require(n["action"] in ACTIONS, "unapproved action")
        location, conditions, effects = ACTIONS[n["action"]]
        require(n["location"] == location and set(n["preconditions"]) == conditions and set(n["effects"]) == effects, "unapproved precondition/effect")
        require(all(edge in ids for edge in n["next"]), "dangling edge")
    graph = {n["id"]: set(n["next"]) for n in nodes}
    def visit(start):
        found, todo = set(), [start]
        while todo:
            here = todo.pop()
            if here not in found:
                found.add(here); todo.extend(graph[here])
        return found
    require(visit("offer") == ids and all("replay" in visit(n) for n in ids), "quest disconnected or has no terminal path")
    require(graph["test"] == {"bed_screen", "mouth_screen"} and graph["replay"] == set(), "both resolutions required")
    require(len(data["texts"]) == 22, "text budget changed")
    for text in data["texts"]:
        require(set(text) == {"en", "pt"}, "both languages required")
        for value in text.values():
            require(isinstance(value, str) and value.endswith("$") and len(value) <= 160, "unbounded text")
            require(all(ord(c) < 128 for c in value) and "{" not in value, "unsupported text control")
    return {"schema_version":1, "map_cells":400, "buffer_cells":1190, "native_objects":3, "quest_nodes":7, "text_bytes_utf8":sum(len(t) for pair in data["texts"] for t in pair.values()), "provider_requests":0}


def native_outputs(data):
    validate_expansion(data)
    m = data["map"]
    return {
        "data/maps/HelixQuietGarden/map.json": (json.dumps(m["native"], indent=2) + "\n").encode(),
        "data/layouts/HelixQuietGarden/map.bin": struct.pack("<400H", *(v for row in m["grid"] for v in row)),
        "data/layouts/HelixQuietGarden/border.bin": struct.pack("<4H", *m["border"]),
    }


def check_native(data, game: Path):
    pairs = re.findall(r'EXP_PAIR\("(.*?)", "(.*?)"\)', (game / "src/helix_expansion.c").read_text())
    require(data["texts"] == [dict(en=en, pt=pt) for en,pt in pairs], "native text drift")
    for relative, expected in native_outputs(data).items():
        require((game / relative).read_bytes() == expected, f"native drift: {relative}")
    return {path: sha256(value).hexdigest() for path, value in native_outputs(data).items()}
