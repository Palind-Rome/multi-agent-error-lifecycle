"""Codex multi-agent "leader consolidation" arm for RQ1.

Codex multi-agent communication differs from per-hop compaction in that a
leader consolidates the *full* set of subagent results into one answer at the
end, rather than summarizing each individual handoff. This arm reproduces that
mechanism: it reuses a completed native (verbatim) relay trace, then makes a
single leader consolidation call over the full conversation using the verbatim
Codex ``COMPACT_PROMPT``. The consolidation summary is the artifact under test —
does the tracer's meaning survive the leader merging many agents' outputs?

This is a derived analysis over an existing native run, so it does not re-run
the relay; it adds exactly one provider call per task.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.dont_write_bytecode = True

from .agentcollab_compact import COMPACT_PROMPT, CONDITION_ID, PROTOCOL_KIND
from .agentcollab_smoke import (
    ANALYSIS_ELIGIBLE,
    APPROVED_METRIC,
    APPROVED_RTD_TASKS,
    PURPOSE,
    BudgetGate,
    OpenAICompatibleSmokeProvider,
    PrivateRunStore,
    RunLedger,
    SmokeConfigurationError,
    SmokeExecutionError,
    SmokeRunResult,
    SmokeSettings,
    load_smoke_settings,
    read_api_key_from_user_input,
    verify_agentcollab_repository,
    load_untouched_native_task,
    _API_KEY_INPUT_METHODS,
    _assert_api_key_not_in_environment,
    _new_run_id,
    _validate_api_key,
)

CONDITION = "codex-leader-consolidation"


@dataclass(slots=True)
class _Message:
    role: str
    content: str


def _assemble_conversation(conversation: Sequence[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for step in conversation:
        if not isinstance(step, dict):
            continue
        agent_id = step.get("agent_id") or step.get("role") or "agent"
        content = step.get("content", "")
        if content:
            parts.append(f"[{agent_id}]:\n{content}")
    return "\n\n---\n\n".join(parts)


def run_single_agentcollab_consolidate(
    *,
    repository_root: Path,
    agentcollab_repository: Path,
    native_run_directory: Path,
    task_file: Path,
    expected_task_id: str,
    metric: str,
    settings: SmokeSettings,
    api_key: str,
    api_key_input_method: str = "caller_memory",
    seed: int = 7,
    run_id: str | None = None,
    transport: Any | None = None,
) -> SmokeRunResult:
    """Consolidate one completed native relay into a single leader summary."""

    _assert_api_key_not_in_environment()
    if api_key_input_method not in _API_KEY_INPUT_METHODS:
        raise SmokeConfigurationError("invalid API-key input method label")
    if not isinstance(api_key, str):
        raise SmokeConfigurationError("PaperBypass API key must be text")
    _validate_api_key(api_key)
    sys.dont_write_bytecode = True
    upstream_commit = verify_agentcollab_repository(agentcollab_repository)
    task, task_bytes_sha256 = load_untouched_native_task(
        agentcollab_repository,
        task_file,
        expected_task_id=expected_task_id,
        metric=metric,
    )

    native_raw_path = native_run_directory / "raw" / "agentcollab-result.json"
    if not native_raw_path.is_file():
        raise SmokeConfigurationError(
            f"native run is missing raw/agentcollab-result.json: {native_run_directory}"
        )
    native_raw = json.loads(native_raw_path.read_text())
    native_trace = native_raw.get("run_result", {}).get("trace", {})
    conversation = native_trace.get("conversation")
    if not isinstance(conversation, list) or not conversation:
        raise SmokeConfigurationError("native run has no conversation to consolidate")
    full_text = _assemble_conversation(conversation)

    resolved_run_id = run_id or _new_run_id(f"consolidate-{expected_task_id}")
    store = PrivateRunStore.create(repository_root, resolved_run_id, api_key)
    budget = BudgetGate(settings.limits)
    ledger = RunLedger(
        store,
        run_id=resolved_run_id,
        task_id=expected_task_id,
        metric=metric,
        native_task_sha256=task_bytes_sha256,
        upstream_commit=upstream_commit,
        settings=settings,
        seed=seed,
        api_key_input_method=api_key_input_method,
    )
    ledger.mark_running(budget)
    provider = OpenAICompatibleSmokeProvider(
        settings.provider,
        api_key=api_key,
        budget=budget,
        store=store,
        ledger=ledger,
        transport=transport,
        seed=seed,
    )

    stage = "provider_execution"
    try:
        messages = [
            _Message(role="assistant", content=full_text),
            _Message(role="user", content=COMPACT_PROMPT),
        ]
        response = provider.chat(messages)
        summary = response.content
        budget.assert_runtime()

        stage = "consolidation_persistence"
        payload = {
            "task_id": expected_task_id,
            "native_run_directory": native_run_directory.name,
            "consolidation_summary": summary,
            "full_conversation": full_text,
            "compact_prompt": COMPACT_PROMPT,
            "tracer": _tracer_payload(task, metric),
            "condition_id": CONDITION,
            "protocol_kind": PROTOCOL_KIND,
        }
        raw_result_path = store.write_json("raw/consolidation-result.json", payload)
        summary_path = store.write_text(
            "consolidation-summary.txt", summary + "\n"
        )
        budget.assert_runtime()
        ledger.mark_completed(
            raw_result_path=raw_result_path,
            trace_path=summary_path,
            budget=budget,
        )
    except Exception as exc:
        ledger.mark_failed(stage, type(exc).__name__, budget)
        raise SmokeExecutionError(stage, type(exc).__name__, ledger.path) from exc

    return SmokeRunResult(
        run_id=resolved_run_id,
        task_id=expected_task_id,
        metric=metric,
        diagnostic_score=-1.0,
        run_directory=store.run_directory,
        ledger_path=ledger.path,
        raw_result_path=raw_result_path,
        trace_path=summary_path,
    )


def _tracer_payload(task: Mapping[str, Any], metric: str) -> list[dict[str, Any]]:
    injections = task.get("injections", {})
    rtd = injections.get(metric, {}) if isinstance(injections, dict) else {}
    if isinstance(rtd, dict) and isinstance(rtd.get("constraints"), list):
        rows = rtd["constraints"]
    elif isinstance(rtd, dict) and isinstance(rtd.get("multi_constraint"), dict):
        rows = rtd["multi_constraint"].get("constraints", [])
    else:
        rows = [rtd]
    return [
        {"tracer_id": str(row.get("tracer_id")), "anchor": str(row.get("anchor"))}
        for row in rows
        if isinstance(row, dict)
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Consolidate one native AgentCollabBench relay into a leader summary."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--native-run-dir", required=True, type=Path)
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--metric", required=True, choices=[APPROVED_METRIC])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--api-key-stdin", action="store_true")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--max-output-tokens-per-call", type=int)
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--max-cost-usd")
    parser.add_argument("--max-input-cost-usd-per-million-tokens")
    parser.add_argument("--max-output-cost-usd-per-million-tokens")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[3]
    overrides = {
        "max_calls": args.max_calls,
        "max_input_tokens": args.max_input_tokens,
        "max_output_tokens": args.max_output_tokens,
        "max_output_tokens_per_call": args.max_output_tokens_per_call,
        "max_wall_seconds": args.max_wall_seconds,
        "max_cost_usd": args.max_cost_usd,
        "max_input_cost_usd_per_million_tokens": (
            args.max_input_cost_usd_per_million_tokens
        ),
        "max_output_cost_usd_per_million_tokens": (
            args.max_output_cost_usd_per_million_tokens
        ),
    }
    try:
        _assert_api_key_not_in_environment()
        settings = load_smoke_settings(
            repository_root=repository_root,
            config_path=args.config,
            overrides=overrides,
        )
        api_key, api_key_input_method = read_api_key_from_user_input(
            use_stdin=args.api_key_stdin
        )
        result = run_single_agentcollab_consolidate(
            repository_root=repository_root,
            agentcollab_repository=args.agentcollab_repo,
            native_run_directory=args.native_run_dir,
            task_file=args.task_file,
            expected_task_id=args.task_id,
            metric=args.metric,
            settings=settings,
            api_key=api_key,
            api_key_input_method=api_key_input_method,
            seed=args.seed,
            run_id=args.run_id,
        )
    except (SmokeConfigurationError, SmokeExecutionError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception:
        print(
            json.dumps(
                {"ok": False, "error": "unexpected consolidation failure; no credential printed"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    print(
        json.dumps(
            {
                "ok": True,
                "condition_id": CONDITION,
                "protocol_kind": PROTOCOL_KIND,
                "run_id": result.run_id,
                "task_id": result.task_id,
                "private_run_directory": str(result.run_directory),
                "consolidation_summary": str(result.trace_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
