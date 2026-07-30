"""Small-sample estimates for paired experimental conditions."""

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

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def bootstrap_mean(
    values: Iterable[float],
    *,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> BootstrapEstimate:
    """Percentile bootstrap confidence interval for a mean."""

    observations = tuple(float(value) for value in values)
    _validate_bootstrap_args(observations, confidence, resamples)
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
    )


def paired_mean_difference(
    treatment: dict[str, float],
    control: dict[str, float],
    *,
    confidence: float = 0.95,
    resamples: int = 2_000,
    seed: int = 0,
) -> BootstrapEstimate:
    """Bootstrap paired treatment-control differences on shared run keys."""

    shared = sorted(set(treatment) & set(control))
    if not shared:
        raise ValueError("treatment and control have no shared pairing keys")
    differences = [float(treatment[key]) - float(control[key]) for key in shared]
    return bootstrap_mean(
        differences,
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )


def _validate_bootstrap_args(
    observations: tuple[float, ...], confidence: float, resamples: int
) -> None:
    if not observations:
        raise ValueError("at least one observation is required")
    if any(not math.isfinite(value) for value in observations):
        raise ValueError("observations must be finite")
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
