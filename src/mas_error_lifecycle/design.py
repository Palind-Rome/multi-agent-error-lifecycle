"""Expand a compact TOML experiment matrix into immutable run assignments."""

from __future__ import annotations

import itertools
import json
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PlanItem:
    plan_version: str
    experiment: str
    task_id: str
    condition_id: str
    repeat: int
    seed: int
    factors: dict[str, Any]
    estimated_backbone_calls: int
    estimated_judge_calls: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_plan(path: str | Path) -> tuple[PlanItem, ...]:
    source = Path(path)
    with source.open("rb") as handle:
        config = tomllib.load(handle)
    experiment = config.get("experiment", {})
    factors = config.get("factors", {})
    name = str(experiment.get("name", "")).strip()
    tasks = experiment.get("tasks", [])
    repeats = experiment.get("repeats", 1)
    base_seed = experiment.get("base_seed", 0)
    backbone_calls = experiment.get("estimated_backbone_calls_per_run", 1)
    judge_calls = experiment.get("estimated_judge_calls_per_run", 0)
    if not name:
        raise ValueError("experiment.name must be non-empty")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("experiment.tasks must be a non-empty array")
    if not isinstance(repeats, int) or repeats < 1:
        raise ValueError("experiment.repeats must be a positive integer")
    if not isinstance(base_seed, int):
        raise ValueError("experiment.base_seed must be an integer")
    if not isinstance(factors, dict) or not factors:
        raise ValueError("factors must contain at least one factor")
    for factor_name, levels in factors.items():
        if not isinstance(levels, list) or not levels:
            raise ValueError(f"factors.{factor_name} must be a non-empty array")

    factor_names = sorted(factors)
    combinations = itertools.product(*(factors[name] for name in factor_names))
    items: list[PlanItem] = []
    ordinal = 0
    for levels in combinations:
        factor_values = dict(zip(factor_names, levels, strict=True))
        condition_id = "__".join(
            f"{_slug(name)}-{_slug(str(factor_values[name]))}" for name in factor_names
        )
        for task_id in tasks:
            for repeat in range(repeats):
                items.append(
                    PlanItem(
                        plan_version="0.1.0",
                        experiment=name,
                        task_id=str(task_id),
                        condition_id=condition_id,
                        repeat=repeat,
                        seed=base_seed + ordinal,
                        factors=factor_values,
                        estimated_backbone_calls=int(backbone_calls),
                        estimated_judge_calls=int(judge_calls),
                    )
                )
                ordinal += 1
    return tuple(items)


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
            handle.write(json.dumps(item.to_dict(), ensure_ascii=False, allow_nan=False))
            handle.write("\n")
    temporary.replace(destination)
    return destination


def plan_summary(items: tuple[PlanItem, ...]) -> dict[str, int]:
    return {
        "runs": len(items),
        "conditions": len({item.condition_id for item in items}),
        "tasks": len({item.task_id for item in items}),
        "estimated_backbone_calls": sum(item.estimated_backbone_calls for item in items),
        "estimated_judge_calls": sum(item.estimated_judge_calls for item in items),
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "empty"
