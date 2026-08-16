#!/usr/bin/env python3
"""Run one compact-arm task across several seeds to quantify literal-RTD variance.

The provider does not honor seeds, so each seed is a label for an independent
realization, not a control. This records the benchmark RTD diagnostic per seed
so the literal-score noise can be contrasted with the (stable) semantic layer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.agentcollab_compact import (
    run_single_agentcollab_compact,
)
from mas_error_lifecycle.adapters.agentcollab_smoke import (
    APPROVED_RTD_TASKS,
    SmokeConfigurationError,
    SmokeExecutionError,
    add_override_argument,
    load_smoke_settings,
    parse_cli_overrides,
    read_api_key_from_user_input,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one compact-arm task across several seeds."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--seeds", required=True, help="comma-separated seed list")
    parser.add_argument("--config", type=Path)
    add_override_argument(parser)
    parser.add_argument("--api-key-stdin", action="store_true")
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[1]
    agentcollab_repository = args.agentcollab_repo.resolve()

    if args.task_id not in APPROVED_RTD_TASKS:
        print(json.dumps({"ok": False, "error": "task not on the approved RTD allowlist"}), file=sys.stderr)
        return 2
    seeds = [int(seed.strip()) for seed in args.seeds.split(",") if seed.strip()]
    if not seeds:
        print(json.dumps({"ok": False, "error": "--seeds must list at least one integer"}), file=sys.stderr)
        return 2
    try:
        settings = load_smoke_settings(
            repository_root=repository_root,
            config_path=args.config,
            overrides=parse_cli_overrides(args.override),
        )
        api_key, api_key_input_method = read_api_key_from_user_input(
            use_stdin=args.api_key_stdin
        )
    except SmokeConfigurationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    results: list[dict[str, object]] = []
    for seed in seeds:
        try:
            run = run_single_agentcollab_compact(
                repository_root=repository_root,
                agentcollab_repository=agentcollab_repository,
                task_file=agentcollab_repository / "tasks" / f"{args.task_id}.json",
                expected_task_id=args.task_id,
                metric="rtd",
                settings=settings,
                api_key=api_key,
                api_key_input_method=api_key_input_method,
                seed=seed,
            )
            results.append(
                {
                    "seed": seed,
                    "ok": True,
                    "run_id": run.run_id,
                    "diagnostic_score": run.diagnostic_score,
                    "trace": str(run.trace_path),
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        except SmokeExecutionError as exc:
            results.append({"seed": seed, "ok": False, "error_type": exc.error_type, "error": str(exc)})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        except SmokeConfigurationError as exc:
            results.append({"seed": seed, "ok": False, "error": str(exc)})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    print(
        json.dumps(
            {
                "task_id": args.task_id,
                "results": results,
                "ok_count": sum(1 for r in results if r["ok"]),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
