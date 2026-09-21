#!/usr/bin/env python3
"""Run the backend's bounded daily authoring scheduler, separately from mGBA."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game_agents.world_planner import REGIONS, ROLES, WorldObservations, WorldPlannerStore


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate observations key")
        result[key] = value
    return result


def observations_from(path):
    if path is None:
        return None
    if path.stat().st_size > 4096:
        raise ValueError("observations file too large")
    with path.open("rb") as handle:
        raw = handle.read(4097)
    if len(raw) > 4096:
        raise ValueError("observations file too large")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    return WorldObservations.model_validate(data).model_dump()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("tick", "serve", "status", "context", "recover"))
    parser.add_argument("--state", type=Path, default=ROOT / ".local/world-planner/world.sqlite3")
    parser.add_argument("--world", default="local-world")
    parser.add_argument("--mode", choices=("fixture", "openrouter"), default="fixture")
    parser.add_argument("--model", help="Required explicit model in openrouter mode")
    parser.add_argument("--private-canon", type=Path, help="Private JSON inside .local, max 8 KiB")
    parser.add_argument("--observations", type=Path, help="JSON object containing trusted aggregate counts")
    parser.add_argument("--role", choices=ROLES, default="world")
    parser.add_argument("--region", choices=REGIONS, default="aurora_coast")
    parser.add_argument("--adventure", help="Pin authoring context to this existing adventure identity")
    parser.add_argument("--poll-seconds", type=float, default=30,
                        help="Scheduler check interval, 1..60 seconds; generation occurs once per UTC day")
    parser.add_argument("--max-ticks", type=int, help="Stop serve after this many checks (smoke testing)")
    args = parser.parse_args(argv)
    if not 1 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be 1..60")
    if args.max_ticks is not None and not 1 <= args.max_ticks <= 10000:
        parser.error("--max-ticks must be 1..10000")
    if args.mode == "openrouter" and not args.model:
        parser.error("openrouter mode requires --model")
    if args.mode == "fixture" and args.model:
        parser.error("--model requires --mode openrouter")
    try:
        store = WorldPlannerStore(args.state, world_id=args.world)
        if args.command == "status":
            result = store.status()
        elif args.command == "context":
            result = store.project_context(args.role, args.region, args.adventure)
        elif args.command == "recover":
            result = {"claims_marked_unknown": store.mark_stale_unknown(), "state": store.status()}
        else:
            provider = None
            if args.mode == "openrouter":
                from game_agents.world_provider import live_world_provider
                provider = live_world_provider(key=os.environ.get("OPENROUTER_API_KEY", ""),
                                               model=args.model)
            if args.command == "tick":
                result = store.tick(provider=provider, private_canon_path=args.private_canon,
                                    observations=observations_from(args.observations))
            else:
                stop = threading.Event()
                for signum in (signal.SIGINT, signal.SIGTERM):
                    signal.signal(signum, lambda *_: stop.set())
                count = 0
                previous = None
                while not stop.is_set():
                    try:
                        store.mark_stale_unknown()
                        result = store.tick(provider=provider, private_canon_path=args.private_canon,
                                            observations=observations_from(args.observations))
                    except (OSError, ValueError, sqlite3.Error):
                        result = {"status": "error", "error_code": "invalid_configuration_or_state"}
                    digest = json.dumps(result, sort_keys=True)
                    if digest != previous:
                        print(digest, flush=True)
                        previous = digest
                    count += 1
                    if args.max_ticks is not None and count >= args.max_ticks:
                        break
                    stop.wait(args.poll_seconds)
                return 0
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.Error):
        # Do not print private content, response text, provider errors or key paths.
        print(json.dumps({"status": "error", "error_code": "invalid_configuration_or_state"}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
