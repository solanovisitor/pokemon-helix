#!/usr/bin/env python3
"""Explicit offline-first Pokémon candidate workflow, never native admission."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game_agents.pokemon_generator import PokemonDossier, PokemonGeneratorQueue, native_dossier
from genetics.adventure_package import publish
from genetics.primers import canonical
from genetics.universal_native import decode_store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    native = sub.add_parser("native-input", help="Read independently observed registry bytes; no save writes")
    native.add_argument("--registry", type=Path, required=True)
    native.add_argument("--individual-id", required=True)
    native.add_argument("--output", type=Path, required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--dossier", type=Path, required=True)
    plan.add_argument("--parents-dir", type=Path)
    plan.add_argument("--live", action="store_true")
    plan.add_argument("--model")
    run = sub.add_parser("run")
    run.add_argument("--live", action="store_true")
    run.add_argument("--key-env", help="Explicit environment variable containing the selected live key")
    sub.add_parser("status")
    recover = sub.add_parser("recover", help="Reconcile retained candidate after the old worker stopped and lease expired")
    recover.add_argument("--candidate-sha256", required=True)
    recover.add_argument("--note", required=True)
    args = parser.parse_args()
    if args.command == "native-input":
        with args.registry.open("rb") as stream: raw = stream.read(1473)
        store = decode_store(raw)
        record = next((r for r in store["records"] if r["id_hex"] == args.individual_id), None)
        if record is None: raise ValueError("individual absent from supplied valid registry")
        value = native_dossier(record, registry_sha256=sha256(raw).hexdigest())
        publish(args.output, canonical(value))
        print(json.dumps({"dossier": str(args.output), "native_admission": "none"}))
        return
    if args.queue is None: parser.error("--queue is required for this command")
    queue = PokemonGeneratorQueue(args.queue)
    try:
        if args.command == "plan":
            if args.live != bool(args.model): parser.error("--live and --model are required together")
            with args.dossier.open("rb") as stream: raw = stream.read(65537)
            if len(raw) > 65536: raise ValueError("oversized dossier")
            dossier = PokemonDossier.model_validate_json(raw)
            images = {}
            for parent in dossier.parents:
                if args.parents_dir is None: parser.error("offspring requires --parents-dir with both approved PNGs")
                with (args.parents_dir / (parent.image_sha256 + ".png")).open("rb") as stream:
                    images[parent.image_sha256] = stream.read(2 * 1024 * 1024 + 1)
            result = queue.plan(dossier.model_dump(mode="json"), images=images,
                                mode="external_model" if args.live else "fixture", model=args.model or "none")
        elif args.command == "run":
            if args.live != bool(args.key_env): parser.error("--live and --key-env are required together")
            key = os.environ.get(args.key_env) if args.key_env else None
            result = queue.run(live=args.live, key=key)
        elif args.command == "recover":
            row = queue.db.execute("SELECT id FROM jobs").fetchone()
            if row is None: raise ValueError("no planned job")
            queue.reconcile(row[0], outcome="accepted", note=args.note, result_sha256=args.candidate_sha256)
            result = queue.summary()
        else:
            result = queue.summary()
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    finally:
        queue.close()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError):
        print(json.dumps({"error": "Input, preserved candidate or external attempt requires inspection; no individual was issued."}), file=sys.stderr)
        sys.exit(1)
