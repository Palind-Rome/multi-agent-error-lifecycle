"""Lifecycle metrics computed from a validated trace."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean
from typing import Any, Iterable

from .schema import EventType, TruthStatus, VerificationVerdict
from .store import TraceBundle


def _rate(numerator: int | float, denominator: int | float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def _mean(values: Iterable[float]) -> float | None:
    collected = list(values)
    return fmean(collected) if collected else None


@dataclass(frozen=True, slots=True)
class RunMetrics:
    run_id: str
    task_id: str
    condition_id: str
    false_artifact_count: int
    transmission_attempt_count: int
    exposure_pair_count: int
    adoption_pair_count: int
    verification_pair_count: int
    detection_pair_count: int
    recovery_pair_count: int
    transport_delivery_rate: float | None
    edge_transmission_rate: float | None
    semantic_fidelity_mean: float | None
    adoption_given_exposure: float | None
    verification_given_adoption: float | None
    detection_given_verification: float | None
    false_accept_rate: float | None
    recovery_given_detection: float | None
    effective_error_reproduction_number: float | None
    max_adoption_hop: int
    mean_steps_to_detection: float | None
    mean_steps_to_recovery: float | None
    contaminated_agent_turn_auc: float
    final_contaminated_agents: int
    task_success: bool | None
    task_score: float | None
    input_tokens: int
    output_tokens: int
    latency_ms: float | None
    cost_usd: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_metrics(bundle: TraceBundle) -> RunMetrics:
    """Compute per-run mechanism, outcome, and cost metrics.

    Rates are conditional and return ``None`` when their denominator is zero.
    This prevents a run with no exposure or no verification from receiving an
    artificial perfect score.
    """

    bundle.validate()
    false_artifacts = {
        artifact.artifact_id: artifact
        for artifact in bundle.artifacts
        if artifact.truth_status == TruthStatus.FALSE
    }
    false_ids = set(false_artifacts)
    events = sorted(bundle.events, key=lambda item: (item.step, item.event_id))

    message_events = [
        event
        for event in events
        if event.event_type == EventType.MESSAGE_SENT and event.artifact_id in false_ids
    ]
    delivered_messages = [event for event in message_events if event.details.get("delivered", True)]
    surviving_messages = [
        event
        for event in delivered_messages
        if event.details.get(
            "artifact_present_in_message",
            event.details.get("exact_marker_present", True),
        )
    ]
    exposure_events = [
        event
        for event in events
        if event.event_type == EventType.ARTIFACT_EXPOSED and event.artifact_id in false_ids
    ]
    exposure_pairs = {
        (event.artifact_id, event.target_agent_id)
        for event in exposure_events
        if event.target_agent_id
    }
    adoption_events = [
        event
        for event in events
        if event.event_type == EventType.ARTIFACT_ADOPTED and event.artifact_id in false_ids
    ]
    adoption_pairs = {
        (event.artifact_id, event.agent_id) for event in adoption_events if event.agent_id
    }
    verification_events = [
        event
        for event in events
        if event.event_type == EventType.VERIFICATION_STARTED and event.artifact_id in false_ids
    ]
    verification_pairs = {
        (event.artifact_id, event.agent_id) for event in verification_events if event.agent_id
    }
    completed = [
        event
        for event in events
        if event.event_type == EventType.VERIFICATION_COMPLETED
        and event.artifact_id in false_ids
    ]
    detected_events = [
        event
        for event in completed
        if event.details.get("verdict") == VerificationVerdict.REFUTED.value
    ]
    detection_pairs = {
        (event.artifact_id, event.agent_id) for event in detected_events if event.agent_id
    }
    false_accept_events = [
        event
        for event in completed
        if event.details.get("verdict") == VerificationVerdict.SUPPORTED.value
    ]
    recovered_events = [
        event
        for event in events
        if event.event_type in {EventType.ARTIFACT_RECOVERED, EventType.ARTIFACT_CORRECTED}
        and event.artifact_id in false_ids
    ]
    recovery_pairs = {
        (event.artifact_id, event.agent_id) for event in recovered_events if event.agent_id
    }

    sources_with_exposure = {
        event.source_agent_id for event in exposure_events if event.source_agent_id
    }
    secondary_adoptions: dict[str, set[str]] = {
        source: set() for source in sources_with_exposure
    }
    for event in adoption_events:
        if event.source_agent_id and event.agent_id:
            secondary_adoptions.setdefault(event.source_agent_id, set()).add(event.agent_id)
    reproduction_number = _mean(
        float(len(targets)) for targets in secondary_adoptions.values()
    )

    max_hop = max(
        (
            int(event.details.get("hop", 0))
            for event in adoption_events
            if isinstance(event.details.get("hop", 0), int)
        ),
        default=0,
    )

    detection_steps: dict[str, int] = {}
    for event in detected_events:
        detection_steps.setdefault(event.artifact_id or "", event.step)
    steps_to_detection = [
        detection_step - false_artifacts[artifact_id].created_step
        for artifact_id, detection_step in detection_steps.items()
        if artifact_id in false_artifacts
    ]
    first_recovery_steps: dict[str, int] = {}
    for event in recovered_events:
        first_recovery_steps.setdefault(event.artifact_id or "", event.step)
    steps_to_recovery = [
        recovery_step - detection_steps[artifact_id]
        for artifact_id, recovery_step in first_recovery_steps.items()
        if artifact_id in detection_steps
    ]

    auc, final_contaminated = _contamination_auc(bundle, false_ids)
    fidelity = [
        float(event.details["semantic_fidelity"])
        for event in exposure_events
        if isinstance(event.details.get("semantic_fidelity"), int | float)
    ]

    return RunMetrics(
        run_id=bundle.manifest.run_id,
        task_id=bundle.manifest.task_id,
        condition_id=bundle.manifest.condition_id,
        false_artifact_count=len(false_artifacts),
        transmission_attempt_count=len(message_events),
        exposure_pair_count=len(exposure_pairs),
        adoption_pair_count=len(adoption_pairs),
        verification_pair_count=len(verification_pairs),
        detection_pair_count=len(detection_pairs),
        recovery_pair_count=len(recovery_pairs),
        transport_delivery_rate=_rate(len(delivered_messages), len(message_events)),
        edge_transmission_rate=_rate(len(surviving_messages), len(message_events)),
        semantic_fidelity_mean=_mean(fidelity),
        adoption_given_exposure=_rate(len(adoption_pairs & exposure_pairs), len(exposure_pairs)),
        verification_given_adoption=_rate(
            len(verification_pairs & adoption_pairs), len(adoption_pairs)
        ),
        detection_given_verification=_rate(
            len(detection_pairs & verification_pairs), len(verification_pairs)
        ),
        false_accept_rate=_rate(len(false_accept_events), len(completed)),
        recovery_given_detection=_rate(
            len(recovery_pairs & detection_pairs), len(detection_pairs)
        ),
        effective_error_reproduction_number=reproduction_number,
        max_adoption_hop=max_hop,
        mean_steps_to_detection=_mean(float(value) for value in steps_to_detection),
        mean_steps_to_recovery=_mean(float(value) for value in steps_to_recovery),
        contaminated_agent_turn_auc=auc,
        final_contaminated_agents=final_contaminated,
        task_success=bundle.outcome.success,
        task_score=bundle.outcome.score,
        input_tokens=bundle.outcome.input_tokens,
        output_tokens=bundle.outcome.output_tokens,
        latency_ms=bundle.outcome.latency_ms,
        cost_usd=bundle.outcome.cost_usd,
    )


def _contamination_auc(bundle: TraceBundle, false_ids: set[str]) -> tuple[float, int]:
    """Integrate unique contaminated agents across event steps."""

    contamination: set[tuple[str, str]] = set()
    events = sorted(bundle.events, key=lambda item: (item.step, item.event_id))
    last_step = 0
    area = 0.0
    for event in events:
        if event.step > last_step:
            area += _contaminated_agent_count(contamination) * (event.step - last_step)
            last_step = event.step
        if event.artifact_id not in false_ids:
            continue
        pair = (event.artifact_id, event.agent_id or "")
        if event.event_type in {EventType.ARTIFACT_GENERATED, EventType.ARTIFACT_ADOPTED}:
            if pair[1]:
                contamination.add(pair)
        elif event.event_type in {
            EventType.ARTIFACT_REJECTED,
            EventType.ARTIFACT_CORRECTED,
            EventType.ARTIFACT_RECOVERED,
        }:
            contamination.discard(pair)
    if bundle.outcome.final_step > last_step:
        area += _contaminated_agent_count(contamination) * (
            bundle.outcome.final_step - last_step
        )
    return area, _contaminated_agent_count(contamination)


def _contaminated_agent_count(contamination: set[tuple[str, str]]) -> int:
    return len({agent_id for _, agent_id in contamination})
