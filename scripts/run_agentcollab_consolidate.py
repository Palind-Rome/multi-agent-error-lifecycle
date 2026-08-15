#!/usr/bin/env python3
"""Run the Codex leader-consolidation arm over the approved RTD tasks.

For each approved task, find its latest completed native (verbatim) run, then
make one leader consolidation call over that run's full conversation. This is
the multi-agent treatment; it adds exactly one provider call per task and never
re-runs the relay.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.agentcollab_consolidate import (
    run_single_agentcollab_consolidate,
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


def _latest_native_run(repository_root: Path, task_id: str) -> Path | None:
    private = repository_root / "outputs" / "private"
    candidates: list[tuple[float, Path]] = []
    for directory in private.iterdir():
        if not directory.is_dir() or task_id not in directory.name:
            continue
        if "compact" in directory.name or "consolidate" in directory.name:
            continue
        ledger = directory / "failure-ledger.json"
        if not ledger.is_file():
            continue
        try:
            document = json.loads(ledger.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if document.get("status") == "completed":
            candidates.append((directory.stat().st_mtime, directory))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate the latest native run of each approved RTD task."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    add_override_argument(parser)
    parser.add_argument("--api-key-stdin", action="store_true")
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[1]
    agentcollab_repository = args.agentcollab_repo.resolve()
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
    for task_id in APPROVED_RTD_TASKS:
        native_run = _latest_native_run(repository_root, task_id)
        if native_run is None:
            results.append({"task_id": task_id, "ok": False, "error": "no completed native run"})
            continue
        try:
            run = run_single_agentcollab_consolidate(
                repository_root=repository_root,
                agentcollab_repository=agentcollab_repository,
                native_run_directory=native_run,
                task_file=agentcollab_repository / "tasks" / f"{task_id}.json",
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
                    "native_run": native_run.name,
                    "summary": str(run.trace_path),
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
        except (SmokeConfigurationError, SmokeExecutionError) as exc:
            results.append({"task_id": task_id, "ok": False, "error": str(exc)})
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    print(
        json.dumps(
            {
                "tasks": results,
                "ok_count": sum(1 for r in results if r["ok"]),
                "total": len(results),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
