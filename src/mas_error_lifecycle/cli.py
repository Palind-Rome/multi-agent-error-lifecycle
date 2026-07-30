"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .adapters import (
    convert_agentcollab_result,
    generate_agentcollab_derived_counterfactual,
)
from .design import load_plan, plan_summary, write_plan
from .metrics import compute_metrics
from .runner import MockRunConfig, run_mock
from .store import TraceValidationError, load_trace, write_trace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masel",
        description="Instrument and measure multi-agent error lifecycles.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="write a deterministic mock trace")
    demo.add_argument("--out", required=True, type=Path)
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument(
        "--topology",
        choices=["chain", "broadcast_star", "converging_dag"],
        default="converging_dag",
    )
    demo.add_argument(
        "--verification",
        choices=["none", "selective", "evidence_required"],
        default="evidence_required",
    )
    demo.add_argument("--adoption-probability", type=float, default=0.8)
    demo.add_argument("--verification-accuracy", type=float, default=0.9)
    demo.add_argument(
        "--verification-timing",
        choices=["pre_adoption", "post_adoption"],
        default="post_adoption",
    )
    demo.add_argument(
        "--governance-action",
        choices=["none", "contain", "rollback"],
    )
    demo.add_argument("--force", action="store_true")

    validate = subparsers.add_parser("validate", help="validate a lifecycle JSONL trace")
    validate.add_argument("trace", type=Path)

    summarize = subparsers.add_parser(
        "summarize", help="compute mechanism, outcome, and cost metrics"
    )
    summarize.add_argument("trace", type=Path)
    summarize.add_argument("--compact", action="store_true")

    plan = subparsers.add_parser("plan", help="expand a TOML pilot matrix")
    plan.add_argument("config", type=Path)
    plan.add_argument("--out", required=True, type=Path)
    plan.add_argument(
        "--allow-unready",
        action="store_true",
        help="preview a paused/blocked plan; does not make it executable",
    )
    plan.add_argument("--force", action="store_true")

    adapter = subparsers.add_parser(
        "import-agentcollab", help="convert a full AgentCollabBench result"
    )
    adapter.add_argument("input", type=Path)
    adapter.add_argument("--out", required=True, type=Path)
    adapter.add_argument(
        "--run-context",
        type=Path,
        help="JSON PlanItem/run context; absent imports are observational only",
    )
    adapter.add_argument("--force", action="store_true")

    rewrite = subparsers.add_parser(
        "derive-agentcollab",
        help="create an unvalidated AgentCollabBench-derived stress variant",
    )
    rewrite.add_argument("input", type=Path)
    rewrite.add_argument(
        "--topology",
        required=True,
        choices=[
            "chain",
            "broadcast_star",
            "converging_dag",
            "fully_connected_dag",
        ],
    )
    rewrite.add_argument("--out", required=True, type=Path)
    rewrite.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            bundle = run_mock(
                MockRunConfig(
                    seed=args.seed,
                    topology=args.topology,
                    verification=args.verification,
                    verification_timing=args.verification_timing,
                    governance_action=(
                        args.governance_action
                        or ("none" if args.verification == "none" else "rollback")
                    ),
                    adoption_probability=args.adoption_probability,
                    verification_accuracy=args.verification_accuracy,
                )
            )
            write_trace(args.out, bundle, overwrite=args.force)
            _print_json(
                {
                    "ok": True,
                    "trace": str(args.out),
                    "metrics": compute_metrics(bundle).to_dict(),
                }
            )
            return 0
        if args.command == "validate":
            bundle = load_trace(args.trace)
            _print_json(
                {
                    "ok": True,
                    "trace": str(args.trace),
                    "run_id": bundle.manifest.run_id,
                    "artifacts": len(bundle.artifacts),
                    "prompts": len(bundle.prompts),
                    "events": len(bundle.events),
                }
            )
            return 0
        if args.command == "summarize":
            metrics = compute_metrics(load_trace(args.trace)).to_dict()
            print(
                json.dumps(
                    metrics,
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=None if args.compact else 2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "plan":
            items = load_plan(args.config, allow_unready=args.allow_unready)
            write_plan(args.out, items, overwrite=args.force)
            _print_json({"ok": True, "plan": str(args.out), **plan_summary(items)})
            return 0
        if args.command == "import-agentcollab":
            with args.input.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("input must be a JSON object")
            run_context = None
            if args.run_context:
                with args.run_context.open(encoding="utf-8") as handle:
                    run_context = json.load(handle)
                if not isinstance(run_context, dict):
                    raise ValueError("run context must be a JSON object")
            bundle = convert_agentcollab_result(payload, run_context=run_context)
            write_trace(args.out, bundle, overwrite=args.force)
            _print_json(
                {
                    "ok": True,
                    "trace": str(args.out),
                    "metrics": compute_metrics(bundle).to_dict(),
                }
            )
            return 0
        if args.command == "derive-agentcollab":
            with args.input.open(encoding="utf-8") as handle:
                task = json.load(handle)
            if not isinstance(task, dict):
                raise ValueError("input must be a JSON object")
            rewritten = generate_agentcollab_derived_counterfactual(
                task, args.topology
            )
            _write_json_file(args.out, rewritten, overwrite=args.force)
            _print_json(
                {
                    "ok": True,
                    "task_id": rewritten["task_id"],
                    "topology": args.topology,
                    "out": str(args.out),
                }
            )
            return 0
    except (
        FileExistsError,
        FileNotFoundError,
        json.JSONDecodeError,
        TraceValidationError,
        ValueError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    parser.error(f"unsupported command {args.command}")
    return 2


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True))


def _write_json_file(path: Path, value: object, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.write("\n")
    temporary.replace(path)
