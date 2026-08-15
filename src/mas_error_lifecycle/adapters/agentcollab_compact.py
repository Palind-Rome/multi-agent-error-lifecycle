"""Codex-style checkpoint-compaction derived suite for RQ1.

The native AgentCollabBench RTD relay forwards each parent agent's verbatim
output to its downstream agents, so a tracer survives unless an agent edits it
out. Real multi-agent systems instead compact accumulated context into a
handoff summary when it grows large; that compaction is where correct
information is lost.

This module reproduces that mechanism faithfully. The two prompts below are
the verbatim Codex templates at ``codex-rs/prompts/templates/compact/``:

- ``COMPACT_PROMPT`` instructs the model to produce a handoff summary.
- ``SUMMARY_PREFIX`` frames the summary when it is handed to the next model.

At every inter-agent handoff the parent's raw output is summarized with
``COMPACT_PROMPT`` and the downstream agent receives ``SUMMARY_PREFIX`` plus
that summary in place of the raw text. The untouched native task bytes are
unchanged; the treatment lives entirely in the runner wiring, so the native
``agentcollab_smoke`` path and this derived path share the same pinned inputs.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.dont_write_bytecode = True

from .agentcollab_runner import CompactConfig, evaluate_agentcollab_task
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
    expected_agentcollab_calls,
    _API_KEY_INPUT_METHODS,
    _activate_agentcollab_repository,
    _assert_api_key_not_in_environment,
    _canonical_sha256,
    _new_run_id,
    _validate_api_key,
)
from .agentcollabbench import convert_agentcollab_result

# Verbatim Codex templates (openai/codex, codex-rs/prompts/templates/compact/).
COMPACT_PROMPT = (
    "You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff "
    "summary for another LLM that will resume the task.\n"
    "\n"
    "Include:\n"
    "- Current progress and key decisions made\n"
    "- Important context, constraints, or user preferences\n"
    "- What remains to be done (clear next steps)\n"
    "- Any critical data, examples, or references needed to continue\n"
    "\n"
    "Be concise, structured, and focused on helping the next LLM seamlessly "
    "continue the work.\n"
)

SUMMARY_PREFIX = (
    "Another language model started to solve this problem and produced a "
    "summary of its thinking process. You also have access to the state of the "
    "tools that were used by that language model. Use this to build on the work "
    "that has already been done and avoid duplicating work. Here is the summary "
    "produced by the other language model, use the information in this summary "
    "to assist with your own analysis:\n"
)

PROTOCOL_KIND = "agentcollab_codex_compact"
CONDITION_ID = "codex-compact-handoff"


def _parents_from_topology(topology: Mapping[str, Any]) -> dict[str, list[str]]:
    """Parse topology edges into ``{child: [parents]}``, matching DAGTopology."""

    parents: dict[str, list[str]] = {}
    for edge in topology.get("edges", []):
        if isinstance(edge, dict):
            source = edge.get("source") or edge.get("from") or edge.get("sender")
            target = edge.get("target") or edge.get("to") or edge.get("receiver")
        elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
            source, target = edge[0], edge[1]
        else:
            continue
        if not source or not target:
            continue
        parents.setdefault(target, []).append(source)
    return parents


def expected_compaction_calls(task: Mapping[str, Any], *, metric: str) -> int:
    """Number of handoffs that trigger a compaction turn.

    The upstream runner repeats the speaking order until the metric's expected
    turn budget is met. A position is compacted only when its assembled parent
    context is non-empty — i.e. at least one topology parent has already spoken
    in this run (a dense topology's first speaker has parents that are still
    empty, so it receives the root injection prompt, not a compaction). This
    simulates the speaking order to match the runner exactly.
    """

    topology = task.get("topology", {})
    speaking_order = topology.get("speaking_order", [])
    if not isinstance(speaking_order, list) or not speaking_order:
        return 0
    expected_turns = expected_agentcollab_calls(task, metric=metric)
    parents = _parents_from_topology(topology)
    effective_order = [
        speaking_order[i % len(speaking_order)] for i in range(expected_turns)
    ]
    spoken: set[str] = set()
    compactions = 0
    for agent_id in effective_order:
        if any(parent in spoken for parent in parents.get(agent_id, [])):
            compactions += 1
        spoken.add(agent_id)
    return compactions


def run_single_agentcollab_compact(
    *,
    repository_root: Path,
    agentcollab_repository: Path,
    task_file: Path,
    expected_task_id: str,
    metric: str,
    settings: SmokeSettings,
    api_key: str,
    api_key_input_method: str = "caller_memory",
    seed: int = 7,
    run_id: str | None = None,
    transport: Any | None = None,
) -> Any:
    """Execute one allowlisted RTD task with compaction at every handoff."""

    _assert_api_key_not_in_environment()
    if api_key_input_method not in _API_KEY_INPUT_METHODS:
        raise SmokeConfigurationError("invalid API-key input method label")
    if not isinstance(api_key, str):
        raise SmokeConfigurationError("PaperBypass API key must be text")
    _validate_api_key(api_key)
    sys.dont_write_bytecode = True
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise SmokeConfigurationError("seed must be an integer in [0, 2^31)")
    upstream_commit = verify_agentcollab_repository(agentcollab_repository)
    task, task_bytes_sha256 = load_untouched_native_task(
        agentcollab_repository,
        task_file,
        expected_task_id=expected_task_id,
        metric=metric,
    )
    expected_calls = expected_agentcollab_calls(task, metric=metric)
    # expected_compaction_calls parses topology edges locally and does not import
    # the upstream package, so this and the budget gate run before activation and
    # a rejected run never pollutes sys.modules with the upstream import.
    expected_compactions = expected_compaction_calls(task, metric=metric)
    total_calls = expected_calls + expected_compactions
    if total_calls > settings.limits.max_calls:
        raise SmokeConfigurationError(
            f"task requires {total_calls} calls (agents + compaction) but "
            f"max_calls is {settings.limits.max_calls}"
        )
    if settings.limits.max_output_tokens < total_calls:
        raise SmokeConfigurationError(
            "max_output_tokens must allow at least one token per expected call"
        )
    _activate_agentcollab_repository(agentcollab_repository)

    resolved_run_id = run_id or _new_run_id(f"compact-{expected_task_id}")
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
    compact = CompactConfig(
        summarizer=provider,
        prompt=COMPACT_PROMPT,
        summary_prefix=SUMMARY_PREFIX,
    )
    stage = "provider_execution"
    try:
        agent_ids = [str(agent["agent_id"]) for agent in task["topology"]["agents"]]
        metric_config: dict[str, Any] = {}
        random_state = random.getstate()
        random.seed(seed)
        try:
            evaluation = evaluate_agentcollab_task(
                copy.deepcopy(task),
                {agent_id: provider for agent_id in agent_ids},
                metric=metric,
                metric_config=metric_config,
                compact=compact,
                run_context={
                    "run_id": resolved_run_id,
                    "purpose": PURPOSE,
                    "analysis_eligible": ANALYSIS_ELIGIBLE,
                    "protocol_kind": PROTOCOL_KIND,
                    "condition_id": CONDITION_ID,
                    "cluster_id": expected_task_id,
                    "review_status": "derived",
                    "native_task_hash": task_bytes_sha256,
                    "upstream_commit": upstream_commit,
                    "seed": seed,
                    "provider_seed_sent": settings.provider.send_seed,
                    "compact_prompt_sha256": hashlib.sha256(
                        COMPACT_PROMPT.encode("utf-8")
                    ).hexdigest(),
                    "summary_prefix_sha256": hashlib.sha256(
                        SUMMARY_PREFIX.encode("utf-8")
                    ).hexdigest(),
                },
            )
        finally:
            random.setstate(random_state)
        budget.assert_runtime()

        stage = "completion_reconciliation"
        provider_requests = evaluation.run_result.trace.get("provider_requests")
        compaction_calls = evaluation.run_result.trace.get("compaction_calls")
        if not isinstance(provider_requests, list):
            raise SmokeConfigurationError(
                "upstream result is missing provider_requests"
            )
        if not isinstance(compaction_calls, list):
            raise SmokeConfigurationError(
                "upstream result is missing compaction_calls"
            )
        if not (
            budget.calls_started
            == budget.calls_completed
            == total_calls
            == len(provider_requests) + len(compaction_calls)
        ):
            raise SmokeConfigurationError(
                "completed call/provider-request counts do not match expected "
                "agent-plus-compaction calls"
            )
        if len(provider_requests) != expected_calls:
            raise SmokeConfigurationError(
                "agent provider-request count does not match expected calls"
            )
        if len(compaction_calls) != expected_compactions:
            raise SmokeConfigurationError(
                "compaction-call count does not match expected handoffs"
            )

        stage = "untouched_task_verification"
        scenario = evaluation.run_result.to_dict().get("scenario")
        if _canonical_sha256(scenario) != _canonical_sha256(task):
            raise SmokeConfigurationError(
                "upstream execution changed the native task scenario"
            )

        stage = "raw_result_persistence"
        payload = evaluation.to_adapter_payload()
        raw_result_path = store.write_json("raw/agentcollab-result.json", payload)

        stage = "lifecycle_conversion"
        bundle = convert_agentcollab_result(payload)
        if bundle.manifest.purpose != PURPOSE or bundle.manifest.analysis_eligible:
            raise SmokeConfigurationError(
                "lifecycle adapter did not preserve engineering smoke eligibility gates"
            )
        trace_lines = "".join(
            json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False) + "\n"
            for record in bundle.records()
        )
        trace_path = store.write_text("lifecycle-trace.jsonl", trace_lines)

        stage = "compaction_sidecar"
        compaction_lines = "".join(
            json.dumps(call, ensure_ascii=False, allow_nan=False) + "\n"
            for call in compaction_calls
        )
        compaction_path = store.write_text(
            "compaction-summaries.jsonl", compaction_lines
        )

        budget.assert_runtime()
        ledger.mark_completed(
            raw_result_path=raw_result_path,
            trace_path=trace_path,
            budget=budget,
        )
    except Exception as exc:
        ledger.mark_failed(stage, type(exc).__name__, budget)
        raise SmokeExecutionError(stage, type(exc).__name__, ledger.path) from exc

    return SmokeRunResult(
        run_id=resolved_run_id,
        task_id=expected_task_id,
        metric=metric,
        diagnostic_score=evaluation.score,
        run_directory=store.run_directory,
        ledger_path=ledger.path,
        raw_result_path=raw_result_path,
        trace_path=trace_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one private, analysis-ineligible AgentCollabBench RTD task "
            "with Codex-style compaction at every handoff."
        )
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--metric", required=True, choices=[APPROVED_METRIC])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--api-key-stdin", action="store_true")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--request-timeout-seconds", type=float)
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
        "base_url": args.base_url,
        "model": args.model,
        "temperature": args.temperature,
        "request_timeout_seconds": args.request_timeout_seconds,
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
        result = run_single_agentcollab_compact(
            repository_root=repository_root,
            agentcollab_repository=args.agentcollab_repo,
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
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "unexpected compaction-driver failure; no provider "
                        "payload or credential was printed"
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    print(
        json.dumps(
            {
                "ok": True,
                "purpose": PURPOSE,
                "analysis_eligible": ANALYSIS_ELIGIBLE,
                "condition_id": CONDITION_ID,
                "protocol_kind": PROTOCOL_KIND,
                "run_id": result.run_id,
                "task_id": result.task_id,
                "metric": result.metric,
                "diagnostic_score": result.diagnostic_score,
                "private_run_directory": str(result.run_directory),
                "ledger": str(result.ledger_path),
                "lifecycle_trace": str(result.trace_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
