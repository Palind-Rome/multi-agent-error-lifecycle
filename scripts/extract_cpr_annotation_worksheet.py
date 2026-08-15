#!/usr/bin/env python3
"""Build an RQ2 (CPR) annotation worksheet from one completed CPR run.

RQ2 asks how *wrong* information propagates. The benchmark's own CPR score is
keyword-based and literal-only (see ``docs/rq2-cpr-findings.md``), so the
semantic layer (adopted / rejected / surfaced-only) is annotated by a human or
LLM-judge. That judgment is slow to do from raw ``lifecycle-trace.jsonl``, so
this script pre-extracts everything deterministic and lays it out turn by turn:

* ``false_fact`` / ``ground_truth`` / ``seed_agent`` from the task JSON;
* the keyword CPR score + per-turn "polluted" flags from the ``outcome`` record;
* each agent turn (who said what, at which step) from the ``message`` records;
* per turn, whether the false fact *textually* surfaced (from the trace's own
  deterministic ``surface-proxy`` annotations), with the matched evidence span.

The worksheet leaves the semantic fields (``semantic_stance`` per turn and the
``final_outcome`` / ``propagated_past_seed`` / ``pattern`` summary) empty for a
judge to fill in. It reads only; it never writes into ``outputs/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

_SURFACE_PROXY_TAXONOMY = "surface-proxy"


def _records(trace_path: Path):
    with trace_path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _find(records, record_type: str):
    for record in records:
        if record.get("record_type") == record_type:
            yield record


def _surfaced_spans(records) -> dict[str, list[str]]:
    """Map agent_id -> evidence spans from deterministic surface-proxy notes."""
    spans: dict[str, list[str]] = {}
    for record in _find(records, "annotation"):
        if record.get("taxonomy") != _SURFACE_PROXY_TAXONOMY:
            continue
        agent_id = record.get("agent_id", "?")
        for span in record.get("evidence_spans", []):
            spans.setdefault(agent_id, []).append(span)
    return spans


def _turn_surfaced(content: str, spans: list[str]) -> str | None:
    for span in spans:
        if span and span in content:
            return span
    return None


def build_worksheet(*, run_dir: Path, task: dict) -> dict:
    trace_path = run_dir / "lifecycle-trace.jsonl"
    if not trace_path.is_file():
        raise SystemExit(f"no lifecycle-trace.jsonl in {run_dir}")

    records = list(_records(trace_path))
    injections = task.get("injections", {}).get("cpr", {})
    false_fact = injections.get("false_fact", "")
    ground_truth = injections.get("ground_truth", "")
    seed_agent = injections.get("seed_agent", "")

    # Deterministic CPR keyword score + per-turn polluted flags.
    keyword_cpr: float | None = None
    polluted_turns: list[dict] = []
    for outcome in _find(records, "outcome"):
        evaluation = outcome.get("details", {}).get("detailed_evaluation", {})
        if "cpr_score" in evaluation:
            keyword_cpr = evaluation.get("cpr_score")
        polluted_turns = evaluation.get("turn_results", [])

    spans = _surfaced_spans(records)

    turns: list[dict] = []
    for message in _find(records, "message"):
        agent_id = message.get("source_agent_id", "?")
        content = message.get("content", "")
        span = _turn_surfaced(content, spans.get(agent_id, []))
        turns.append({
            "agent_id": agent_id,
            "target_agent_id": message.get("target_agent_id"),
            "sent_step": message.get("sent_step"),
            "content": content,
            "surfaced_false_fact": span is not None,
            "evidence_span": span,
            "semantic_stance": None,  # judge fills: adopted/rejected/surfaced_only/no_mention
        })

    return {
        "schema": "rq2-cpr-annotation-worksheet/1",
        "task_id": task.get("task_id"),
        "run_id": run_dir.name,
        "seed_agent": seed_agent,
        "false_fact": false_fact,
        "ground_truth": ground_truth,
        "keyword_cpr": keyword_cpr,
        "polluted_turns": polluted_turns,
        "turns": turns,
        # Judge fills these three from the turns above.
        "to_judge": {
            "final_outcome": None,      # ground_truth_wins / false_fact_wins / contaminated / unobservable
            "propagated_past_seed": None,
            "pattern": None,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an RQ2 CPR annotation worksheet from one completed run."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="write JSON here (default: stdout)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sys.dont_write_bytecode = True
    run_dir = args.run_dir.resolve()
    trace_path = run_dir / "lifecycle-trace.jsonl"
    if not trace_path.is_file():
        print(json.dumps({"ok": False, "error": f"no trace in {run_dir}"}), file=sys.stderr)
        return 2

    manifest = next(_find(_records(trace_path), "run_manifest"), None)
    if manifest is None:
        print(json.dumps({"ok": False, "error": "no run_manifest in trace"}), file=sys.stderr)
        return 2
    task_id = manifest.get("task_id")
    task_file = (args.agentcollab_repo / "tasks" / f"{task_id}.json").resolve()
    if not task_file.is_file():
        print(json.dumps({"ok": False, "error": f"no task file {task_file}"}), file=sys.stderr)
        return 2
    task = json.loads(task_file.read_text(encoding="utf-8"))

    worksheet = build_worksheet(run_dir=run_dir, task=task)
    rendered = json.dumps(worksheet, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "out": str(args.out)}))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
