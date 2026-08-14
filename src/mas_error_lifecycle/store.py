"""JSONL persistence and cross-record/state-machine validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .schema import (
    AnnotationRecord,
    ArtifactKind,
    ArtifactOrigin,
    ArtifactRecord,
    AttestationRecord,
    CallStatus,
    EvidenceRecord,
    EvidenceValidity,
    EventType,
    GraderRunRecord,
    GraderStatus,
    InformationAssignmentRecord,
    InjectionRecord,
    LifecycleEvent,
    MessageRecord,
    ModelCallRecord,
    PromptRecord,
    RunManifest,
    RunOutcome,
    ToolCallRecord,
    TraceRecord,
    VerificationCompletionStatus,
    VerificationTiming,
    VerificationVerdict,
    record_from_dict,
)


class TraceValidationError(ValueError):
    """Raised when one or more trace invariants are violated."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass(frozen=True, slots=True)
class TraceBundle:
    manifest: RunManifest
    artifacts: tuple[ArtifactRecord, ...]
    prompts: tuple[PromptRecord, ...]
    events: tuple[LifecycleEvent, ...]
    outcome: RunOutcome
    information_assignments: tuple[InformationAssignmentRecord, ...] = ()
    injections: tuple[InjectionRecord, ...] = ()
    messages: tuple[MessageRecord, ...] = ()
    evidence: tuple[EvidenceRecord, ...] = ()
    model_calls: tuple[ModelCallRecord, ...] = ()
    tool_calls: tuple[ToolCallRecord, ...] = ()
    annotations: tuple[AnnotationRecord, ...] = ()
    attestations: tuple[AttestationRecord, ...] = ()
    graders: tuple[GraderRunRecord, ...] = ()

    def records(self) -> Iterable[TraceRecord]:
        yield self.manifest
        yield from self.information_assignments
        yield from self.injections
        yield from self.artifacts
        yield from self.prompts
        yield from self.messages
        yield from self.evidence
        yield from self.model_calls
        yield from self.tool_calls
        yield from self.annotations
        yield from self.events
        yield from self.attestations
        yield from self.graders
        yield self.outcome

    def validate(self) -> None:
        errors: list[str] = []
        for record in self.records():
            try:
                record.validate()
            except ValueError as exc:
                errors.append(f"{type(record).__name__}: {exc}")

        run_id = self.manifest.run_id
        children = tuple(record for record in self.records() if record is not self.manifest)
        if any(getattr(record, "run_id", None) != run_id for record in children):
            errors.append("all records must share manifest.run_id")

        agents = {agent.agent_id: agent for agent in self.manifest.agents}
        if len(agents) != len(self.manifest.agents):
            errors.append("manifest contains duplicate agent_id values")
        edges = {edge.edge_id: edge for edge in self.manifest.topology}
        if len(edges) != len(self.manifest.topology):
            errors.append("manifest contains duplicate edge_id values")
        for edge in self.manifest.topology:
            if edge.source not in agents or edge.target not in agents:
                errors.append(f"edge {edge.edge_id} references an unknown agent")

        artifact_map = _unique_map(
            self.artifacts, "artifact_id", "artifact", errors
        )
        prompt_map = _unique_map(self.prompts, "prompt_id", "prompt", errors)
        message_map = _unique_map(self.messages, "message_id", "message", errors)
        evidence_map = _unique_map(self.evidence, "evidence_id", "evidence", errors)
        model_call_map = _unique_map(
            self.model_calls, "call_id", "model call", errors
        )
        tool_call_map = _unique_map(
            self.tool_calls, "tool_call_id", "tool call", errors
        )
        event_map = _unique_map(self.events, "event_id", "event", errors)
        grader_map = _unique_map(self.graders, "grader_id", "grader", errors)
        _unique_map(
            self.information_assignments,
            "assignment_id",
            "information assignment",
            errors,
        )
        _unique_map(self.injections, "injection_id", "injection", errors)
        _unique_map(self.annotations, "annotation_id", "annotation", errors)
        _unique_map(self.attestations, "attestation_id", "attestation", errors)

        self._validate_artifacts(artifact_map, agents, errors)
        self._validate_assignments_and_injections(artifact_map, agents, edges, errors)
        self._validate_prompts_messages_calls(
            artifact_map,
            prompt_map,
            message_map,
            model_call_map,
            agents,
            errors,
        )
        self._validate_evidence_tools_annotations(
            artifact_map,
            evidence_map,
            event_map,
            tool_call_map,
            agents,
            errors,
        )
        self._validate_events(
            artifact_map,
            prompt_map,
            message_map,
            evidence_map,
            event_map,
            agents,
            edges,
            errors,
        )
        self._validate_attestations_and_outcome(
            evidence_map, grader_map, agents, errors
        )
        self._validate_usage(model_call_map, errors)

        # RQ1 transformations are additive contracts nested in annotations.
        # Import lazily to avoid coupling the generic record schema to the
        # derived-suite calibration helper while still validating fail-closed.
        rq1_declared = (
            self.manifest.protocol_kind.startswith("rq1_")
            or self.manifest.benchmark.lower().startswith("rq1")
            or any(str(key).startswith("rq1_") for key in self.manifest.config)
            or any(
                annotation.taxonomy
                in {"rq1-transformation", "rq1-required-fact"}
                for annotation in self.annotations
            )
        )
        if rq1_declared:
            try:
                from .rq1 import _validate_rq1_bundle_records

                _validate_rq1_bundle_records(self)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"RQ1 transformation contract: {exc}")

        if errors:
            raise TraceValidationError(errors)

    def _validate_artifacts(
        self,
        artifacts: dict[str, ArtifactRecord],
        agents: dict[str, object],
        errors: list[str],
    ) -> None:
        for artifact in self.artifacts:
            if artifact.source_agent_id and artifact.source_agent_id not in agents:
                errors.append(
                    f"artifact {artifact.artifact_id} references unknown source agent"
                )
            for parent_id in artifact.parent_artifact_ids:
                parent = artifacts.get(parent_id)
                if parent is None:
                    errors.append(
                        f"artifact {artifact.artifact_id} references unknown parent {parent_id}"
                    )
                elif parent.created_step > artifact.created_step:
                    errors.append(
                        f"artifact {artifact.artifact_id} parent {parent_id} is created later"
                    )
        _validate_artifact_dag(artifacts, errors)

    def _validate_assignments_and_injections(
        self,
        artifacts: dict[str, ArtifactRecord],
        agents: dict[str, object],
        edges: dict[str, object],
        errors: list[str],
    ) -> None:
        for assignment in self.information_assignments:
            if assignment.artifact_id not in artifacts:
                errors.append(
                    f"information assignment {assignment.assignment_id} "
                    "references unknown artifact"
                )
            for agent_id in (
                *assignment.holder_agent_ids,
                *assignment.authorized_agent_ids,
            ):
                if agent_id not in agents:
                    errors.append(
                        f"information assignment {assignment.assignment_id} "
                        f"references unknown agent {agent_id}"
                    )
        for injection in self.injections:
            if injection.artifact_id not in artifacts:
                errors.append(
                    f"injection {injection.injection_id} references unknown artifact"
                )
            if injection.target_agent_id and injection.target_agent_id not in agents:
                errors.append(
                    f"injection {injection.injection_id} references unknown target agent"
                )
            if injection.target_edge_id and injection.target_edge_id not in edges:
                errors.append(
                    f"injection {injection.injection_id} references unknown target edge"
                )

    def _validate_prompts_messages_calls(
        self,
        artifacts: dict[str, ArtifactRecord],
        prompts: dict[str, PromptRecord],
        messages: dict[str, MessageRecord],
        model_calls: dict[str, ModelCallRecord],
        agents: dict[str, object],
        errors: list[str],
    ) -> None:
        for prompt in self.prompts:
            if prompt.agent_id not in agents:
                errors.append(f"prompt {prompt.prompt_id} references unknown agent")
            for artifact_id in prompt.artifact_ids:
                if artifact_id not in artifacts:
                    errors.append(
                        f"prompt {prompt.prompt_id} references unknown artifact {artifact_id}"
                    )
            if prompt.call_id and prompt.call_id not in model_calls:
                errors.append(f"prompt {prompt.prompt_id} references unknown model call")
        for message in self.messages:
            if message.source_agent_id not in agents:
                errors.append(f"message {message.message_id} has unknown source")
            if (
                message.target_agent_id not in agents
                and message.target_agent_id != "__output__"
            ):
                errors.append(f"message {message.message_id} has unknown target")
            for artifact_id in (
                *message.expected_artifact_ids,
                *message.artifact_ids,
            ):
                if artifact_id not in artifacts:
                    errors.append(
                        f"message {message.message_id} references unknown artifact "
                        f"{artifact_id}"
                    )
            if message.included_prompt_id:
                prompt = prompts.get(message.included_prompt_id)
                if prompt is None:
                    errors.append(
                        f"message {message.message_id} references unknown included prompt"
                    )
                elif prompt.agent_id != message.target_agent_id:
                    errors.append(
                        f"message {message.message_id} included prompt has wrong agent"
                    )
        for call in self.model_calls:
            if call.agent_id not in agents:
                errors.append(f"model call {call.call_id} references unknown agent")
            prompt = prompts.get(call.prompt_id)
            if prompt is None:
                errors.append(f"model call {call.call_id} references unknown prompt")
            elif prompt.agent_id != call.agent_id:
                errors.append(f"model call {call.call_id} prompt has wrong agent")
            elif prompt.call_id and prompt.call_id != call.call_id:
                errors.append(f"model call {call.call_id} does not match prompt.call_id")

    def _validate_evidence_tools_annotations(
        self,
        artifacts: dict[str, ArtifactRecord],
        evidence: dict[str, EvidenceRecord],
        events: dict[str, LifecycleEvent],
        tool_calls: dict[str, ToolCallRecord],
        agents: dict[str, object],
        errors: list[str],
    ) -> None:
        for item in self.evidence:
            if item.artifact_id and item.artifact_id not in artifacts:
                errors.append(f"evidence {item.evidence_id} references unknown artifact")
            if item.producer_agent_id and item.producer_agent_id not in agents:
                errors.append(f"evidence {item.evidence_id} references unknown producer")
        for call in self.tool_calls:
            if call.agent_id not in agents:
                errors.append(f"tool call {call.tool_call_id} references unknown agent")
            for artifact_id in call.depends_on_artifact_ids:
                if artifact_id not in artifacts:
                    errors.append(
                        f"tool call {call.tool_call_id} references unknown artifact"
                    )
        for annotation in self.annotations:
            if annotation.artifact_id and annotation.artifact_id not in artifacts:
                errors.append(
                    f"annotation {annotation.annotation_id} references unknown artifact"
                )
            if annotation.agent_id and annotation.agent_id not in agents:
                errors.append(
                    f"annotation {annotation.annotation_id} references unknown agent"
                )
            for event_id in (
                *annotation.target_event_ids,
                *annotation.evidence_event_ids,
            ):
                if event_id not in events:
                    errors.append(
                        f"annotation {annotation.annotation_id} references unknown event"
                    )

    def _validate_events(
        self,
        artifacts: dict[str, ArtifactRecord],
        prompts: dict[str, PromptRecord],
        messages: dict[str, MessageRecord],
        evidence: dict[str, EvidenceRecord],
        events: dict[str, LifecycleEvent],
        agents: dict[str, object],
        edges: dict[str, object],
        errors: list[str],
    ) -> None:
        positions = {event.event_id: index for index, event in enumerate(self.events)}
        previous_step = -1
        prior_by_pair: dict[tuple[str, str], list[LifecycleEvent]] = {}
        finalized = 0

        for index, event in enumerate(self.events):
            if event.step < previous_step:
                errors.append("events must be ordered by non-decreasing step")
            previous_step = max(previous_step, event.step)
            if event.event_type == EventType.RUN_FINALIZED:
                finalized += 1
            if event.artifact_id and event.artifact_id not in artifacts:
                errors.append(f"event {event.event_id} references unknown artifact")
            for field_name in ("agent_id", "source_agent_id", "target_agent_id"):
                value = getattr(event, field_name)
                if value and value not in agents and value != "__output__":
                    errors.append(
                        f"event {event.event_id} has unknown {field_name}={value}"
                    )
            if event.edge_id:
                edge = edges.get(event.edge_id)
                if edge is None:
                    errors.append(f"event {event.event_id} references unknown edge")
                elif (
                    event.source_agent_id
                    and event.target_agent_id
                    and (
                        edge.source != event.source_agent_id
                        or edge.target != event.target_agent_id
                    )
                ):
                    errors.append(f"event {event.event_id} edge endpoints do not match")
            for parent_id in event.parent_event_ids:
                parent_position = positions.get(parent_id)
                if parent_position is None:
                    errors.append(
                        f"event {event.event_id} references unknown parent event"
                    )
                elif parent_position >= index:
                    errors.append(
                        f"event {event.event_id} parent must occur earlier"
                    )
                else:
                    parent = events[parent_id]
                    if (
                        event.artifact_id
                        and parent.artifact_id
                        and event.artifact_id != parent.artifact_id
                    ):
                        errors.append(
                            f"event {event.event_id} parent has different artifact"
                        )

            if event.event_type in {EventType.MESSAGE_SENT, EventType.MESSAGE_DELIVERED}:
                message_id = event.details.get("message_id")
                message = messages.get(str(message_id))
                if message is None:
                    errors.append(f"event {event.event_id} references unknown message")
                else:
                    if (
                        message.source_agent_id != event.source_agent_id
                        or message.target_agent_id != event.target_agent_id
                    ):
                        errors.append(
                            f"event {event.event_id} does not match message endpoints"
                        )
                    if event.event_type == EventType.MESSAGE_DELIVERED:
                        if message.delivered is not True:
                            errors.append(
                                f"event {event.event_id} says delivered but message does not"
                            )
                        sent_parents = [
                            events[parent_id]
                            for parent_id in event.parent_event_ids
                            if parent_id in events
                            and events[parent_id].event_type == EventType.MESSAGE_SENT
                        ]
                        if not sent_parents:
                            errors.append(
                                f"event {event.event_id} has no message_sent parent"
                            )

            if event.event_type == EventType.ARTIFACT_EXPOSED:
                prompt = prompts.get(event.prompt_id or "")
                if prompt is None:
                    errors.append(f"event {event.event_id} references unknown prompt")
                else:
                    if prompt.agent_id != event.target_agent_id:
                        errors.append(
                            f"event {event.event_id} prompt belongs to wrong agent"
                        )
                    if event.artifact_id not in prompt.artifact_ids:
                        errors.append(
                            f"event {event.event_id} artifact is absent from prompt"
                        )
                    if (
                        prompt.metadata.get("actual_full_provider_request_available")
                        is not True
                    ):
                        errors.append(
                            f"event {event.event_id} prompt is not an observed full request"
                        )

            if event.event_type == EventType.VERIFICATION_COMPLETED:
                for evidence_id in event.details.get("evidence_ids", []):
                    if evidence_id not in evidence:
                        errors.append(
                            f"event {event.event_id} references unknown evidence "
                            f"{evidence_id}"
                        )

            if event.event_type == EventType.ACTION_TAKEN:
                for artifact_id in event.details.get(
                    "depends_on_artifact_ids", []
                ):
                    if artifact_id not in artifacts:
                        errors.append(
                            f"event {event.event_id} action references unknown artifact"
                        )

            state_agent = event.agent_id
            if event.event_type == EventType.ARTIFACT_EXPOSED:
                state_agent = event.target_agent_id
            if state_agent and event.artifact_id:
                pair = (event.artifact_id, state_agent)
                prior = prior_by_pair.setdefault(pair, [])
                self._validate_state_transition(event, prior, artifacts, evidence, errors)
                prior.append(event)

        if finalized != 1:
            errors.append(f"trace must contain exactly one run_finalized event, found {finalized}")

        roots_by_artifact: dict[str, set[EventType]] = {}
        for event in self.events:
            if event.artifact_id:
                roots_by_artifact.setdefault(event.artifact_id, set()).add(event.event_type)
        for artifact in self.artifacts:
            roots = roots_by_artifact.get(artifact.artifact_id, set())
            required = (
                EventType.ARTIFACT_GENERATED
                if artifact.origin == ArtifactOrigin.NATURAL_GENERATION
                else EventType.ARTIFACT_POSSESSED
            )
            if required not in roots:
                errors.append(
                    f"artifact {artifact.artifact_id} has no {required.value} origin event"
                )

        last_step = max((event.step for event in self.events), default=0)
        if self.outcome.final_step < last_step:
            errors.append("outcome.final_step precedes the last lifecycle event")

    def _validate_state_transition(
        self,
        event: LifecycleEvent,
        prior: list[LifecycleEvent],
        artifacts: dict[str, ArtifactRecord],
        evidence: dict[str, EvidenceRecord],
        errors: list[str],
    ) -> None:
        prior_types = {item.event_type for item in prior}
        event_type = event.event_type
        pair_name = f"{event.artifact_id}/{event.agent_id}"

        if event_type in {EventType.ARTIFACT_ADOPTED, EventType.ARTIFACT_INTEGRATED}:
            if not prior_types & {
                EventType.ARTIFACT_EXPOSED,
                EventType.ARTIFACT_POSSESSED,
                EventType.ARTIFACT_GENERATED,
            }:
                errors.append(
                    f"{event_type.value} for {pair_name} occurs without prior exposure/possession"
                )

        if event_type == EventType.VERIFICATION_STARTED:
            timing = event.details.get("timing")
            if (
                timing == VerificationTiming.POST_ADOPTION.value
                and not prior_types
                & {EventType.ARTIFACT_ADOPTED, EventType.ARTIFACT_INTEGRATED}
            ):
                errors.append(
                    f"post-adoption verification for {pair_name} has no prior adoption"
                )
            if (
                timing == VerificationTiming.PRE_ADOPTION.value
                and not prior_types
                & {
                    EventType.ARTIFACT_EXPOSED,
                    EventType.ARTIFACT_POSSESSED,
                    EventType.ARTIFACT_GENERATED,
                }
            ):
                errors.append(
                    f"pre-adoption verification for {pair_name} has no prior information"
                )

        if event_type == EventType.VERIFICATION_COMPLETED:
            matching_start = [
                item
                for item in prior
                if item.event_type == EventType.VERIFICATION_STARTED
                and item.details.get("timing") == event.details.get("timing")
            ]
            if not matching_start:
                errors.append(
                    f"verification_completed for {pair_name} has no matching start"
                )
            if (
                event.details.get("completion_status")
                == VerificationCompletionStatus.COMPLETED.value
                and event.details.get("evidence_validity")
                == EvidenceValidity.VALID.value
            ):
                valid_evidence = [
                    evidence.get(evidence_id)
                    for evidence_id in event.details.get("evidence_ids", [])
                ]
                if not valid_evidence or any(
                    item is None or item.validity != EvidenceValidity.VALID
                    for item in valid_evidence
                ):
                    errors.append(
                        f"verification_completed for {pair_name} claims valid "
                        "evidence without valid records"
                    )

        if event_type == EventType.ROLLBACK_COMPLETED and EventType.ROLLBACK_STARTED not in prior_types:
            errors.append(f"rollback_completed for {pair_name} has no rollback_started")

        if event_type == EventType.ARTIFACT_RECOVERED:
            detected = any(
                item.event_type == EventType.VERIFICATION_COMPLETED
                and item.details.get("verdict") == VerificationVerdict.REFUTED.value
                for item in prior
            )
            actuated = bool(
                prior_types
                & {
                    EventType.ARTIFACT_CONTAINED,
                    EventType.ROLLBACK_COMPLETED,
                    EventType.ARTIFACT_CORRECTED,
                }
            )
            if not detected:
                errors.append(f"artifact_recovered for {pair_name} has no prior detection")
            if not actuated:
                errors.append(f"artifact_recovered for {pair_name} has no actuation")

        if event_type == EventType.ARTIFACT_RELAPSED and not prior_types & {
            EventType.ARTIFACT_RECOVERED,
            EventType.ARTIFACT_CONTAINED,
            EventType.ROLLBACK_COMPLETED,
        }:
            errors.append(f"artifact_relapsed for {pair_name} has no prior containment")

        commitment_followups = {
            EventType.COMMITMENT_ACKNOWLEDGED,
            EventType.COMMITMENT_FULFILLED,
            EventType.COMMITMENT_BREACHED,
            EventType.COMMITMENT_WITHDRAWN,
        }
        if event_type in commitment_followups:
            artifact = artifacts.get(event.artifact_id or "")
            if artifact and artifact.kind not in {
                ArtifactKind.COMMITMENT,
                ArtifactKind.INTERFACE_CONTRACT,
            }:
                errors.append(
                    f"{event_type.value} requires commitment/interface-contract artifact"
                )
            if EventType.COMMITMENT_MADE not in prior_types:
                errors.append(f"{event_type.value} for {pair_name} has no commitment_made")
            for evidence_id in event.details.get("evidence_ids", []):
                if evidence_id not in evidence:
                    errors.append(
                        f"{event_type.value} for {pair_name} references unknown evidence"
                    )

    def _validate_attestations_and_outcome(
        self,
        evidence: dict[str, EvidenceRecord],
        graders: dict[str, GraderRunRecord],
        agents: dict[str, object],
        errors: list[str],
    ) -> None:
        for attestation in self.attestations:
            if attestation.verifier_agent_id not in agents:
                errors.append(
                    f"attestation {attestation.attestation_id} has unknown verifier"
                )
            for evidence_id in attestation.evidence_ids:
                if evidence_id not in evidence:
                    errors.append(
                        f"attestation {attestation.attestation_id} "
                        "references unknown evidence"
                    )
        if self.outcome.grader_id:
            grader = graders.get(self.outcome.grader_id)
            if grader is None:
                errors.append("outcome references unknown grader")
            elif grader.status != GraderStatus.SUCCESS:
                errors.append("outcome cannot use unsuccessful grader")
            elif (
                grader.task_passed != self.outcome.success
                or grader.score != self.outcome.score
            ):
                errors.append("outcome does not match referenced grader")

    def _validate_usage(
        self, model_calls: dict[str, ModelCallRecord], errors: list[str]
    ) -> None:
        if self.manifest.config.get("usage_reconciliation_complete") is not True:
            return
        successful = [
            call for call in model_calls.values() if call.status == CallStatus.SUCCESS
        ]
        if successful and all(call.input_tokens is not None for call in successful):
            total = sum(int(call.input_tokens or 0) for call in successful)
            if self.outcome.input_tokens is not None and self.outcome.input_tokens != total:
                errors.append("outcome input_tokens do not reconcile with model calls")
        if successful and all(call.output_tokens is not None for call in successful):
            total = sum(int(call.output_tokens or 0) for call in successful)
            if self.outcome.output_tokens is not None and self.outcome.output_tokens != total:
                errors.append("outcome output_tokens do not reconcile with model calls")


