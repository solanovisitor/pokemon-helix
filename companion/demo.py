"""Compare two controlled conditions with the same fictional indicator culture.

All identifiers belong to the public-demo namespace. They bind observations;
they do not create Pokémon, import DNA, or refer to retained game individuals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib

from genetics.lab_simulation import canonical, simulate, verify_result

DEFAULT_PREDICTIONS = {"sheltered": "stable", "exposed": "sensitive"}
MAX_CONFIG_BYTES = 4096


def load_predictions(path: Path | None = None) -> dict[str, str]:
    if path is None:
        return dict(DEFAULT_PREDICTIONS)
    with path.open("rb") as stream:
        raw = stream.read(MAX_CONFIG_BYTES + 1)
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("demo configuration must be at most 4096 bytes")
    config = tomllib.loads(raw.decode("utf-8"))
    if set(config) != {"predictions"} or type(config["predictions"]) is not dict:
        raise ValueError("configuration requires only a [predictions] table")
    predictions = config["predictions"]
    if (set(predictions) != set(DEFAULT_PREDICTIONS)
            or any(type(value) is not str or value not in ("stable", "sensitive")
                   for value in predictions.values())):
        raise ValueError("sheltered and exposed predictions must be stable or sensitive")
    return predictions


def run_demo(predictions: dict[str, str]) -> dict:
    if set(predictions) != set(DEFAULT_PREDICTIONS):
        raise ValueError("both controlled conditions are required")
    snapshot = {"namespace": "helix-public-demo-v1", "culture": "nanomon-indicator-v1"}
    observations = []
    for condition in DEFAULT_PREDICTIONS:
        bindings = {
            "request_id": f"public-demo-{condition}-1",
            "save_lineage": "public-demo-no-save",
            "individual_id": "public-demo-no-pokemon",
            "snapshot_sha256": hashlib.sha256(canonical(snapshot)).hexdigest(),
            "quest_revision": 1,
        }
        result = simulate(condition, predictions[condition], bindings)
        verify_result(result, condition, predictions[condition], bindings)
        observations.append(result)
    return {"demo": "helix-public-demo-v1", "synthetic": True,
            "observations": observations,
            "limitations": "Fictional units; no biological prediction, DNA edit, ROM, or save access."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="optional synthetic TOML prediction settings")
    parser.add_argument("--json", action="store_true", help="print complete deterministic results and commitments")
    args = parser.parse_args(argv)
    try:
        report = run_demo(load_predictions(args.config))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    print("Pokémon Helix | synthetic indicator lab")
    print("Same culture, same medium, same -50 / 0 / +50 probes.")
    print()
    print("Condition   Prediction  Signals       Center  Range  Observation")
    for result in report["observations"]:
        request = result["request"]
        values = ", ".join(str(value) for value in result["values"])
        print(f"{request['condition']:<11} {request['prediction']:<11} {values:<13} "
              f"{result['signal']:>6}  {result['span']:>5}  {result['interpretation']}")
    print()
    print("Sheltered gives a stable reference; exposed gives a sensitive detector in this culture.")
    print("Range is max minus min over controlled probes, not statistical uncertainty.")
    print("Predictions change feedback only. Try --config examples/lab-demo.toml --json.")
    print(report["limitations"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
