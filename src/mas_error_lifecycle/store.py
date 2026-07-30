"""JSONL trace persistence and cross-record validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .schema import (
    ArtifactRecord,
    EventType,
    LifecycleEvent,
    PromptRecord,
    RunManifest,
    RunOutcome,
    TraceRecord,
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

    def records(self) -> Iterable[TraceRecord]:
        yield self.manifest
        yield from self.artifacts
        yield from self.prompts
        yield from self.events
        yield self.outcome

    def validate(self) -> None:
        errors: list[str] = []
        for record in self.records():
            try:
                record.validate()
            except ValueError as exc:
                errors.append(f"{type(record).__name__}: {exc}")

        run_id = self.manifest.run_id
        if any(
            record.run_id != run_id
            for record in (*self.artifacts, *self.prompts, *self.events, self.outcome)
        ):
            errors.append("all records must share manifest.run_id")

        agent_ids = [agent.agent_id for agent in self.manifest.agents]
        if len(agent_ids) != len(set(agent_ids)):
            errors.append("manifest contains duplicate agent_id values")
        agent_set = set(agent_ids)

        edge_ids = [edge.edge_id for edge in self.manifest.topology]
        if len(edge_ids) != len(set(edge_ids)):
            errors.append("manifest contains duplicate edge_id values")
        edge_set = set(edge_ids)
        for edge in self.manifest.topology:
            if edge.source not in agent_set or edge.target not in agent_set:
                errors.append(f"edge {edge.edge_id} references an unknown agent")

        artifact_ids = [artifact.artifact_id for artifact in self.artifacts]
        if len(artifact_ids) != len(set(artifact_ids)):
            errors.append("trace contains duplicate artifact_id values")
        artifact_set = set(artifact_ids)
        for artifact in self.artifacts:
            if artifact.source_agent_id not in agent_set:
                errors.append(f"artifact {artifact.artifact_id} references unknown source agent")
            for parent_id in artifact.parent_artifact_ids:
                if parent_id not in artifact_set:
                    errors.append(
                        f"artifact {artifact.artifact_id} references unknown parent {parent_id}"
                    )

        prompt_ids = [prompt.prompt_id for prompt in self.prompts]
        if len(prompt_ids) != len(set(prompt_ids)):
            errors.append("trace contains duplicate prompt_id values")
        prompt_set = set(prompt_ids)
        for prompt in self.prompts:
            if prompt.agent_id not in agent_set:
                errors.append(f"prompt {prompt.prompt_id} references unknown agent")
            for artifact_id in prompt.artifact_ids:
                if artifact_id not in artifact_set:
                    errors.append(
                        f"prompt {prompt.prompt_id} references unknown artifact {artifact_id}"
                    )

        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            errors.append("trace contains duplicate event_id values")
        event_set = set(event_ids)
        previous_step = -1
        for event in self.events:
            if event.step < previous_step:
                errors.append("events must be ordered by non-decreasing step")
            previous_step = max(previous_step, event.step)
            if event.artifact_id and event.artifact_id not in artifact_set:
                errors.append(f"event {event.event_id} references unknown artifact")
            for field_name in ("agent_id", "source_agent_id", "target_agent_id"):
                value = getattr(event, field_name)
                if value and value not in agent_set and value != "__output__":
                    errors.append(f"event {event.event_id} has unknown {field_name}={value}")
            if event.edge_id and event.edge_id not in edge_set:
                errors.append(f"event {event.event_id} references unknown edge")
            if event.prompt_id and event.prompt_id not in prompt_set:
                errors.append(f"event {event.event_id} references unknown prompt")
            for parent_id in event.parent_event_ids:
                if parent_id not in event_set:
                    errors.append(f"event {event.event_id} references unknown parent event")

        generated = {
            (event.artifact_id, event.agent_id)
            for event in self.events
            if event.event_type == EventType.ARTIFACT_GENERATED
        }
        for artifact in self.artifacts:
            if (artifact.artifact_id, artifact.source_agent_id) not in generated:
                errors.append(
                    f"artifact {artifact.artifact_id} has no matching artifact_generated event"
                )

        if self.outcome.final_step < max((event.step for event in self.events), default=0):
            errors.append("outcome.final_step precedes the last lifecycle event")

        if errors:
            raise TraceValidationError(errors)


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
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False))
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
    artifacts = tuple(record for record in records if isinstance(record, ArtifactRecord))
    prompts = tuple(record for record in records if isinstance(record, PromptRecord))
    events = tuple(record for record in records if isinstance(record, LifecycleEvent))
    outcomes = [record for record in records if isinstance(record, RunOutcome)]
    errors: list[str] = []
    if len(manifests) != 1:
        errors.append(f"expected exactly one run_manifest, found {len(manifests)}")
    if len(outcomes) != 1:
        errors.append(f"expected exactly one outcome, found {len(outcomes)}")
    if errors:
        raise TraceValidationError(errors)
    bundle = TraceBundle(manifests[0], artifacts, prompts, events, outcomes[0])
    if validate:
        bundle.validate()
    return bundle
