#!/usr/bin/env python3
"""Select a deterministic, stratified AgentCollabBench pilot subset."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("tasks_dir", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--per-cell", type=int, default=1)
    parser.add_argument("--min-agents", type=int, default=4)
    parser.add_argument("--metrics", nargs="+", default=["rtd", "cpr"])
    parser.add_argument(
        "--allow-multi-metric",
        action="store_true",
        help="include tasks whose metric_applicability contains multiple probes",
    )
    parser.add_argument(
        "--topologies",
        nargs="+",
        default=["linear_chain", "converging_dag", "fully_connected"],
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.per_cell < 1:
        raise SystemExit("--per-cell must be positive")
    if args.out.exists() and not args.force:
        raise SystemExit(f"{args.out} already exists; pass --force to replace")
    cells: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(args.tasks_dir.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            task = json.load(handle)
        topology = task.get("topology", {}).get("type")
        if len(task.get("topology", {}).get("agents", [])) < args.min_agents:
            continue
        complexity = task.get("structural_complexity", "unknown")
        metrics = task.get("metric_applicability", [])
        if len(metrics) != 1 and not args.allow_multi_metric:
            continue
        for metric in args.metrics:
            if metric in metrics and topology in args.topologies:
                cells[(metric, str(topology), str(complexity))].append(
                    {
                        "task_id": task.get("task_id"),
                        "domain": task.get("domain"),
                        "metric": metric,
                        "topology": topology,
                        "complexity": complexity,
                        "filename": path.name,
                    }
                )

    rng = random.Random(args.seed)
    selected: list[dict[str, Any]] = []
    for cell_index, (cell, candidates) in enumerate(sorted(cells.items())):
        by_domain: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for candidate in candidates:
            by_domain[str(candidate["domain"])].append(candidate)
        for domain_candidates in by_domain.values():
            rng.shuffle(domain_candidates)
        domains = sorted(by_domain)
        for index in range(args.per_cell):
            domain = domains[(cell_index + index) % len(domains)]
            if by_domain[domain]:
                selected.append(by_domain[domain].pop())
            else:
                remaining = [
                    item for candidates_for_domain in by_domain.values()
                    for item in candidates_for_domain
                ]
                if remaining:
                    selected.append(rng.choice(remaining))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "selection_version": "0.1.0",
                "seed": args.seed,
                "per_cell": args.per_cell,
                "min_agents": args.min_agents,
                "requested_metrics": args.metrics,
                "requested_topologies": args.topologies,
                "count": len(selected),
                "tasks": selected,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    temporary.replace(args.out)
    print(json.dumps({"ok": True, "count": len(selected), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
