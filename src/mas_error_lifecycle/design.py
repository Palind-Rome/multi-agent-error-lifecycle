"""Expand a guarded TOML study design into paired immutable assignments."""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import re
import tomllib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable


IMPLEMENTED_FACTOR_BINDINGS = {
    "native_task_passthrough",
    "derived_topology_rewriter",
    "role_model_assignment",
    "governance_policy",
    "injection_variant",
    "source_position_assignment",
}
PLAN_VERSION = "0.3.0"
KNOWN_REVIEW_STATUSES = frozenset({"native", "not_required", "unvalidated"})
EXECUTABLE_REVIEW_STATUSES = frozenset({"native", "not_required"})


@dataclass(frozen=True, slots=True)
class PlanItem:
    plan_version: str
    benchmark_plugin: str
    plugin_version: str
    raw_schema_version: str
    experiment: str
    purpose: str
    protocol_kind: str
    suite_kind: str
    execution_status: str
    review_status: str
    analysis_eligible: bool
    task_id: str
    condition_id: str
    repeat: int
    pair_id: str
    cluster_id: str
    assignment_id: str
    run_id: str
    seed: int
    seed_supported: bool | None
    run_order: int
    factors: dict[str, Any]
    factor_bindings: dict[str, str]
    preregistration_hash: str | None
    native_task_hash: str | None
    estimated_backbone_calls: int | None
    estimated_judge_calls: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_plan(
    path: str | Path,
    *,
    allow_unready: bool = False,
) -> tuple[PlanItem, ...]:
    """Load assignments and refuse paused/unreviewed designs by default."""

    source = Path(path)
    with source.open("rb") as handle:
        config = tomllib.load(handle)
    experiment = config.get("experiment", {})
    factors = config.get("factors", {})
    factor_bindings = config.get("factor_bindings", {})

    name = str(experiment.get("name", "")).strip()
    purpose = str(experiment.get("purpose", "")).strip()
    protocol_kind = str(experiment.get("protocol_kind", "")).strip()
    suite_kind = str(experiment.get("suite_kind", "")).strip()
    execution_status = str(experiment.get("execution_status", "blocked")).strip()
    review_status = str(experiment.get("review_status", "unvalidated")).strip()
    analysis_eligible = experiment.get("analysis_eligible", False)
    tasks = experiment.get("tasks", [])
    repeats = experiment.get("repeats", 1)
    base_seed = experiment.get("base_seed", 0)
    run_order_seed = experiment.get("run_order_seed", base_seed)
    seed_supported = experiment.get("seed_supported")
    backbone_calls = experiment.get("estimated_backbone_calls_per_run")
    judge_calls = experiment.get("estimated_judge_calls_per_run")
    preregistration_hash = experiment.get("preregistration_hash")
    benchmark_plugin = experiment.get("benchmark_plugin")
    plugin_version = experiment.get("plugin_version")
    raw_schema_version = experiment.get("raw_schema_version")
    if not isinstance(benchmark_plugin, str) or not re.fullmatch(
        r"[a-z][a-z0-9_.-]{0,63}", benchmark_plugin
    ):
        raise ValueError(
            "experiment.benchmark_plugin must match "
            "[a-z][a-z0-9_.-]{0,63}"
        )
    for value, label in (
        (plugin_version, "experiment.plugin_version"),
        (raw_schema_version, "experiment.raw_schema_version"),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")

    for value, label in (
        (name, "experiment.name"),
        (purpose, "experiment.purpose"),
        (protocol_kind, "experiment.protocol_kind"),
        (suite_kind, "experiment.suite_kind"),
    ):
        if not value:
            raise ValueError(f"{label} must be non-empty")
    if execution_status not in {"ready", "paused", "blocked"}:
        raise ValueError("experiment.execution_status is invalid")
    if review_status not in KNOWN_REVIEW_STATUSES:
        raise ValueError("experiment.review_status is invalid")
    if not allow_unready and execution_status != "ready":
        raise ValueError(
            f"plan is {execution_status}; pass allow_unready=True only to preview it"
        )
    if not allow_unready and review_status not in EXECUTABLE_REVIEW_STATUSES:
        raise ValueError(
            "plan review_status is not executable; complete construct review"
        )
    if not isinstance(analysis_eligible, bool):
        raise ValueError("experiment.analysis_eligible must be boolean")
    if analysis_eligible and not _is_sha256(preregistration_hash):
        raise ValueError("analysis-eligible plan requires preregistration_hash")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("experiment.tasks must be a non-empty array")
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("experiment.repeats must be a positive integer")
    if not isinstance(base_seed, int) or not isinstance(run_order_seed, int):
        raise ValueError("base_seed and run_order_seed must be integers")
    if seed_supported is not None and not isinstance(seed_supported, bool):
        raise ValueError("experiment.seed_supported must be boolean or omitted")
    for value, label in (
        (backbone_calls, "estimated_backbone_calls_per_run"),
        (judge_calls, "estimated_judge_calls_per_run"),
    ):
        if value is not None and (not isinstance(value, int) or value < 0):
            raise ValueError(f"{label} must be a non-negative integer or omitted")
    if not isinstance(factors, dict) or not factors:
        raise ValueError("factors must contain at least one factor")
    if not isinstance(factor_bindings, dict):
        raise ValueError("factor_bindings must be an object")
    for factor_name, levels in factors.items():
        if not isinstance(levels, list) or not levels:
            raise ValueError(f"factors.{factor_name} must be a non-empty array")
        binding = factor_bindings.get(factor_name)
        if binding not in IMPLEMENTED_FACTOR_BINDINGS:
            raise ValueError(
                f"factor {factor_name!r} has no implemented binding; "
                f"got {binding!r}"
            )

    factor_names = sorted(factors)
    combinations = tuple(
        itertools.product(*(factors[name] for name in factor_names))
    )
    items: list[PlanItem] = []
    for levels in combinations:
        factor_values = dict(zip(factor_names, levels, strict=True))
        condition_id = "__".join(
            f"{_slug(name)}-{_slug(str(factor_values[name]))}"
            for name in factor_names
        )
        assignment_block = str(
            factor_values.get(
                "assignment_direction",
                factor_values.get("assignment", "default"),
            )
        )
        for task_id_raw in tasks:
            task_id = str(task_id_raw)
            for repeat in range(repeats):
                pair_id = _stable_id(
                    "pair", name, task_id, str(repeat), assignment_block
                )
                seed = _paired_seed(
                    base_seed, name, task_id, repeat, assignment_block
                )
                assignment_id = _stable_id(
                    "assignment", pair_id, condition_id
                )
                run_id = _stable_id("run", assignment_id)
                items.append(
                    PlanItem(
                        plan_version=PLAN_VERSION,
                        benchmark_plugin=benchmark_plugin,
                        plugin_version=plugin_version,
                        raw_schema_version=raw_schema_version,
                        experiment=name,
                        purpose=purpose,
                        protocol_kind=protocol_kind,
                        suite_kind=suite_kind,
                        execution_status=execution_status,
                        review_status=review_status,
                        analysis_eligible=analysis_eligible,
                        task_id=task_id,
                        condition_id=condition_id,
                        repeat=repeat,
                        pair_id=pair_id,
                        cluster_id=task_id,
                        assignment_id=assignment_id,
                        run_id=run_id,
                        seed=seed,
                        seed_supported=seed_supported,
                        run_order=-1,
                        factors=factor_values,
                        factor_bindings={
                            name: str(factor_bindings[name]) for name in factor_names
                        },
                        preregistration_hash=preregistration_hash,
                        native_task_hash=None,
                        estimated_backbone_calls=backbone_calls,
                        estimated_judge_calls=judge_calls,
                    )
                )

    rng = random.Random(run_order_seed)
    shuffled = list(items)
    rng.shuffle(shuffled)
    ordered = tuple(
        replace(item, run_order=index) for index, item in enumerate(shuffled)
    )
    if len({item.run_id for item in ordered}) != len(ordered):
        raise ValueError("plan generated duplicate run_id values")
    return ordered


def write_plan(
    path: str | Path, items: tuple[PlanItem, ...], *, overwrite: bool = False
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"{destination} already exists")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for item in items:
            handle.write(
                json.dumps(item.to_dict(), ensure_ascii=False, allow_nan=False)
            )
            handle.write("\n")
    temporary.replace(destination)
    return destination


def plan_summary(
    items: tuple[PlanItem, ...],
) -> dict[str, bool | int | str | None]:
    return {
        "runs": len(items),
        "conditions": len({item.condition_id for item in items}),
        "pairs": len({item.pair_id for item in items}),
        "tasks": len({item.task_id for item in items}),
        "purpose": items[0].purpose if items else None,
        "execution_status": items[0].execution_status if items else None,
        "analysis_eligible": bool(items) and all(
            item.analysis_eligible for item in items
        ),
        "estimated_backbone_calls": _sum_known(
            item.estimated_backbone_calls for item in items
        ),
        "estimated_judge_calls": _sum_known(
            item.estimated_judge_calls for item in items
        ),
    }


def _sum_known(values: Iterable[int | None]) -> int | None:
    rows = tuple(values)
    return sum(int(value) for value in rows if value is not None) if all(
        value is not None for value in rows
    ) else None


def _paired_seed(
    base_seed: int,
    experiment: str,
    task_id: str,
    repeat: int,
    assignment_block: str,
) -> int:
    digest = hashlib.sha256(
        f"{base_seed}:{experiment}:{task_id}:{repeat}:{assignment_block}".encode(
            "utf-8"
        )
    ).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}:{digest}"


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "empty"
