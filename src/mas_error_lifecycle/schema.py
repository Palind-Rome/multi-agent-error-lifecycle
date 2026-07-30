"""Versioned records for error-lifecycle traces.

The schema deliberately distinguishes a message being sent, an artifact being
present in the actual receiver context, and the receiver adopting the artifact.
Those events are often collapsed by existing multi-agent benchmarks.
"""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, TypeAlias

SCHEMA_VERSION = "0.1.0"


class TruthStatus(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class VerificationVerdict(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class EventType(StrEnum):
    ARTIFACT_GENERATED = "artifact_generated"
    MESSAGE_SENT = "message_sent"
    ARTIFACT_EXPOSED = "artifact_exposed"
    ARTIFACT_ADOPTED = "artifact_adopted"
    ARTIFACT_REJECTED = "artifact_rejected"
    ARTIFACT_UNCERTAIN = "artifact_uncertain"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    ARTIFACT_CORRECTED = "artifact_corrected"
    ARTIFACT_RECOVERED = "artifact_recovered"
    ACTION_TAKEN = "action_taken"
    RUN_FINALIZED = "run_finalized"


def _assert_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _assert_json_object(value: dict[str, Any], name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only JSON-serializable values") from exc


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    role: str
    provider: str = "unassigned"
    model: str = "unassigned"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.agent_id, "agent_id")
        _assert_nonempty(self.role, "role")
        _assert_nonempty(self.provider, "provider")
        _assert_nonempty(self.model, "model")
        _assert_json_object(self.metadata, "agent metadata")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgentSpec:
        return cls(
            agent_id=str(value["agent_id"]),
            role=str(value["role"]),
            provider=str(value.get("provider", "unassigned")),
            model=str(value.get("model", "unassigned")),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    edge_id: str
    source: str
    target: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.edge_id, "edge_id")
        _assert_nonempty(self.source, "edge source")
        _assert_nonempty(self.target, "edge target")
        if self.source == self.target:
            raise ValueError(f"self-loop is not allowed for edge {self.edge_id}")
        _assert_json_object(self.metadata, "edge metadata")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EdgeSpec:
        return cls(
            edge_id=str(value["edge_id"]),
            source=str(value["source"]),
            target=str(value["target"]),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class RunManifest:
    record_type: ClassVar[str] = "run_manifest"

    run_id: str
    task_id: str
    condition_id: str
    benchmark: str
    seed: int
    started_at: str
    agents: tuple[AgentSpec, ...]
    topology: tuple[EdgeSpec, ...]
    config: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        for name in ("run_id", "task_id", "condition_id", "benchmark", "started_at"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; expected {SCHEMA_VERSION!r}"
            )
        if not self.agents:
            raise ValueError("manifest must contain at least one agent")
        for agent in self.agents:
            agent.validate()
        for edge in self.topology:
            edge.validate()
        _assert_json_object(self.config, "run config")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "condition_id": self.condition_id,
            "benchmark": self.benchmark,
            "seed": self.seed,
            "started_at": self.started_at,
            "agents": [agent.to_dict() for agent in self.agents],
            "topology": [edge.to_dict() for edge in self.topology],
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunManifest:
        return cls(
            run_id=str(value["run_id"]),
            task_id=str(value["task_id"]),
            condition_id=str(value["condition_id"]),
            benchmark=str(value["benchmark"]),
            seed=int(value["seed"]),
            started_at=str(value["started_at"]),
            agents=tuple(AgentSpec.from_dict(item) for item in value.get("agents", [])),
            topology=tuple(EdgeSpec.from_dict(item) for item in value.get("topology", [])),
            config=dict(value.get("config", {})),
            schema_version=str(value.get("schema_version", "")),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    record_type: ClassVar[str] = "artifact"

    artifact_id: str
    run_id: str
    source_agent_id: str
    created_step: int
    truth_status: TruthStatus
    content: str
    parent_artifact_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.artifact_id, "artifact_id")
        _assert_nonempty(self.run_id, "artifact run_id")
        _assert_nonempty(self.source_agent_id, "artifact source_agent_id")
        if not isinstance(self.created_step, int) or self.created_step < 0:
            raise ValueError("artifact created_step must be a non-negative integer")
        if not isinstance(self.truth_status, TruthStatus):
            raise ValueError("artifact truth_status must be a TruthStatus")
        if not isinstance(self.content, str):
            raise ValueError("artifact content must be a string")
        _assert_json_object(self.metadata, "artifact metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "source_agent_id": self.source_agent_id,
            "created_step": self.created_step,
            "truth_status": self.truth_status.value,
            "content": self.content,
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ArtifactRecord:
        return cls(
            artifact_id=str(value["artifact_id"]),
            run_id=str(value["run_id"]),
            source_agent_id=str(value["source_agent_id"]),
            created_step=int(value["created_step"]),
            truth_status=TruthStatus(value["truth_status"]),
            content=str(value.get("content", "")),
            parent_artifact_ids=tuple(str(item) for item in value.get("parent_artifact_ids", [])),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class PromptRecord:
    record_type: ClassVar[str] = "prompt"

    prompt_id: str
    run_id: str
    agent_id: str
    step: int
    messages: tuple[dict[str, str], ...]
    artifact_ids: tuple[str, ...] = ()
    content_sha256: str = ""
    redacted: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.prompt_id, "prompt_id")
        _assert_nonempty(self.run_id, "prompt run_id")
        _assert_nonempty(self.agent_id, "prompt agent_id")
        if not isinstance(self.step, int) or self.step < 0:
            raise ValueError("prompt step must be a non-negative integer")
        if not self.messages:
            raise ValueError("prompt messages must be non-empty")
        for index, message in enumerate(self.messages):
            if not isinstance(message, dict):
                raise ValueError(f"prompt message {index} must be an object")
            if set(message) != {"role", "content"}:
                raise ValueError(
                    f"prompt message {index} must contain exactly role and content"
                )
            _assert_nonempty(message["role"], f"prompt message {index} role")
            if not isinstance(message["content"], str):
                raise ValueError(f"prompt message {index} content must be a string")
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise ValueError("prompt content_sha256 must be a lowercase SHA-256 hex digest")
        if prompt_sha256(self.messages) != self.content_sha256 and not self.redacted:
            raise ValueError("unredacted prompt content does not match content_sha256")
        if not isinstance(self.redacted, bool):
            raise ValueError("prompt redacted must be boolean")
        _assert_json_object(self.metadata, "prompt metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "prompt_id": self.prompt_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "step": self.step,
            "messages": list(self.messages),
            "artifact_ids": list(self.artifact_ids),
            "content_sha256": self.content_sha256,
            "redacted": self.redacted,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> PromptRecord:
        return cls(
            prompt_id=str(value["prompt_id"]),
            run_id=str(value["run_id"]),
            agent_id=str(value["agent_id"]),
            step=int(value["step"]),
            messages=tuple(
                {"role": str(item["role"]), "content": str(item["content"])}
                for item in value.get("messages", [])
            ),
            artifact_ids=tuple(str(item) for item in value.get("artifact_ids", [])),
            content_sha256=str(value.get("content_sha256", "")),
            redacted=value.get("redacted", False),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    record_type: ClassVar[str] = "event"

    event_id: str
    run_id: str
    event_type: EventType
    step: int
    timestamp: str
    agent_id: str | None = None
    artifact_id: str | None = None
    source_agent_id: str | None = None
    target_agent_id: str | None = None
    edge_id: str | None = None
    prompt_id: str | None = None
    parent_event_ids: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.event_id, "event_id")
        _assert_nonempty(self.run_id, "event run_id")
        _assert_nonempty(self.timestamp, "event timestamp")
        if not isinstance(self.event_type, EventType):
            raise ValueError("event_type must be an EventType")
        if not isinstance(self.step, int) or self.step < 0:
            raise ValueError("event step must be a non-negative integer")
        _assert_json_object(self.details, "event details")
        if self.event_type == EventType.MESSAGE_SENT:
            if not self.source_agent_id or not self.target_agent_id:
                raise ValueError("message_sent requires source_agent_id and target_agent_id")
        if self.event_type == EventType.ARTIFACT_EXPOSED:
            if not self.artifact_id or not self.target_agent_id or not self.prompt_id:
                raise ValueError("artifact_exposed requires artifact_id, target_agent_id, prompt_id")
        if self.event_type in {
            EventType.ARTIFACT_GENERATED,
            EventType.ARTIFACT_ADOPTED,
            EventType.ARTIFACT_REJECTED,
            EventType.ARTIFACT_UNCERTAIN,
            EventType.VERIFICATION_STARTED,
            EventType.VERIFICATION_COMPLETED,
            EventType.ARTIFACT_CORRECTED,
            EventType.ARTIFACT_RECOVERED,
        }:
            if not self.agent_id or not self.artifact_id:
                raise ValueError(f"{self.event_type.value} requires agent_id and artifact_id")
        if self.event_type == EventType.VERIFICATION_COMPLETED:
            verdict = self.details.get("verdict")
            if verdict not in {item.value for item in VerificationVerdict}:
                raise ValueError(
                    "verification_completed details.verdict must be one of "
                    + ", ".join(item.value for item in VerificationVerdict)
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "event_type": self.event_type.value,
            "step": self.step,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "artifact_id": self.artifact_id,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "edge_id": self.edge_id,
            "prompt_id": self.prompt_id,
            "parent_event_ids": list(self.parent_event_ids),
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LifecycleEvent:
        return cls(
            event_id=str(value["event_id"]),
            run_id=str(value["run_id"]),
            event_type=EventType(value["event_type"]),
            step=int(value["step"]),
            timestamp=str(value["timestamp"]),
            agent_id=value.get("agent_id"),
            artifact_id=value.get("artifact_id"),
            source_agent_id=value.get("source_agent_id"),
            target_agent_id=value.get("target_agent_id"),
            edge_id=value.get("edge_id"),
            prompt_id=value.get("prompt_id"),
            parent_event_ids=tuple(str(item) for item in value.get("parent_event_ids", [])),
            details=dict(value.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class RunOutcome:
    record_type: ClassVar[str] = "outcome"

    run_id: str
    success: bool | None
    score: float | None
    final_step: int
    evaluator: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float | None = None
    cost_usd: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.run_id, "outcome run_id")
        _assert_nonempty(self.evaluator, "outcome evaluator")
        if self.success is not None and not isinstance(self.success, bool):
            raise ValueError("outcome success must be boolean or null")
        if self.score is not None and not isinstance(self.score, int | float):
            raise ValueError("outcome score must be numeric or null")
        if not isinstance(self.final_step, int) or self.final_step < 0:
            raise ValueError("outcome final_step must be a non-negative integer")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or value < 0:
                raise ValueError(f"outcome {name} must be a non-negative integer")
        for name in ("latency_ms", "cost_usd"):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int | float) or value < 0
            ):
                raise ValueError(f"outcome {name} must be non-negative or null")
        _assert_json_object(self.details, "outcome details")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "run_id": self.run_id,
            "success": self.success,
            "score": self.score,
            "final_step": self.final_step,
            "evaluator": self.evaluator,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunOutcome:
        return cls(
            run_id=str(value["run_id"]),
            success=value.get("success"),
            score=float(value["score"]) if value.get("score") is not None else None,
            final_step=int(value["final_step"]),
            evaluator=str(value["evaluator"]),
            input_tokens=int(value.get("input_tokens", 0)),
            output_tokens=int(value.get("output_tokens", 0)),
            latency_ms=(
                float(value["latency_ms"])
                if value.get("latency_ms") is not None
                else None
            ),
            cost_usd=(
                float(value["cost_usd"]) if value.get("cost_usd") is not None else None
            ),
            details=dict(value.get("details", {})),
        )


TraceRecord: TypeAlias = (
    RunManifest | ArtifactRecord | PromptRecord | LifecycleEvent | RunOutcome
)


def record_from_dict(value: dict[str, Any]) -> TraceRecord:
    record_type = value.get("record_type")
    classes = {
        RunManifest.record_type: RunManifest,
        ArtifactRecord.record_type: ArtifactRecord,
        PromptRecord.record_type: PromptRecord,
        LifecycleEvent.record_type: LifecycleEvent,
        RunOutcome.record_type: RunOutcome,
    }
    cls = classes.get(record_type)
    if cls is None:
        raise ValueError(f"unknown record_type {record_type!r}")
    return cls.from_dict(value)


def prompt_sha256(messages: tuple[dict[str, str], ...]) -> str:
    canonical = json.dumps(
        list(messages),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
