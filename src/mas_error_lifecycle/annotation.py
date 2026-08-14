"""Offline multi-label calibration helpers for MAST-style trace annotation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from statistics import fmean
from typing import Any, Iterable

from .schema import AnnotationRecord


class RQ1FactAnnotationStage(StrEnum):
    TRANSFORMATION_OUTPUT = "transformation_output"
    DOWNSTREAM_OUTPUT = "downstream_output"


class RQ1FactAnnotationStatus(StrEnum):
    # Transformation-output rubric.
    PRESERVED_CORRECTLY = "preserved_correctly"
    OMITTED = "omitted"
    DISTORTED_OR_CONTRADICTED = "distorted_or_contradicted"
    PARTIAL = "partial"
    # Downstream-output rubric.
    CORRECTLY_REFLECTED = "correctly_reflected"
    MENTIONED_ONLY = "mentioned_only"
    INCORRECTLY_REFLECTED = "incorrectly_reflected"
    ABSENT = "absent"
    # Non-binary outcomes allowed at either stage.
    UNCERTAIN = "uncertain"
    UNKNOWN = "unknown"
    UNOBSERVABLE = "unobservable"


class RQ1FactObservationStatus(StrEnum):
    COMPLETE_VALID = "complete_valid"
    MISSING = "missing"
    INVALID = "invalid"
    PROVIDER_ERROR = "provider_error"
    SETUP_ERROR = "setup_error"
    TRACE_INCOMPLETE = "trace_incomplete"


RQ1_FACT_ANNOTATION_TAXONOMY = "rq1-required-fact"
RQ1_FACT_ANNOTATION_VERSION = "1.0.0"

_RQ1_NONBINARY_STATUSES = {
    RQ1FactAnnotationStatus.UNCERTAIN,
    RQ1FactAnnotationStatus.UNKNOWN,
    RQ1FactAnnotationStatus.UNOBSERVABLE,
}
_RQ1_ALLOWED_STATUSES = {
    RQ1FactAnnotationStage.TRANSFORMATION_OUTPUT: {
        RQ1FactAnnotationStatus.PRESERVED_CORRECTLY,
        RQ1FactAnnotationStatus.OMITTED,
        RQ1FactAnnotationStatus.DISTORTED_OR_CONTRADICTED,
        RQ1FactAnnotationStatus.PARTIAL,
        *_RQ1_NONBINARY_STATUSES,
    },
    RQ1FactAnnotationStage.DOWNSTREAM_OUTPUT: {
        RQ1FactAnnotationStatus.CORRECTLY_REFLECTED,
        RQ1FactAnnotationStatus.MENTIONED_ONLY,
        RQ1FactAnnotationStatus.INCORRECTLY_REFLECTED,
        RQ1FactAnnotationStatus.ABSENT,
        *_RQ1_NONBINARY_STATUSES,
    },
}
_RQ1_SUCCESS_STATUS = {
    RQ1FactAnnotationStage.TRANSFORMATION_OUTPUT: (
        RQ1FactAnnotationStatus.PRESERVED_CORRECTLY
    ),
    RQ1FactAnnotationStage.DOWNSTREAM_OUTPUT: (
        RQ1FactAnnotationStatus.CORRECTLY_REFLECTED
    ),
}


@dataclass(frozen=True, slots=True)
class RQ1FactAnnotation:
    """Typed fact-level judgment carried by a normal AnnotationRecord."""

    contract_type = "rq1_fact_annotation"

    annotation_id: str
    run_id: str
    transformation_id: str
    fact_id: str
    stage: RQ1FactAnnotationStage
    status: RQ1FactAnnotationStatus
    observation_status: RQ1FactObservationStatus
    target_event_ids: tuple[str, ...]
    annotator: str
    evidence_spans: tuple[str, ...] = ()
    blind_fields: tuple[str, ...] = ()
    confidence: float | None = None
    adjudication: str | None = None
    metadata: dict[str, Any] | None = None

    def validate(self) -> None:
        for name in (
            "annotation_id",
            "run_id",
            "transformation_id",
            "fact_id",
            "annotator",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"RQ1 fact annotation {name} must be non-empty")
        if not isinstance(self.stage, RQ1FactAnnotationStage):
            raise ValueError("RQ1 fact annotation stage is invalid")
        if not isinstance(self.status, RQ1FactAnnotationStatus):
            raise ValueError("RQ1 fact annotation status is invalid")
        if not isinstance(self.observation_status, RQ1FactObservationStatus):
            raise ValueError("RQ1 fact annotation observation_status is invalid")
        if self.status not in _RQ1_ALLOWED_STATUSES[self.stage]:
            raise ValueError(
                f"status {self.status.value} is not allowed for stage "
                f"{self.stage.value}"
            )
        if not self.target_event_ids or len(set(self.target_event_ids)) != len(
            self.target_event_ids
        ):
            raise ValueError(
                "RQ1 fact annotation target_event_ids must be non-empty and unique"
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("RQ1 fact annotation confidence must be in [0, 1]")
        if (
            self.status
            in {
                RQ1FactAnnotationStatus.PRESERVED_CORRECTLY,
                RQ1FactAnnotationStatus.DISTORTED_OR_CONTRADICTED,
                RQ1FactAnnotationStatus.PARTIAL,
                RQ1FactAnnotationStatus.CORRECTLY_REFLECTED,
                RQ1FactAnnotationStatus.MENTIONED_ONLY,
                RQ1FactAnnotationStatus.INCORRECTLY_REFLECTED,
            }
            and not self.evidence_spans
        ):
            raise ValueError(
                "observed semantic fact judgments require an evidence span"
            )
        if (
            self.status
            not in _RQ1_NONBINARY_STATUSES
            and self.observation_status
            != RQ1FactObservationStatus.COMPLETE_VALID
        ):
            raise ValueError(
                "binary fact judgments require a complete valid observation"
            )
        if (
            self.status == RQ1FactAnnotationStatus.UNCERTAIN
            and self.observation_status
            != RQ1FactObservationStatus.COMPLETE_VALID
        ):
            raise ValueError(
                "uncertain is a semantic judgment and requires complete valid text"
            )
        if (
            self.status == RQ1FactAnnotationStatus.UNOBSERVABLE
            and self.observation_status
            == RQ1FactObservationStatus.COMPLETE_VALID
        ):
            raise ValueError(
                "unobservable fact status cannot have complete valid observation"
            )
        metadata = self.metadata if self.metadata is not None else {}
        if not isinstance(metadata, dict):
            raise ValueError("RQ1 fact annotation metadata must be an object")

    @property
    def is_binary(self) -> bool:
        return self.status not in _RQ1_NONBINARY_STATUSES

    @property
    def is_success(self) -> bool:
        return self.status == _RQ1_SUCCESS_STATUS[self.stage]

    def to_record(self) -> AnnotationRecord:
        self.validate()
        identifiability = (
            "unobservable"
            if self.status == RQ1FactAnnotationStatus.UNOBSERVABLE
            else "uncertain"
            if self.status
            in {
                RQ1FactAnnotationStatus.UNCERTAIN,
                RQ1FactAnnotationStatus.UNKNOWN,
            }
            else "complete_text_semantic"
        )
        record = AnnotationRecord(
            annotation_id=self.annotation_id,
            run_id=self.run_id,
            taxonomy=RQ1_FACT_ANNOTATION_TAXONOMY,
            taxonomy_version=RQ1_FACT_ANNOTATION_VERSION,
            labels=(
                f"stage:{self.stage.value}",
                f"status:{self.status.value}",
                f"observation:{self.observation_status.value}",
            ),
            annotator=self.annotator,
            identifiability=identifiability,
            target_event_ids=self.target_event_ids,
            artifact_id=self.fact_id,
            evidence_spans=self.evidence_spans,
            blind_fields=self.blind_fields,
            confidence=self.confidence,
            adjudication=self.adjudication,
            metadata={
                "rq1_fact_annotation": {
                    "contract_type": self.contract_type,
                    "transformation_id": self.transformation_id,
                    "fact_id": self.fact_id,
                    "stage": self.stage.value,
                    "status": self.status.value,
                    "observation_status": self.observation_status.value,
                    "metadata": dict(self.metadata or {}),
                }
            },
        )
        record.validate()
        return record

    @classmethod
    def from_record(cls, record: AnnotationRecord) -> RQ1FactAnnotation:
        record.validate()
        if record.taxonomy != RQ1_FACT_ANNOTATION_TAXONOMY:
            raise ValueError("annotation is not an RQ1 required-fact annotation")
        if record.taxonomy_version != RQ1_FACT_ANNOTATION_VERSION:
            raise ValueError("unsupported RQ1 required-fact taxonomy_version")
        raw = record.metadata.get("rq1_fact_annotation")
        if not isinstance(raw, dict) or raw.get("contract_type") != cls.contract_type:
            raise ValueError("missing or invalid RQ1 fact annotation contract")
        required_fields = {
            "transformation_id",
            "fact_id",
            "stage",
            "status",
            "observation_status",
        }
        if not required_fields.issubset(raw):
            raise ValueError("malformed RQ1 fact annotation contract")
        if raw.get("fact_id") != record.artifact_id:
            raise ValueError("RQ1 fact annotation artifact/fact ID mismatch")
        stage = RQ1FactAnnotationStage(raw["stage"])
        status = RQ1FactAnnotationStatus(raw["status"])
        observation_status = RQ1FactObservationStatus(raw["observation_status"])
        expected_labels = {
            f"stage:{stage.value}",
            f"status:{status.value}",
            f"observation:{observation_status.value}",
        }
        if set(record.labels) != expected_labels:
            raise ValueError("RQ1 fact annotation labels mismatch contract")
        item = cls(
            annotation_id=record.annotation_id,
            run_id=record.run_id,
            transformation_id=str(raw["transformation_id"]),
            fact_id=str(raw["fact_id"]),
            stage=stage,
            status=status,
            observation_status=observation_status,
            target_event_ids=record.target_event_ids,
            annotator=record.annotator,
            evidence_spans=record.evidence_spans,
            blind_fields=record.blind_fields,
            confidence=record.confidence,
            adjudication=record.adjudication,
            metadata=dict(raw.get("metadata", {})),
        )
        item.validate()
        return item


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
