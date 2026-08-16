#!/usr/bin/env python3
"""Propose additional AgentCollabBench tasks for the reviewed allowlist.

The engineering-smoke allowlist (``APPROVED_RTD_TASKS`` / ``APPROVED_CPR_TASKS``
in ``agentcollab_smoke.py``) is a *security control*: every task it names is
pinned by SHA-256 and only those exact bytes ever execute. Expanding the sample
for RQ1/RQ2 therefore must stay a human-reviewed step, not a bulk import.

This script does the mechanical part of that review:

* enumerates single-metric tasks (``metric_applicability == [metric]``) that
  match optional domain / agent-count / topology filters;
* for each candidate, records the structural shape a reviewer needs to judge it
  (domain, agent count, topology type, tracer count, constraint type, salience)
  and the SHA-256 of the exact on-disk bytes;
* reports how much of the (domain x agent-count x topology) space the *current*
  allowlist already covers, so the reviewer can fill uncovered cells first;
* writes a proposal JSON plus a ``ready_to_paste`` dict literal for the subset
  the reviewer approves.

It never edits ``agentcollab_smoke.py`` and never touches ``outputs/``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True

# ── allowlist reflection ────────────────────────────────────────────────────
_SMOKE_MODULE = "mas_error_lifecycle/adapters/agentcollab_smoke.py"
_ALLOWLIST_NAMES = {"rtd": "APPROVED_RTD_TASKS", "cpr": "APPROVED_CPR_TASKS"}
_TOPOLOGIES = ("linear_chain", "branching_tree", "converging_dag",
               "fully_connected", "custom_graph")


def _existing_allowlist(repository_root: Path, metric: str) -> dict[str, str]:
    """Read the current allowlist dict straight out of the source file."""
    source = (repository_root / "src" / _SMOKE_MODULE).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == _ALLOWLIST_NAMES[metric]:
                value = ast.literal_eval(node.value)
                if not isinstance(value, dict):
                    raise SystemExit(f"{_ALLOWLIST_NAMES[metric]} is not a dict literal")
                return dict(value)
    raise SystemExit(f"could not find {_ALLOWLIST_NAMES[metric]} in {_SMOKE_MODULE}")


# ── task introspection ──────────────────────────────────────────────────────
def _tracer_count(metric: str, task: dict) -> int:
    injection = task.get("injections", {}).get(metric, {})
    if metric == "rtd":
        multi = injection.get("multi_constraint")
        if isinstance(multi, dict) and isinstance(multi.get("constraints"), list):
            return len(multi["constraints"])
        return 1 if injection.get("anchor") else 0
    if metric == "cpr":
        # A CPR task carries exactly one false_fact / ground_truth pair.
        return 1 if injection.get("false_fact") else 0
    return 0


def _constraint_type(metric: str, task: dict) -> str:
    injection = task.get("injections", {}).get(metric, {})
    return str(injection.get("constraint_type", "n/a"))


def _salience(metric: str, task: dict) -> str:
    injection = task.get("injections", {}).get(metric, {})
    return str(injection.get("salience", "n/a"))


def _tracer_ids(metric: str, task: dict) -> list[str]:
    injection = task.get("injections", {}).get(metric, {})
    if metric == "rtd":
        multi = injection.get("multi_constraint")
        if isinstance(multi, dict) and isinstance(multi.get("constraints"), list):
            return [str(c.get("tracer_id")) for c in multi["constraints"]]
        tid = injection.get("tracer_id")
        return [str(tid)] if tid else []
    return []


def _seed_agent(task: dict) -> str:
    injection = task.get("injections", {}).get("cpr", {})
    return str(injection.get("seed_agent", "n/a"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_single_metric_tasks(tasks_dir: Path, metric: str):
    for path in sorted(tasks_dir.glob("*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        if task.get("metric_applicability") != [metric]:
            continue
        yield path, task


def _cell(task: dict) -> tuple[str, int, str]:
    return (
        str(task.get("domain", "unknown")),
        len(task.get("topology", {}).get("agents", [])),
        str(task.get("topology", {}).get("type", "unknown")),
    )


# ── main ────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Propose reviewed AgentCollabBench allowlist additions."
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--metric", required=True, choices=sorted(_ALLOWLIST_NAMES))
    parser.add_argument("--min-agents", type=int, default=3)
    parser.add_argument("--max-agents", type=int, default=6)
    parser.add_argument("--domains", nargs="*", help="e.g. data_engineering devops swe")
    parser.add_argument("--topologies", nargs="*", choices=_TOPOLOGIES)
    parser.add_argument("--require-tracers", type=int, default=1,
                        help="only keep tasks with at least this many tracers")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[1]
    tasks_dir = (args.agentcollab_repo / "tasks").resolve()
    if not tasks_dir.is_dir():
        print(json.dumps({"ok": False, "error": f"no tasks/ under {args.agentcollab_repo}"}),
              file=sys.stderr)
        return 2
    if args.out.exists() and not args.force:
        print(json.dumps({"ok": False, "error": f"{args.out} exists; pass --force"}),
              file=sys.stderr)
        return 2

    existing = _existing_allowlist(repository_root, args.metric)

    candidates: list[dict[str, object]] = []
    all_cells: set[tuple[str, int, str]] = set()

    for path, task in _iter_single_metric_tasks(tasks_dir, args.metric):
        cell = _cell(task)
        all_cells.add(cell)
        if task.get("task_id") in existing:
            continue  # already reviewed and pinned; only propose additions
        n_agents = len(task.get("topology", {}).get("agents", []))
        n_tracers = _tracer_count(args.metric, task)
        if n_agents < args.min_agents or n_agents > args.max_agents:
            continue
        if args.domains and task.get("domain") not in args.domains:
            continue
        if args.topologies and task.get("topology", {}).get("type") not in args.topologies:
            continue
        if n_tracers < args.require_tracers:
            continue
        candidate = {
            "task_id": task.get("task_id"),
            "filename": path.name,
            "sha256": _sha256(path),
            "domain": task.get("domain"),
            "n_agents": n_agents,
            "topology": task.get("topology", {}).get("type"),
            "n_tracers": n_tracers,
        }
        if args.metric == "rtd":
            candidate["constraint_type"] = _constraint_type(args.metric, task)
            candidate["salience"] = _salience(args.metric, task)
            candidate["tracer_ids"] = _tracer_ids(args.metric, task)
        else:
            candidate["seed_agent"] = _seed_agent(task)
        candidates.append(candidate)

    # Which cells does the *current* allowlist already occupy?
    existing_cells: set[tuple[str, int, str]] = set()
    for path, task in _iter_single_metric_tasks(tasks_dir, args.metric):
        if task.get("task_id") in existing:
            existing_cells.add(_cell(task))

    # Candidates in uncovered cells first (the reviewer should fill gaps).
    def _candidate_cell(c: dict[str, object]) -> tuple[str, int, str]:
        return (str(c["domain"]), int(c["n_agents"]), str(c["topology"]))

    candidates.sort(key=lambda c: (
        _candidate_cell(c) in existing_cells,  # False (uncovered) sorts first
        str(c["domain"]), str(c["n_agents"]), str(c["topology"]), str(c["task_id"]),
    ))

    proposal = {
        "ok": True,
        "metric": args.metric,
        "purpose": "reviewed allowlist expansion — NOT auto-applied",
        "source_dir": str(tasks_dir),
        "filters": {
            "min_agents": args.min_agents,
            "max_agents": args.max_agents,
            "domains": args.domains,
            "topologies": args.topologies,
            "require_tracers": args.require_tracers,
        },
        "existing_allowlist_size": len(existing),
        "existing_coverage": {
            "n_cells": len(existing_cells),
            "cells": sorted(f"{d}/{n}/{t}" for d, n, t in existing_cells),
        },
        "candidate_count": len(candidates),
        "uncovered_cell_candidates": sum(
            1 for c in candidates if _candidate_cell(c) not in existing_cells
        ),
        "candidates": candidates,
        "ready_to_paste": {c["task_id"]: c["sha256"] for c in candidates},
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    tmp.write_text(json.dumps(proposal, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(args.out)

    # Human-readable summary to stdout (the JSON is the durable artifact).
    uncovered = [c for c in candidates if _candidate_cell(c) not in existing_cells]
    print(f"metric={args.metric}  existing={len(existing)}  candidates={len(candidates)}  "
          f"uncovered-cell={len(uncovered)}")
    print("existing cells:", ", ".join(sorted(f"{d}/{n}/{t}" for d, n, t in existing_cells)))
    if uncovered:
        print("first uncovered-cell candidates (fill these gaps):")
        for c in uncovered[:20]:
            line = (f"  {c['task_id']}  {c['domain']}/{c['n_agents']}/{c['topology']}  "
                    f"tracers={c['n_tracers']}")
            if args.metric == "rtd":
                line += f"  {c['constraint_type']}/{c['salience']}"
            else:
                line += f"  seed={c['seed_agent']}"
            print(line)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
