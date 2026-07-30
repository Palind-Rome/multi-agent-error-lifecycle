"""Paired, cluster-aware small-sample summaries with explicit missingness."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Iterable


@dataclass(frozen=True, slots=True)
class BootstrapEstimate:
    n: int
    estimate: float
    confidence: float
    lower: float
    upper: float
    inference_eligible: bool = True

    def to_dict(self) -> dict[str, int | float | bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class PairingAudit:
    planned: int
    observed_treatment: int
    observed_control: int
    paired: int
    missing_treatment: tuple[str, ...]
    missing_control: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_treatment and not self.missing_control

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "missing_treatment": list(self.missing_treatment),
            "missing_control": list(self.missing_control),
            "complete": self.complete,
        }


def descriptive_mean(values: Iterable[float]) -> BootstrapEstimate:
    """Return a point estimate explicitly marked as non-inferential."""

    observations = _observations(values)
    estimate = fmean(observations)
    return BootstrapEstimate(
        n=len(observations),
        estimate=estimate,
        confidence=0.0,
        lower=estimate,
        upper=estimate,
        inference_eligible=False,
    )


def bootstrap_mean(
    values: Iterable[float],
    *,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> BootstrapEstimate:
    """Percentile bootstrap CI; a singleton smoke is intentionally rejected."""

    observations = _observations(values)
    _validate_bootstrap_args(observations, confidence, resamples)
    if len(observations) < 2:
        raise ValueError(
            "at least two independent clusters are required for an inferential CI; "
            "use descriptive_mean for an engineering smoke"
        )
    rng = random.Random(seed)
    n = len(observations)
    samples = sorted(
        fmean(observations[rng.randrange(n)] for _ in range(n))
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    return BootstrapEstimate(
        n=n,
        estimate=fmean(observations),
        confidence=confidence,
        lower=_quantile(samples, alpha),
        upper=_quantile(samples, 1.0 - alpha),
        inference_eligible=True,
    )


def audit_pairs(
    planned_keys: Iterable[str],
    treatment_keys: Iterable[str],
    control_keys: Iterable[str],
) -> PairingAudit:
    planned = set(planned_keys)
    treatment = set(treatment_keys)
    control = set(control_keys)
    return PairingAudit(
        planned=len(planned),
        observed_treatment=len(treatment & planned),
        observed_control=len(control & planned),
        paired=len(planned & treatment & control),
        missing_treatment=tuple(sorted(planned - treatment)),
        missing_control=tuple(sorted(planned - control)),
    )


def paired_mean_difference(
    treatment: dict[str, float],
    control: dict[str, float],
    *,
    planned_keys: Iterable[str] | None = None,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> BootstrapEstimate:
    """Bootstrap paired differences and refuse silent complete-case deletion."""

    planned = (
        set(planned_keys)
        if planned_keys is not None
        else set(treatment) | set(control)
    )
    audit = audit_pairs(planned, treatment, control)
    if not audit.complete:
        raise ValueError(
            "paired contrast has missing cells: "
            f"missing treatment={list(audit.missing_treatment)}, "
            f"missing control={list(audit.missing_control)}"
        )
    keys = sorted(planned)
    differences = [float(treatment[key]) - float(control[key]) for key in keys]
    return bootstrap_mean(
        differences,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )


def paired_cluster_mean_difference(
    treatment: dict[str, Iterable[float]],
    control: dict[str, Iterable[float]],
    *,
    planned_clusters: Iterable[str] | None = None,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> BootstrapEstimate:
    """Aggregate within cluster, then resample clusters as the independent unit."""

    planned = (
        set(planned_clusters)
        if planned_clusters is not None
        else set(treatment) | set(control)
    )
    audit = audit_pairs(planned, treatment, control)
    if not audit.complete:
        raise ValueError(
            "cluster-paired contrast has missing cells: "
            f"missing treatment={list(audit.missing_treatment)}, "
            f"missing control={list(audit.missing_control)}"
        )
    differences = []
    for cluster_id in sorted(planned):
        treatment_values = _observations(treatment[cluster_id])
        control_values = _observations(control[cluster_id])
        differences.append(fmean(treatment_values) - fmean(control_values))
    return bootstrap_mean(
        differences,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )


def _observations(values: Iterable[float]) -> tuple[float, ...]:
    observations = tuple(float(value) for value in values)
    if not observations:
        raise ValueError("at least one observation is required")
    if any(not math.isfinite(value) for value in observations):
        raise ValueError("observations must be finite")
    return observations


def _validate_bootstrap_args(
    observations: tuple[float, ...], confidence: float, resamples: int
) -> None:
    if not observations:
        raise ValueError("at least one observation is required")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if resamples < 100:
        raise ValueError("resamples must be at least 100")


def _quantile(sorted_values: list[float], probability: float) -> float:
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
