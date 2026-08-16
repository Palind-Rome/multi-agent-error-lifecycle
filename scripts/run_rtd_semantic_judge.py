#!/usr/bin/env python3
"""LLM-judge semantic annotation for RTD compact-arm runs.

The benchmark's literal RTD score is string-only (see
``docs/rq1-rtd-findings.md``). This judge classifies each tracer's *semantic*
fate at two stages, per ``docs/rq1-annotation-guide.md``:

* transformation (the compaction summary) — preserved_correctly / omitted /
  distorted_or_contradicted / partial;
* downstream (the final answer) — correctly_reflected / mentioned_only /
  incorrectly_reflected / absent.

It uses the same provider (OpenAI-compatible) as the smoke driver; the API key
is read from stdin (``--api-key-stdin``) and never persisted. Output is a JSON
annotation bundle for human review.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True

PAPERBYPASS_BASE_URL = "https://aigateway.paperbypass.com/api/v1"
DEFAULT_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"

_JUDGE_PROMPT = """You are annotating whether a required fact survived a multi-agent handoff.

FACT:
{fact}

STAGE 1 — TRANSFORMATION (a compacted summary that should carry the fact):
{summary}

STAGE 2 — DOWNSTREAM (the final answer):
{final}

Classify the fact at each stage.
Transformation labels: preserved_correctly | omitted | distorted_or_contradicted | partial
Downstream labels: correctly_reflected | mentioned_only | incorrectly_reflected | absent
Use "uncertain" only if the rubric cannot decide.

Return ONLY a JSON object:
{{"transformation": "<label>", "downstream": "<label>", "evidence": "<short quote>"}}"""


def _anchors(task: dict) -> list[tuple[str, str]]:
    injection = task.get("injections", {}).get("rtd", {})
    multi = injection.get("multi_constraint")
    if isinstance(multi, dict) and isinstance(multi.get("constraints"), list):
        return [(c.get("tracer_id"), c.get("anchor")) for c in multi["constraints"]]
    anchor = injection.get("anchor")
    return [(injection.get("tracer_id"), anchor)] if anchor else []


def _first_summary(run_dir: Path) -> str:
    sidecar = run_dir / "compaction-summaries.jsonl"
    if not sidecar.is_file():
        return ""
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return json.loads(line).get("response_content", "")
    return ""


def _final_answer(run_dir: Path) -> str:
    trace = run_dir / "lifecycle-trace.jsonl"
    if not trace.is_file():
        return ""
    last = ""
    for line in trace.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("record_type") == "message":
            last = record.get("content", "")
    return last


def _judge(api_key: str, model: str, fact: str, summary: str, final: str) -> dict:
    prompt = _JUDGE_PROMPT.format(fact=fact, summary=summary[:6000], final=final[:6000])
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{PAPERBYPASS_BASE_URL}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        return {"transformation": "unknown", "downstream": "unknown",
                "evidence": f"judge_call_failed:{type(exc).__name__}"}
    content = payload["choices"][0]["message"]["content"]
    # The model may wrap the JSON in a code fence; strip it.
    content = content.strip().removeprefix("```json").removesuffix("```").strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"transformation": "unknown", "downstream": "unknown",
                "evidence": "judge_output_unparseable"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LLM-judge semantic annotation for one RTD compact run."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--api-key-stdin", action="store_true")
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sys.dont_write_bytecode = True
    task_file = (args.agentcollab_repo / "tasks" / f"{args.task_id}.json").resolve()
    if not task_file.is_file():
        print(json.dumps({"ok": False, "error": f"no task file {task_file}"}), file=sys.stderr)
        return 2
    task = json.loads(task_file.read_text(encoding="utf-8"))
    api_key = sys.stdin.readline().strip() if args.api_key_stdin else ""
    if not api_key:
        print(json.dumps({"ok": False, "error": "no API key on stdin"}), file=sys.stderr)
        return 2

    summary = _first_summary(args.run_dir)
    final = _final_answer(args.run_dir)
    tracers = []
    for tracer_id, anchor in _anchors(task):
        verdict = _judge(api_key, args.model, anchor, summary, final)
        tracers.append({
            "tracer_id": tracer_id,
            "anchor": anchor,
            "transformation": verdict.get("transformation", "unknown"),
            "downstream": verdict.get("downstream", "unknown"),
            "evidence": verdict.get("evidence", ""),
        })

    result = {
        "schema": "rq1-rtd-semantic-judge/1",
        "task_id": args.task_id,
        "run_id": args.run_dir.name,
        "judge_model": args.model,
        "tracers": tracers,
        "annotator": "llm-judge (pending human review)",
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "out": str(args.out)}))
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
