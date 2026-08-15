#!/usr/bin/env python3
"""Run the Codex-style compaction derived suite over approved RTD tasks.

One pass over the reviewed ``APPROVED_RTD_TASKS`` allowlist: each untouched RTD
task is executed once with a Codex checkpoint-compaction summary at every
inter-agent handoff, and its lifecycle trace plus compaction-summaries sidecar
are persisted under ``outputs/private``. The native run is the control arm; this
is the treatment arm.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.agentcollab_compact import (
    CONDITION_ID,
    PROTOCOL_KIND,
    run_single_agentcollab_compact,
)
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
)


def _run_batch(
    *,
    repository_root: Path,
    agentcollab_repository: Path,
    settings: object,
    api_key: str,
    api_key_input_method: str,
    task_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    selected = list(task_ids) if task_ids else list(APPROVED_RTD_TASKS)
    unknown = [task_id for task_id in selected if task_id not in APPROVED_RTD_TASKS]
    if unknown:
        raise SmokeConfigurationError(
            "task not on the approved RTD allowlist: " + ", ".join(sorted(unknown))
        )
    results: list[dict[str, object]] = []
    for task_id in selected:
        task_file = agentcollab_repository / "tasks" / f"{task_id}.json"
        try:
            run = run_single_agentcollab_compact(
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
        "condition_id": CONDITION_ID,
        "protocol_kind": PROTOCOL_KIND,
        "tasks": results,
        "ok_count": sum(1 for item in results if item["ok"]),
        "total": len(results),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Codex-compaction derived suite over approved RTD tasks."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--task-id",
        action="append",
        default=[],
        metavar="ID",
        help="run only this allowlisted task (repeatable; default: all approved)",
    )
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
            task_ids=args.task_id or None,
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
