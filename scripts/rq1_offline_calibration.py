#!/usr/bin/env python3
"""Run the deterministic derived RQ1 calibration without provider access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mas_error_lifecycle.rq1 import run_offline_rq1_calibration


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the synthetic 1-fixture x 3-arm RQ1 offline calibration."
    )
    parser.add_argument(
        "--include-traces",
        action="store_true",
        help="include the three synthetic JSON trace record arrays",
    )
    args = parser.parse_args()
    report = run_offline_rq1_calibration()
    print(
        json.dumps(
            report.to_dict(include_traces=args.include_traces),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
