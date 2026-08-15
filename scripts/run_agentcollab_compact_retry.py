#!/usr/bin/env python3
"""Retry one compact-arm RTD task through network flakiness.

The guarded compact driver has no automatic retry (fail-closed). This wrapper
retries only transport failures (``ProviderRequestError``) so a long task can
survive intermittent network drops, while configuration and contract errors
still fail immediately.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.agentcollab_compact import (
    run_single_agentcollab_compact,
)
from mas_error_lifecycle.adapters.agentcollab_smoke import (
    APPROVED_RTD_TASKS,
    SmokeConfigurationError,
    SmokeExecutionError,
    load_smoke_settings,
    read_api_key_from_user_input,
)

_RETRYABLE_ERROR = "ProviderRequestError"


def _attempt(
    *,
    repository_root: Path,
    agentcollab_repository: Path,
    task_id: str,
    settings: object,
    api_key: str,
    api_key_input_method: str,
) -> object:
    return run_single_agentcollab_compact(
        repository_root=repository_root,
        agentcollab_repository=agentcollab_repository,
        task_file=agentcollab_repository / "tasks" / f"{task_id}.json",
        expected_task_id=task_id,
        metric="rtd",
        settings=settings,
        api_key=api_key,
        api_key_input_method=api_key_input_method,
        seed=7,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retry one compact-arm RTD task through network flakiness."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--max-attempts", type=int, default=15)
    parser.add_argument("--delay-seconds", type=float, default=30.0)
    parser.add_argument("--api-key-stdin", action="store_true")
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[1]
    agentcollab_repository = args.agentcollab_repo.resolve()

    if args.task_id not in APPROVED_RTD_TASKS:
        print(json.dumps({"ok": False, "error": "task not on the approved RTD allowlist"}), file=sys.stderr)
        return 2
    try:
        settings = load_smoke_settings(
            repository_root=repository_root,
            config_path=args.config,
            overrides={},
        )
        api_key, api_key_input_method = read_api_key_from_user_input(
            use_stdin=args.api_key_stdin
        )
    except SmokeConfigurationError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    for attempt in range(1, args.max_attempts + 1):
        try:
            run = _attempt(
                repository_root=repository_root,
                agentcollab_repository=agentcollab_repository,
                task_id=args.task_id,
                settings=settings,
                api_key=api_key,
                api_key_input_method=api_key_input_method,
            )
        except SmokeExecutionError as exc:
            if exc.error_type == _RETRYABLE_ERROR and attempt < args.max_attempts:
                print(
                    json.dumps(
                        {"ok": False, "attempt": attempt, "error_type": exc.error_type, "retrying": True},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                time.sleep(args.delay_seconds)
                continue
            print(
                json.dumps({"ok": False, "attempt": attempt, "error": str(exc)}, ensure_ascii=False),
                file=sys.stderr,
            )
            return 2
        except SmokeConfigurationError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 2

        print(
            json.dumps(
                {
                    "ok": True,
                    "attempt": attempt,
                    "task_id": args.task_id,
                    "diagnostic_score": run.diagnostic_score,
                    "trace": str(run.trace_path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(json.dumps({"ok": False, "error": "exhausted retry attempts"}, ensure_ascii=False), file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
