"""Offline multi-label calibration helpers for MAST-style trace annotation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Iterable


@dataclass(frozen=True, slots=True)
class LabelConfusion:
    label: str
    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int
    precision: float | None
    recall: float | None
    f1: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    examples: int
    labels: int
    exact_match_accuracy: float
    micro_precision: float | None
    micro_recall: float | None
    micro_f1: float | None
    macro_f1: float | None
    per_label: tuple[LabelConfusion, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "per_label": [item.to_dict() for item in self.per_label],
        }


def calibrate_multilabel(
    gold: dict[str, Iterable[str]],
    predicted: dict[str, Iterable[str]],
) -> CalibrationReport:
    """Compare a judge with a fixed human-labeled set without coercing unknowns."""

    if not gold:
        raise ValueError("gold annotations must be non-empty")
    if set(gold) != set(predicted):
        missing = sorted(set(gold) - set(predicted))
        extra = sorted(set(predicted) - set(gold))
        raise ValueError(
            f"annotation IDs differ; missing={missing}, extra={extra}"
        )
    gold_sets = {key: frozenset(values) for key, values in gold.items()}
    predicted_sets = {
        key: frozenset(values) for key, values in predicted.items()
    }
    labels = sorted(
        set().union(*gold_sets.values(), *predicted_sets.values())
    )
    confusions: list[LabelConfusion] = []
    total_tp = total_fp = total_fn = 0
    for label in labels:
        tp = sum(
            label in gold_sets[key] and label in predicted_sets[key]
            for key in gold_sets
        )
        fp = sum(
            label not in gold_sets[key] and label in predicted_sets[key]
            for key in gold_sets
        )
        fn = sum(
            label in gold_sets[key] and label not in predicted_sets[key]
            for key in gold_sets
        )
        tn = len(gold_sets) - tp - fp - fn
        precision = _rate(tp, tp + fp)
        recall = _rate(tp, tp + fn)
        f1 = _f1(precision, recall)
        confusions.append(
            LabelConfusion(
                label=label,
                true_positive=tp,
                false_positive=fp,
                false_negative=fn,
                true_negative=tn,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
        total_tp += tp
        total_fp += fp
        total_fn += fn
    micro_precision = _rate(total_tp, total_tp + total_fp)
    micro_recall = _rate(total_tp, total_tp + total_fn)
    macro_values = [item.f1 for item in confusions if item.f1 is not None]
    return CalibrationReport(
        examples=len(gold_sets),
        labels=len(labels),
        exact_match_accuracy=(
            sum(gold_sets[key] == predicted_sets[key] for key in gold_sets)
            / len(gold_sets)
        ),
        micro_precision=micro_precision,
        micro_recall=micro_recall,
        micro_f1=_f1(micro_precision, micro_recall),
        macro_f1=fmean(macro_values) if macro_values else None,
        per_label=tuple(confusions),
    )


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)
