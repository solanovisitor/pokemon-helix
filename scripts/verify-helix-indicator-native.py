#!/usr/bin/env python3
"""Run native model equivalence and emit evidence; never opens ROMs or saves."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output is not None and args.output.exists():
        parser.error("existing evidence output is refused")
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        parser.error("a C compiler is required")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                               pattern="test_helix_indicator_native.py")
    log = io.StringIO()
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    duration = time.perf_counter() - start
    paths = ("rom-source/overlay/src/helix_indicator_model.c", "rom-source/overlay/include/helix_indicator_model.h",
             "genetics/lab_simulation.py", "tests/test_helix_indicator_native.py",
             "tests/fixtures/helix-indicator-hill-v1.json",
             "scripts/verify-helix-indicator-native.py")
    report = {"schema": "helix-indicator-native-equivalence-v1",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "machine": platform.machine(),
              "python": platform.python_version(),
              "compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
              "optimization_levels": ["-O0", "-O2"],
              "sanitizer": "undefined; no recovery",
              "passed": result.wasSuccessful(), "tests": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped), "duration_seconds": duration,
              "domain_stimuli": 1001, "protocol_prediction_pairs": 4,
              "invalid_enum_combinations_per_optimization": 262136,
              "limits": {"square_max": 1000000, "denominator_max": 1250000,
                         "rounded_numerator_max": 80625000},
              "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths},
              "test_log": log.getvalue(),
              "scope": "C model numeric/API verification, not GBA emulation or RG34XX hardware"}
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        with args.output.open("x") as output:
            output.write(encoded)
    else:
        print(encoded, end="")
    print(log.getvalue(), file=sys.stderr, end="")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
