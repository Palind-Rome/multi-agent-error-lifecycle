#!/usr/bin/env python3
"""Deterministic tracer-survival analyzer for RTD compact-arm runs.

For each tracer anchor in a task, report *where* the anchor's key fragments
survive or vanish across three stages: the compaction summaries, the inter-agent
messages, and the final answer. This is the literal "surface" layer that
complements (and explains) the benchmark's single RTD score — it shows whether a
0.0 comes from the compaction step or from the downstream relay.

It reads only; it never writes into ``outputs/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _anchors(task: dict) -> list[tuple[str, str]]:
    injection = task.get("injections", {}).get("rtd", {})
    multi = injection.get("multi_constraint")
    if isinstance(multi, dict) and isinstance(multi.get("constraints"), list):
        return [(c.get("tracer_id"), c.get("anchor")) for c in multi["constraints"]]
    anchor = injection.get("anchor")
    return [(injection.get("tracer_id"), anchor)] if anchor else []


def _fragments(anchor: str) -> list[str]:
    """Heuristic key fragments: the precise/numeric tokens most likely to relax."""
    parts = anchor.split()
    frags: list[str] = []
    for i, tok in enumerate(parts):
        if any(ch.isdigit() for ch in tok):
            frags.append(tok)
    # Always include the full anchor as the strictest check.
    if anchor not in frags:
        frags.append(anchor)
    return frags


def _summaries(run_dir: Path) -> list[str]:
    sidecar = run_dir / "compaction-summaries.jsonl"
    if not sidecar.is_file():
        return []
    return [
        json.loads(line).get("response_content", "")
        for line in sidecar.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _messages(run_dir: Path) -> list[tuple[str, str]]:
    trace = run_dir / "lifecycle-trace.jsonl"
    if not trace.is_file():
        return []
    out: list[tuple[str, str]] = []
    for line in trace.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("record_type") == "message":
            out.append((record.get("source_agent_id", "?"), record.get("content", "")))
    return out


def analyze(run_dir: Path, task: dict) -> dict:
    anchors = _anchors(task)
    summaries = _summaries(run_dir)
    messages = _messages(run_dir)
    final_answer = messages[-1][1] if messages else ""

    rows = []
    for tracer_id, anchor in anchors:
        fragments = _fragments(anchor)
        summary_hits = {f: any(f in s for s in summaries) for f in fragments}
        relay_hits = {f: any(f in c for _, c in messages[:-1]) for f in fragments}
        final_hits = {f: f in final_answer for f in fragments}
        rows.append({
            "tracer_id": tracer_id,
            "anchor": anchor,
            "in_any_summary": any(summary_hits.values()),
            "in_any_relay": any(relay_hits.values()),
            "in_final": any(final_hits.values()),
            "fragments": fragments,
            "summary_hits": summary_hits,
            "relay_hits": relay_hits,
            "final_hits": final_hits,
        })
    return {
        "task_id": task.get("task_id"),
        "run_id": run_dir.name,
        "tracers": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report where each RTD tracer anchor survives (summary/relay/final)."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sys.dont_write_bytecode = True
    task_file = (args.agentcollab_repo / "tasks" / f"{args.task_id}.json").resolve()
    if not task_file.is_file():
        print(json.dumps({"ok": False, "error": f"no task file {task_file}"}), file=sys.stderr)
        return 2
    task = json.loads(task_file.read_text(encoding="utf-8"))
    result = analyze(args.run_dir, task)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