def _unique_map(
    records: Iterable[object],
    field_name: str,
    label: str,
    errors: list[str],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for record in records:
        value = str(getattr(record, field_name))
        if value in result:
            errors.append(f"trace contains duplicate {field_name} values for {label}")
        result[value] = record
    return result


def _validate_artifact_dag(
    artifacts: dict[str, ArtifactRecord], errors: list[str]
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(artifact_id: str) -> None:
        if artifact_id in visited:
            return
        if artifact_id in visiting:
            errors.append(f"artifact lineage contains a cycle at {artifact_id}")
            return
        visiting.add(artifact_id)
        artifact = artifacts.get(artifact_id)
        if artifact:
            for parent_id in artifact.parent_artifact_ids:
                if parent_id in artifacts:
                    visit(parent_id)
        visiting.discard(artifact_id)
        visited.add(artifact_id)

    for artifact_id in artifacts:
        visit(artifact_id)


def write_trace(path: str | Path, bundle: TraceBundle, *, overwrite: bool = False) -> Path:
    """Validate and atomically write one run as newline-delimited JSON."""

    bundle.validate()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise FileExistsError(f"{destination} already exists; pass overwrite=True to replace it")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in bundle.records():
            handle.write(
                json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False)
            )
            handle.write("\n")
    temporary.replace(destination)
    return destination


def load_trace(path: str | Path, *, validate: bool = True) -> TraceBundle:
    """Load a single-run JSONL file and optionally validate all invariants."""

    source = Path(path)
    records: list[TraceRecord] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("line is not a JSON object")
                records.append(record_from_dict(raw))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise TraceValidationError([f"line {line_number}: {exc}"]) from exc

    manifests = [record for record in records if isinstance(record, RunManifest)]
    outcomes = [record for record in records if isinstance(record, RunOutcome)]
    errors: list[str] = []
    if len(manifests) != 1:
        errors.append(f"expected exactly one run_manifest, found {len(manifests)}")
    if len(outcomes) != 1:
        errors.append(f"expected exactly one outcome, found {len(outcomes)}")
    if errors:
        raise TraceValidationError(errors)

    bundle = TraceBundle(
        manifest=manifests[0],
        artifacts=tuple(
            record for record in records if isinstance(record, ArtifactRecord)
        ),
        prompts=tuple(record for record in records if isinstance(record, PromptRecord)),
        events=tuple(
            record for record in records if isinstance(record, LifecycleEvent)
        ),
        outcome=outcomes[0],
        information_assignments=tuple(
            record
            for record in records
            if isinstance(record, InformationAssignmentRecord)
        ),
        injections=tuple(
            record for record in records if isinstance(record, InjectionRecord)
        ),
        messages=tuple(
            record for record in records if isinstance(record, MessageRecord)
        ),
        evidence=tuple(
            record for record in records if isinstance(record, EvidenceRecord)
        ),
        model_calls=tuple(
            record for record in records if isinstance(record, ModelCallRecord)
        ),
        tool_calls=tuple(
            record for record in records if isinstance(record, ToolCallRecord)
        ),
        annotations=tuple(
            record for record in records if isinstance(record, AnnotationRecord)
        ),
        attestations=tuple(
            record for record in records if isinstance(record, AttestationRecord)
        ),
        graders=tuple(
            record for record in records if isinstance(record, GraderRunRecord)
        ),
    )
    if validate:
        bundle.validate()
    return bundle
