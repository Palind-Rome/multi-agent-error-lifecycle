#!/usr/bin/env python3
"""Run the approved AgentCollabBench RTD instrumentation sample in one pass.

This is the native, analysis-ineligible instrumentation run for RQ1 ("where
does correct information get lost"): each untouched RTD task is executed once
through the guarded smoke driver and its lifecycle trace is persisted under
``outputs/private``. It is not a generic run-plan executor; it only visits the
reviewed ``APPROVED_RTD_TASKS`` allowlist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.agentcollab_smoke import (
    ANALYSIS_ELIGIBLE,
    APPROVED_RTD_TASKS,
    PURPOSE,
    SmokeConfigurationError,
    SmokeExecutionError,
    add_override_argument,
    load_smoke_settings,
    parse_cli_overrides,
    read_api_key_from_user_input,
    run_single_agentcollab_smoke,
)


def _run_batch(
    *,
    repository_root: Path,
    agentcollab_repository: Path,
    settings: object,
    api_key: str,
    api_key_input_method: str,
) -> dict[str, object]:
    results: list[dict[str, object]] = []
    for task_id in APPROVED_RTD_TASKS:
        task_file = agentcollab_repository / "tasks" / f"{task_id}.json"
        try:
            run = run_single_agentcollab_smoke(
                repository_root=repository_root,
                agentcollab_repository=agentcollab_repository,
                task_file=task_file,
                expected_task_id=task_id,
                metric="rtd",
                settings=settings,
                api_key=api_key,
                api_key_input_method=api_key_input_method,
                seed=7,
            )
            results.append(
                {
                    "task_id": task_id,
                    "ok": True,
                    "run_id": run.run_id,
                    "diagnostic_score": run.diagnostic_score,
                    "trace": str(run.trace_path),
                }
            )
        except (SmokeConfigurationError, SmokeExecutionError) as exc:
            results.append({"task_id": task_id, "ok": False, "error": str(exc)})
    return {
        "purpose": PURPOSE,
        "analysis_eligible": ANALYSIS_ELIGIBLE,
        "tasks": results,
        "ok_count": sum(1 for item in results if item["ok"]),
        "total": len(results),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the approved AgentCollabBench RTD instrumentation sample."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    add_override_argument(parser)
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="read exactly one API-key line from non-TTY stdin",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[1]
    try:
        settings = load_smoke_settings(
            repository_root=repository_root,
            config_path=args.config,
            overrides=parse_cli_overrides(args.override),
        )
        api_key, api_key_input_method = read_api_key_from_user_input(
            use_stdin=args.api_key_stdin
        )
        result = _run_batch(
            repository_root=repository_root,
            agentcollab_repository=args.agentcollab_repo,
            settings=settings,
            api_key=api_key,
            api_key_input_method=api_key_input_method,
        )
    except SmokeConfigurationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "unexpected batch failure; no credential was printed"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
