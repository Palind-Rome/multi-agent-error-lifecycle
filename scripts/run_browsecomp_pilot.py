#!/usr/bin/env python3
"""Run the 3-agent BrowseComp relay over a small number of decrypted questions.

Reads the model key and the Tavily key on two stdin lines (never persisted),
loads the decrypted BrowseComp cache, and runs Searcher -> Synthesizer ->
Verifier on the first ``--n`` questions. Each run's trace + final answer is
appended as one JSONL record to ``outputs/browsecomp-run-<timestamp>.jsonl``
(git-ignored).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.browsecomp_loader import load_browsecomp
from mas_error_lifecycle.adapters.browsecomp_runner import (
    BrowseCompRunnerError,
    run_browsecomp_question,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the BrowseComp MAS pilot.")
    parser.add_argument("--n", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="qwen/qwen3-30b-a3b-instruct-2507")
    parser.add_argument("--skip", type=int, default=0, help="skip the first N questions")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sys.dont_write_bytecode = True
    model_key = sys.stdin.readline().strip()
    tavily_key = sys.stdin.readline().strip()
    if not model_key or not tavily_key:
        print(json.dumps({"ok": False, "error": "need model key + tavily key on stdin"}),
              file=sys.stderr)
        return 2

    data = load_browsecomp()
    selected = data[args.skip: args.skip + args.n]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for i, item in enumerate(selected):
        question = item["question"]
        try:
            run = run_browsecomp_question(
                question=question, model_key=model_key, tavily_key=tavily_key,
                model=args.model,
            )
            record = {"source_row": item["source_row"], "question": question,
                      "true_answer": item["answer"], "final": run["final"],
                      "findings": run["findings"], "answer": run["answer"],
                      "trace": run["trace"], "ok": True}
        except BrowseCompRunnerError as exc:
            record = {"source_row": item["source_row"], "question": question,
                      "true_answer": item["answer"], "ok": False, "error": str(exc)}
        results.append(record)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps({"i": i + 1, "source_row": item["source_row"],
                          "ok": record["ok"],
                          "final": (record.get("final") or "")[:80]},
                         ensure_ascii=False), flush=True)

    print(json.dumps({"ok": True, "n": len(results), "out": str(args.out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
