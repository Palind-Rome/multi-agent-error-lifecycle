"""Versioned, audit-oriented records for multi-agent lifecycle traces.

Schema v0.2 separates possession, surfacing, transport, actual prompt exposure,
integration/adoption, verification, governance actuation, commitment execution,
and outcome.  It also preserves missing/invalid evidence instead of silently
turning unknown observations into successes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, TypeAlias

SCHEMA_VERSION = "0.2.0"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class TruthStatus(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class ArtifactOrigin(StrEnum):
    NATURAL_GENERATION = "natural_generation"
    USER_ASSERTION = "user_assertion"
    ENVIRONMENT = "environment"
    CONTROLLED_INJECTION = "controlled_injection"
    PRIVATE_INFORMATION = "private_information"
    IN_TRANSIT_CORRUPTION = "in_transit_corruption"
    PROFILE_TRANSFORM = "profile_transform"
    BENCHMARK_PROBE = "benchmark_probe"
    SHAM = "sham"


class ArtifactKind(StrEnum):
    CLAIM = "claim"
    CONSTRAINT = "constraint"
    REQUIREMENT = "requirement"
    PRIVATE_FACT = "private_fact"
    TRACER = "tracer"
    PLAN = "plan"
    COMMITMENT = "commitment"
    INTERFACE_CONTRACT = "interface_contract"
    DERIVED_RESULT = "derived_result"
    PATCH_CLAIM = "patch_claim"
    TEST_EVIDENCE = "test_evidence"
    TOOL_OUTPUT = "tool_output"


class VerificationVerdict(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


class VerificationTiming(StrEnum):
    PRE_ADOPTION = "pre_adoption"
    POST_ADOPTION = "post_adoption"


class VerificationCompletionStatus(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    TOOL_ERROR = "tool_error"
    TIMEOUT = "timeout"


class EvidenceValidity(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class AttestationStatus(StrEnum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"
    TIMEOUT = "timeout"
    ERROR = "error"


class AttestationVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"


class CallStatus(StrEnum):
    ATTEMPTED = "attempted"
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class ToolCallStatus(StrEnum):
    NOT_RUN = "not_run"
    SUCCESS = "success"
    PARSE_ERROR = "parse_error"
    SCHEMA_INVALID = "schema_invalid"
    PERMISSION_DENIED = "permission_denied"
    EXECUTION_ERROR = "execution_error"
    ENVIRONMENT_ERROR = "environment_error"
    TIMEOUT = "timeout"


class GraderStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


class OutcomeKind(StrEnum):
    RECOGNIZED_TASK = "recognized_task"
    DIAGNOSTIC_ONLY = "diagnostic_only"
    SYNTHETIC_SMOKE = "synthetic_smoke"
    UNAVAILABLE = "unavailable"


class RunStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    ACTION_CAP = "action_cap"
    PROVIDER_ERROR = "provider_error"
    SETUP_ERROR = "setup_error"
    INVALID_OUTPUT = "invalid_output"


class EventType(StrEnum):
    ARTIFACT_GENERATED = "artifact_generated"
    ARTIFACT_POSSESSED = "artifact_possessed"
    ARTIFACT_SURFACED = "artifact_surfaced"
    MESSAGE_SENT = "message_sent"
    MESSAGE_DELIVERED = "message_delivered"
    ARTIFACT_EXPOSED = "artifact_exposed"
    ARTIFACT_INTEGRATED = "artifact_integrated"
    ARTIFACT_ADOPTED = "artifact_adopted"
    ARTIFACT_REJECTED = "artifact_rejected"
    ARTIFACT_UNCERTAIN = "artifact_uncertain"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    ARTIFACT_CONTAINED = "artifact_contained"
    ROLLBACK_STARTED = "rollback_started"
    ROLLBACK_COMPLETED = "rollback_completed"
    ARTIFACT_CORRECTED = "artifact_corrected"
    ARTIFACT_RECOVERED = "artifact_recovered"
    ARTIFACT_RELAPSED = "artifact_relapsed"
    ARTIFACT_ACKNOWLEDGED = "artifact_acknowledged"
    PLAN_UPDATED = "plan_updated"
    COMMITMENT_MADE = "commitment_made"
    COMMITMENT_ACKNOWLEDGED = "commitment_acknowledged"
    COMMITMENT_FULFILLED = "commitment_fulfilled"
    COMMITMENT_BREACHED = "commitment_breached"
    COMMITMENT_WITHDRAWN = "commitment_withdrawn"
    ACTION_TAKEN = "action_taken"
    ACCESS_ATTEMPTED = "access_attempted"
    ACCESS_COMPLETED = "access_completed"
    ROLE_VIOLATION_ATTEMPTED = "role_violation_attempted"
    ROLE_VIOLATION_SUCCEEDED = "role_violation_succeeded"
    RUN_FINALIZED = "run_finalized"


def _assert_nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _assert_optional_nonempty(value: str | None, name: str) -> None:
    if value is not None:
        _assert_nonempty(value, name)


def _assert_json_object(value: dict[str, Any], name: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain only JSON-serializable values") from exc


def _assert_sha256(value: str | None, name: str, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _assert_nonnegative_number(value: int | float | None, name: str) -> None:
    if value is not None and (
        not isinstance(value, int | float) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(f"{name} must be non-negative or null")


def _enum_values(enum_type: type[StrEnum]) -> set[str]:
    return {item.value for item in enum_type}


@dataclass(frozen=True, slots=True)
class AccessPolicy:
    spec_access: str = "none"
    brief_access: str = "none"
    workspace_read: bool = False
    workspace_write: bool = False
    execute: bool = False
    attest: bool = False
    history_scope: str = "none"
    allowed_tools: tuple[str, ...] = ()
    allowed_roots: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.spec_access not in {"none", "summary", "full", "private"}:
            raise ValueError("access policy spec_access is invalid")
        if self.brief_access not in {"none", "summary", "full", "private"}:
            raise ValueError("access policy brief_access is invalid")
        if self.history_scope not in {"none", "parents", "own", "shared", "full"}:
            raise ValueError("access policy history_scope is invalid")
        for value in (*self.allowed_tools, *self.allowed_roots):
            _assert_nonempty(value, "access policy entry")
        _assert_json_object(self.metadata, "access policy metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "allowed_tools": list(self.allowed_tools),
            "allowed_roots": list(self.allowed_roots),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AccessPolicy:
        return cls(
            spec_access=str(value.get("spec_access", "none")),
            brief_access=str(value.get("brief_access", "none")),
            workspace_read=bool(value.get("workspace_read", False)),
            workspace_write=bool(value.get("workspace_write", False)),
            execute=bool(value.get("execute", False)),
            attest=bool(value.get("attest", False)),
            history_scope=str(value.get("history_scope", "none")),
            allowed_tools=tuple(str(item) for item in value.get("allowed_tools", [])),
            allowed_roots=tuple(str(item) for item in value.get("allowed_roots", [])),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class JudgeSpec:
    judge_id: str
    provider: str
    model: str
    purpose: str
    prompt_name: str
    prompt_sha256: str
    scoring_mode: str
    calibration_dataset: str | None = None
    calibration_version: str | None = None
    agreement_reference: str | None = None
    tested_model_disjoint: bool | None = None
    blind_fields: tuple[str, ...] = ()
    privileged_fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in (
            "judge_id",
            "provider",
            "model",
            "purpose",
            "prompt_name",
            "scoring_mode",
        ):
            _assert_nonempty(getattr(self, name), f"judge {name}")
        _assert_sha256(self.prompt_sha256, "judge prompt_sha256", required=True)
        _assert_optional_nonempty(self.calibration_dataset, "calibration_dataset")
        _assert_optional_nonempty(self.calibration_version, "calibration_version")
        _assert_json_object(self.metadata, "judge metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "blind_fields": list(self.blind_fields),
            "privileged_fields": list(self.privileged_fields),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> JudgeSpec:
        return cls(
            judge_id=str(value["judge_id"]),
            provider=str(value["provider"]),
            model=str(value["model"]),
            purpose=str(value["purpose"]),
            prompt_name=str(value["prompt_name"]),
            prompt_sha256=str(value["prompt_sha256"]),
            scoring_mode=str(value["scoring_mode"]),
            calibration_dataset=value.get("calibration_dataset"),
            calibration_version=value.get("calibration_version"),
            agreement_reference=value.get("agreement_reference"),
            tested_model_disjoint=value.get("tested_model_disjoint"),
            blind_fields=tuple(str(item) for item in value.get("blind_fields", [])),
            privileged_fields=tuple(
                str(item) for item in value.get("privileged_fields", [])
            ),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class AgentSpec:
    agent_id: str
    role: str
    provider: str = "unassigned"
    model: str = "unassigned"
    access_policy: AccessPolicy | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("agent_id", "role", "provider", "model"):
            _assert_nonempty(getattr(self, name), name)
        if self.access_policy:
            self.access_policy.validate()
        _assert_json_object(self.metadata, "agent metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "access_policy": (
                self.access_policy.to_dict() if self.access_policy is not None else None
            ),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AgentSpec:
        policy = value.get("access_policy")
        return cls(
            agent_id=str(value["agent_id"]),
            role=str(value["role"]),
            provider=str(value.get("provider", "unassigned")),
            model=str(value.get("model", "unassigned")),
            access_policy=AccessPolicy.from_dict(policy) if isinstance(policy, dict) else None,
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
    seed: int | None
    started_at: str
    agents: tuple[AgentSpec, ...]
    topology: tuple[EdgeSpec, ...]
    protocol_kind: str = "instrumentation"
    suite_kind: str = "native"
    purpose: str = "engineering_smoke"
    pair_id: str | None = None
    cluster_id: str | None = None
    assignment_id: str | None = None
    analysis_eligible: bool = False
    execution_status: str = "ready"
    review_status: str = "not_required"
    preregistration_hash: str | None = None
    native_task_hash: str | None = None
    upstream_commit: str | None = None
    code_commit: str | None = None
    judges: tuple[JudgeSpec, ...] = ()
    config: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> None:
        for name in (
            "run_id",
            "task_id",
            "condition_id",
            "benchmark",
            "started_at",
            "protocol_kind",
            "suite_kind",
            "purpose",
            "execution_status",
            "review_status",
        ):
            _assert_nonempty(getattr(self, name), name)
        if self.seed is not None and not isinstance(self.seed, int):
            raise ValueError("seed must be an integer or null")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema_version {self.schema_version!r}; "
                f"expected {SCHEMA_VERSION!r}"
            )
        if self.execution_status not in {"ready", "paused", "blocked"}:
            raise ValueError("execution_status must be ready, paused, or blocked")
        if not isinstance(self.analysis_eligible, bool):
            raise ValueError("analysis_eligible must be boolean")
        if not self.agents:
            raise ValueError("manifest must contain at least one agent")
        for agent in self.agents:
            agent.validate()
        for edge in self.topology:
            edge.validate()
        for judge in self.judges:
            judge.validate()
        _assert_optional_nonempty(self.pair_id, "pair_id")
        _assert_optional_nonempty(self.cluster_id, "cluster_id")
        _assert_optional_nonempty(self.assignment_id, "assignment_id")
        _assert_sha256(self.preregistration_hash, "preregistration_hash")
        _assert_sha256(self.native_task_hash, "native_task_hash")
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
            "protocol_kind": self.protocol_kind,
            "suite_kind": self.suite_kind,
            "purpose": self.purpose,
            "pair_id": self.pair_id,
            "cluster_id": self.cluster_id,
            "assignment_id": self.assignment_id,
            "analysis_eligible": self.analysis_eligible,
            "execution_status": self.execution_status,
            "review_status": self.review_status,
            "preregistration_hash": self.preregistration_hash,
            "native_task_hash": self.native_task_hash,
            "upstream_commit": self.upstream_commit,
            "code_commit": self.code_commit,
            "judges": [judge.to_dict() for judge in self.judges],
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunManifest:
        return cls(
            run_id=str(value["run_id"]),
            task_id=str(value["task_id"]),
            condition_id=str(value["condition_id"]),
            benchmark=str(value["benchmark"]),
            seed=int(value["seed"]) if value.get("seed") is not None else None,
            started_at=str(value["started_at"]),
            agents=tuple(AgentSpec.from_dict(item) for item in value.get("agents", [])),
            topology=tuple(EdgeSpec.from_dict(item) for item in value.get("topology", [])),
            protocol_kind=str(value.get("protocol_kind", "instrumentation")),
            suite_kind=str(value.get("suite_kind", "native")),
            purpose=str(value.get("purpose", "engineering_smoke")),
            pair_id=value.get("pair_id"),
            cluster_id=value.get("cluster_id"),
            assignment_id=value.get("assignment_id"),
            analysis_eligible=bool(value.get("analysis_eligible", False)),
            execution_status=str(value.get("execution_status", "ready")),
            review_status=str(value.get("review_status", "not_required")),
            preregistration_hash=value.get("preregistration_hash"),
            native_task_hash=value.get("native_task_hash"),
            upstream_commit=value.get("upstream_commit"),
            code_commit=value.get("code_commit"),
            judges=tuple(JudgeSpec.from_dict(item) for item in value.get("judges", [])),
            config=dict(value.get("config", {})),
            schema_version=str(value.get("schema_version", "")),
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    record_type: ClassVar[str] = "artifact"

    artifact_id: str
    run_id: str
    source_agent_id: str | None
    created_step: int
    truth_status: TruthStatus
    content: str
    origin: ArtifactOrigin = ArtifactOrigin.NATURAL_GENERATION
    kind: ArtifactKind = ArtifactKind.CLAIM
    origin_actor_id: str | None = None
    required_to_surface: bool = False
    parent_artifact_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.artifact_id, "artifact_id")
        _assert_nonempty(self.run_id, "artifact run_id")
        _assert_optional_nonempty(self.source_agent_id, "artifact source_agent_id")
        _assert_optional_nonempty(self.origin_actor_id, "artifact origin_actor_id")
        if not isinstance(self.created_step, int) or self.created_step < 0:
            raise ValueError("artifact created_step must be a non-negative integer")
        if not isinstance(self.truth_status, TruthStatus):
            raise ValueError("artifact truth_status must be a TruthStatus")
        if not isinstance(self.origin, ArtifactOrigin):
            raise ValueError("artifact origin must be an ArtifactOrigin")
        if not isinstance(self.kind, ArtifactKind):
            raise ValueError("artifact kind must be an ArtifactKind")
        if not isinstance(self.content, str):
            raise ValueError("artifact content must be a string")
        if not isinstance(self.required_to_surface, bool):
            raise ValueError("required_to_surface must be boolean")
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
            "origin": self.origin.value,
            "kind": self.kind.value,
            "origin_actor_id": self.origin_actor_id,
            "required_to_surface": self.required_to_surface,
            "parent_artifact_ids": list(self.parent_artifact_ids),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ArtifactRecord:
        return cls(
            artifact_id=str(value["artifact_id"]),
            run_id=str(value["run_id"]),
            source_agent_id=value.get("source_agent_id"),
            created_step=int(value["created_step"]),
            truth_status=TruthStatus(value["truth_status"]),
            content=str(value.get("content", "")),
            origin=ArtifactOrigin(value.get("origin", "natural_generation")),
            kind=ArtifactKind(value.get("kind", "claim")),
            origin_actor_id=value.get("origin_actor_id"),
            required_to_surface=bool(value.get("required_to_surface", False)),
            parent_artifact_ids=tuple(
                str(item) for item in value.get("parent_artifact_ids", [])
            ),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class InformationAssignmentRecord:
    record_type: ClassVar[str] = "information_assignment"

    assignment_id: str
    run_id: str
    artifact_id: str
    holder_agent_ids: tuple[str, ...]
    authorized_agent_ids: tuple[str, ...]
    visibility_scope: str
    required_for_solution: bool
    assigned_step: int = 0
    evidence_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("assignment_id", "run_id", "artifact_id", "visibility_scope"):
            _assert_nonempty(getattr(self, name), name)
        if not self.holder_agent_ids:
            raise ValueError("information assignment must have at least one holder")
        if not set(self.holder_agent_ids).issubset(set(self.authorized_agent_ids)):
            raise ValueError("initial holders must be authorized")
        if not isinstance(self.assigned_step, int) or self.assigned_step < 0:
            raise ValueError("assigned_step must be a non-negative integer")
        _assert_json_object(self.metadata, "information assignment metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "assignment_id": self.assignment_id,
            "run_id": self.run_id,
            "artifact_id": self.artifact_id,
            "holder_agent_ids": list(self.holder_agent_ids),
            "authorized_agent_ids": list(self.authorized_agent_ids),
            "visibility_scope": self.visibility_scope,
            "required_for_solution": self.required_for_solution,
            "assigned_step": self.assigned_step,
            "evidence_ref": self.evidence_ref,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InformationAssignmentRecord:
        return cls(
            assignment_id=str(value["assignment_id"]),
            run_id=str(value["run_id"]),
            artifact_id=str(value["artifact_id"]),
            holder_agent_ids=tuple(str(item) for item in value["holder_agent_ids"]),
            authorized_agent_ids=tuple(
                str(item) for item in value.get("authorized_agent_ids", [])
            ),
            visibility_scope=str(value["visibility_scope"]),
            required_for_solution=bool(value["required_for_solution"]),
            assigned_step=int(value.get("assigned_step", 0)),
            evidence_ref=value.get("evidence_ref"),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class InjectionRecord:
    record_type: ClassVar[str] = "injection"

    injection_id: str
    run_id: str
    artifact_id: str
    corruption_type: str
    validation_verdict: str
    target_agent_id: str | None = None
    target_edge_id: str | None = None
    nominal_dose: float | None = None
    realized_dose: float | None = None
    dose_unit: str | None = None
    ground_truth_ref: str | None = None
    validator: str | None = None
    is_sham: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in (
            "injection_id",
            "run_id",
            "artifact_id",
            "corruption_type",
            "validation_verdict",
        ):
            _assert_nonempty(getattr(self, name), name)
        if not self.target_agent_id and not self.target_edge_id:
            raise ValueError("injection requires target_agent_id or target_edge_id")
        if self.validation_verdict not in {
            "successful",
            "failed",
            "inconclusive",
            "not_measured",
        }:
            raise ValueError("injection validation_verdict is invalid")
        _assert_nonnegative_number(self.nominal_dose, "injection nominal_dose")
        _assert_nonnegative_number(self.realized_dose, "injection realized_dose")
        if (self.nominal_dose is not None or self.realized_dose is not None) and not self.dose_unit:
            raise ValueError("dose_unit is required when a dose is present")
        _assert_json_object(self.metadata, "injection metadata")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "record_type": self.record_type}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InjectionRecord:
        return cls(
            injection_id=str(value["injection_id"]),
            run_id=str(value["run_id"]),
            artifact_id=str(value["artifact_id"]),
            corruption_type=str(value["corruption_type"]),
            validation_verdict=str(value["validation_verdict"]),
            target_agent_id=value.get("target_agent_id"),
            target_edge_id=value.get("target_edge_id"),
            nominal_dose=(
                float(value["nominal_dose"])
                if value.get("nominal_dose") is not None
                else None
            ),
            realized_dose=(
                float(value["realized_dose"])
                if value.get("realized_dose") is not None
                else None
            ),
            dose_unit=value.get("dose_unit"),
            ground_truth_ref=value.get("ground_truth_ref"),
            validator=value.get("validator"),
            is_sham=bool(value.get("is_sham", False)),
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
    call_id: str | None = None
    round_id: str | None = None
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
            if not isinstance(message, dict) or set(message) != {"role", "content"}:
                raise ValueError(
                    f"prompt message {index} must contain exactly role and content"
                )
            _assert_nonempty(message["role"], f"prompt message {index} role")
            if not isinstance(message["content"], str):
                raise ValueError(f"prompt message {index} content must be a string")
        _assert_sha256(self.content_sha256, "prompt content_sha256", required=True)
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
            "call_id": self.call_id,
            "round_id": self.round_id,
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
            redacted=bool(value.get("redacted", False)),
            call_id=value.get("call_id"),
            round_id=value.get("round_id"),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class MessageRecord:
    record_type: ClassVar[str] = "message"

    message_id: str
    run_id: str
    source_agent_id: str
    target_agent_id: str
    sent_step: int
    content: str
    content_sha256: str
    expected_artifact_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    delivered: bool | None = None
    delivered_step: int | None = None
    included_prompt_id: str | None = None
    redacted: bool = False
    local_sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("message_id", "run_id", "source_agent_id", "target_agent_id"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.sent_step, int) or self.sent_step < 0:
            raise ValueError("message sent_step must be a non-negative integer")
        if self.delivered_step is not None and self.delivered_step < self.sent_step:
            raise ValueError("message delivered_step cannot precede sent_step")
        if self.delivered is False and self.delivered_step is not None:
            raise ValueError("undelivered message cannot have delivered_step")
        _assert_sha256(self.content_sha256, "message content_sha256", required=True)
        if text_sha256(self.content) != self.content_sha256 and not self.redacted:
            raise ValueError("unredacted message content does not match content_sha256")
        _assert_json_object(self.metadata, "message metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": self.record_type,
            "message_id": self.message_id,
            "run_id": self.run_id,
            "source_agent_id": self.source_agent_id,
            "target_agent_id": self.target_agent_id,
            "sent_step": self.sent_step,
            "content": self.content,
            "content_sha256": self.content_sha256,
            "expected_artifact_ids": list(self.expected_artifact_ids),
            "artifact_ids": list(self.artifact_ids),
            "delivered": self.delivered,
            "delivered_step": self.delivered_step,
            "included_prompt_id": self.included_prompt_id,
            "redacted": self.redacted,
            "local_sequence": self.local_sequence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MessageRecord:
        return cls(
            message_id=str(value["message_id"]),
            run_id=str(value["run_id"]),
            source_agent_id=str(value["source_agent_id"]),
            target_agent_id=str(value["target_agent_id"]),
            sent_step=int(value["sent_step"]),
            content=str(value.get("content", "")),
            content_sha256=str(value["content_sha256"]),
            expected_artifact_ids=tuple(
                str(item) for item in value.get("expected_artifact_ids", [])
            ),
            artifact_ids=tuple(str(item) for item in value.get("artifact_ids", [])),
            delivered=value.get("delivered"),
            delivered_step=(
                int(value["delivered_step"])
                if value.get("delivered_step") is not None
                else None
            ),
            included_prompt_id=value.get("included_prompt_id"),
            redacted=bool(value.get("redacted", False)),
            local_sequence=(
                int(value["local_sequence"])
                if value.get("local_sequence") is not None
                else None
            ),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    record_type: ClassVar[str] = "evidence"

    evidence_id: str
    run_id: str
    kind: str
    created_step: int
    validity: EvidenceValidity
    artifact_id: str | None = None
    producer_agent_id: str | None = None
    source: str | None = None
    command: str | None = None
    exit_code: int | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    workspace_snapshot_sha256: str | None = None
    independent: bool | None = None
    replayed: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("evidence_id", "run_id", "kind"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.created_step, int) or self.created_step < 0:
            raise ValueError("evidence created_step must be non-negative")
        if not isinstance(self.validity, EvidenceValidity):
            raise ValueError("evidence validity must be an EvidenceValidity")
        for name in ("stdout_sha256", "stderr_sha256", "workspace_snapshot_sha256"):
            _assert_sha256(getattr(self, name), f"evidence {name}")
        _assert_json_object(self.metadata, "evidence metadata")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "record_type": self.record_type, "validity": self.validity.value}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceRecord:
        return cls(
            evidence_id=str(value["evidence_id"]),
            run_id=str(value["run_id"]),
            kind=str(value["kind"]),
            created_step=int(value["created_step"]),
            validity=EvidenceValidity(value["validity"]),
            artifact_id=value.get("artifact_id"),
            producer_agent_id=value.get("producer_agent_id"),
            source=value.get("source"),
            command=value.get("command"),
            exit_code=value.get("exit_code"),
            stdout_sha256=value.get("stdout_sha256"),
            stderr_sha256=value.get("stderr_sha256"),
            workspace_snapshot_sha256=value.get("workspace_snapshot_sha256"),
            independent=value.get("independent"),
            replayed=value.get("replayed"),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    record_type: ClassVar[str] = "model_call"

    call_id: str
    run_id: str
    agent_id: str
    prompt_id: str
    step: int
    status: CallStatus
    provider: str
    model: str
    response_sha256: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    raw_response_id: str | None = None
    error_type: str | None = None
    sampling: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("call_id", "run_id", "agent_id", "prompt_id", "provider", "model"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.step, int) or self.step < 0:
            raise ValueError("model call step must be non-negative")
        if not isinstance(self.status, CallStatus):
            raise ValueError("model call status must be a CallStatus")
        _assert_sha256(self.response_sha256, "model call response_sha256")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or null")
        _assert_nonnegative_number(self.latency_ms, "model call latency_ms")
        _assert_nonnegative_number(self.cost_usd, "model call cost_usd")
        _assert_json_object(self.sampling, "model call sampling")
        _assert_json_object(self.metadata, "model call metadata")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "record_type": self.record_type, "status": self.status.value}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ModelCallRecord:
        return cls(
            call_id=str(value["call_id"]),
            run_id=str(value["run_id"]),
            agent_id=str(value["agent_id"]),
            prompt_id=str(value["prompt_id"]),
            step=int(value["step"]),
            status=CallStatus(value["status"]),
            provider=str(value["provider"]),
            model=str(value["model"]),
            response_sha256=value.get("response_sha256"),
            input_tokens=value.get("input_tokens"),
            output_tokens=value.get("output_tokens"),
            latency_ms=value.get("latency_ms"),
            cost_usd=value.get("cost_usd"),
            raw_response_id=value.get("raw_response_id"),
            error_type=value.get("error_type"),
            sampling=dict(value.get("sampling", {})),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    record_type: ClassVar[str] = "tool_call"

    tool_call_id: str
    run_id: str
    agent_id: str
    step: int
    tool_name: str
    status: ToolCallStatus
    arguments_sha256: str | None = None
    authorized: bool | None = None
    result_sha256: str | None = None
    error_type: str | None = None
    depends_on_artifact_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("tool_call_id", "run_id", "agent_id", "tool_name"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.step, int) or self.step < 0:
            raise ValueError("tool call step must be non-negative")
        if not isinstance(self.status, ToolCallStatus):
            raise ValueError("tool call status must be a ToolCallStatus")
        _assert_sha256(self.arguments_sha256, "tool call arguments_sha256")
        _assert_sha256(self.result_sha256, "tool call result_sha256")
        _assert_json_object(self.metadata, "tool call metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "record_type": self.record_type,
            "status": self.status.value,
            "depends_on_artifact_ids": list(self.depends_on_artifact_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ToolCallRecord:
        return cls(
            tool_call_id=str(value["tool_call_id"]),
            run_id=str(value["run_id"]),
            agent_id=str(value["agent_id"]),
            step=int(value["step"]),
            tool_name=str(value["tool_name"]),
            status=ToolCallStatus(value["status"]),
            arguments_sha256=value.get("arguments_sha256"),
            authorized=value.get("authorized"),
            result_sha256=value.get("result_sha256"),
            error_type=value.get("error_type"),
            depends_on_artifact_ids=tuple(
                str(item) for item in value.get("depends_on_artifact_ids", [])
            ),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class AnnotationRecord:
    record_type: ClassVar[str] = "annotation"

    annotation_id: str
    run_id: str
    taxonomy: str
    taxonomy_version: str
    labels: tuple[str, ...]
    annotator: str
    identifiability: str
    target_event_ids: tuple[str, ...] = ()
    artifact_id: str | None = None
    agent_id: str | None = None
    evidence_event_ids: tuple[str, ...] = ()
    evidence_spans: tuple[str, ...] = ()
    prompt_sha256: str | None = None
    model: str | None = None
    blind_fields: tuple[str, ...] = ()
    confidence: float | None = None
    adjudication: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in (
            "annotation_id",
            "run_id",
            "taxonomy",
            "taxonomy_version",
            "annotator",
            "identifiability",
        ):
            _assert_nonempty(getattr(self, name), name)
        if not self.labels:
            raise ValueError("annotation labels must be non-empty")
        _assert_sha256(self.prompt_sha256, "annotation prompt_sha256")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("annotation confidence must be in [0, 1]")
        _assert_json_object(self.metadata, "annotation metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "record_type": self.record_type,
            "labels": list(self.labels),
            "target_event_ids": list(self.target_event_ids),
            "evidence_event_ids": list(self.evidence_event_ids),
            "evidence_spans": list(self.evidence_spans),
            "blind_fields": list(self.blind_fields),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AnnotationRecord:
        return cls(
            annotation_id=str(value["annotation_id"]),
            run_id=str(value["run_id"]),
            taxonomy=str(value["taxonomy"]),
            taxonomy_version=str(value["taxonomy_version"]),
            labels=tuple(str(item) for item in value.get("labels", [])),
            annotator=str(value["annotator"]),
            identifiability=str(value["identifiability"]),
            target_event_ids=tuple(
                str(item) for item in value.get("target_event_ids", [])
            ),
            artifact_id=value.get("artifact_id"),
            agent_id=value.get("agent_id"),
            evidence_event_ids=tuple(
                str(item) for item in value.get("evidence_event_ids", [])
            ),
            evidence_spans=tuple(
                str(item) for item in value.get("evidence_spans", [])
            ),
            prompt_sha256=value.get("prompt_sha256"),
            model=value.get("model"),
            blind_fields=tuple(str(item) for item in value.get("blind_fields", [])),
            confidence=value.get("confidence"),
            adjudication=value.get("adjudication"),
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

        message_events = {EventType.MESSAGE_SENT, EventType.MESSAGE_DELIVERED}
        if self.event_type in message_events:
            if not self.source_agent_id or not self.target_agent_id:
                raise ValueError(
                    f"{self.event_type.value} requires source_agent_id and target_agent_id"
                )
            _assert_nonempty(str(self.details.get("message_id", "")), "details.message_id")
            if self.event_type == EventType.MESSAGE_SENT and not isinstance(
                self.details.get("artifact_present"), bool
            ):
                raise ValueError("message_sent requires boolean details.artifact_present")

        if self.event_type == EventType.ARTIFACT_EXPOSED:
            if not self.artifact_id or not self.target_agent_id or not self.prompt_id:
                raise ValueError(
                    "artifact_exposed requires artifact_id, target_agent_id, and prompt_id"
                )
            if self.details.get("exposure_evidence") != "exact_provider_request":
                raise ValueError(
                    "artifact_exposed requires exact_provider_request evidence"
                )

        artifact_agent_events = {
            EventType.ARTIFACT_GENERATED,
            EventType.ARTIFACT_POSSESSED,
            EventType.ARTIFACT_SURFACED,
            EventType.ARTIFACT_INTEGRATED,
            EventType.ARTIFACT_ADOPTED,
            EventType.ARTIFACT_REJECTED,
            EventType.ARTIFACT_UNCERTAIN,
            EventType.VERIFICATION_STARTED,
            EventType.VERIFICATION_COMPLETED,
            EventType.ARTIFACT_CONTAINED,
            EventType.ROLLBACK_STARTED,
            EventType.ROLLBACK_COMPLETED,
            EventType.ARTIFACT_CORRECTED,
            EventType.ARTIFACT_RECOVERED,
            EventType.ARTIFACT_RELAPSED,
            EventType.ARTIFACT_ACKNOWLEDGED,
            EventType.PLAN_UPDATED,
            EventType.COMMITMENT_MADE,
            EventType.COMMITMENT_ACKNOWLEDGED,
            EventType.COMMITMENT_FULFILLED,
            EventType.COMMITMENT_BREACHED,
            EventType.COMMITMENT_WITHDRAWN,
        }
        if self.event_type in artifact_agent_events and (
            not self.agent_id or not self.artifact_id
        ):
            raise ValueError(
                f"{self.event_type.value} requires agent_id and artifact_id"
            )

        if self.event_type in {EventType.ARTIFACT_ADOPTED, EventType.ARTIFACT_INTEGRATED}:
            if self.details.get("authoritative") is not True:
                raise ValueError(
                    f"{self.event_type.value} requires details.authoritative=true"
                )
            _assert_nonempty(
                str(self.details.get("evidence_type", "")), "details.evidence_type"
            )

        if self.event_type in {
            EventType.VERIFICATION_STARTED,
            EventType.VERIFICATION_COMPLETED,
        }:
            if self.details.get("timing") not in _enum_values(VerificationTiming):
                raise ValueError("verification event requires valid details.timing")

        if self.event_type == EventType.VERIFICATION_COMPLETED:
            status = self.details.get("completion_status")
            if status not in _enum_values(VerificationCompletionStatus):
                raise ValueError(
                    "verification_completed requires valid completion_status"
                )
            verdict = self.details.get("verdict")
            if verdict not in _enum_values(VerificationVerdict):
                raise ValueError("verification_completed requires a valid verdict")
            if self.details.get("evidence_validity") not in _enum_values(EvidenceValidity):
                raise ValueError(
                    "verification_completed requires valid evidence_validity"
                )
            evidence_ids = self.details.get("evidence_ids")
            if not isinstance(evidence_ids, list):
                raise ValueError("verification_completed requires evidence_ids array")
            coverage = self.details.get("requirement_coverage")
            if coverage is not None and (
                not isinstance(coverage, int | float) or not 0.0 <= coverage <= 1.0
            ):
                raise ValueError("requirement_coverage must be in [0, 1] or null")

        if self.event_type == EventType.ACTION_TAKEN:
            _assert_nonempty(str(self.agent_id or ""), "action agent_id")
            action_id = self.details.get("action_id")
            dependencies = self.details.get("depends_on_artifact_ids")
            _assert_nonempty(str(action_id or ""), "details.action_id")
            if not isinstance(dependencies, list) or not dependencies:
                raise ValueError(
                    "action_taken requires non-empty depends_on_artifact_ids"
                )

        if self.event_type in {
            EventType.COMMITMENT_FULFILLED,
            EventType.COMMITMENT_BREACHED,
        }:
            evidence_ids = self.details.get("evidence_ids")
            if not isinstance(evidence_ids, list):
                raise ValueError(
                    f"{self.event_type.value} requires details.evidence_ids array"
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
            parent_event_ids=tuple(
                str(item) for item in value.get("parent_event_ids", [])
            ),
            details=dict(value.get("details", {})),
        )


@dataclass(frozen=True, slots=True)
class AttestationRecord:
    record_type: ClassVar[str] = "attestation"

    attestation_id: str
    run_id: str
    verifier_agent_id: str
    step: int
    status: AttestationStatus
    verdict: AttestationVerdict | None = None
    raw_sha256: str | None = None
    parse_error: str | None = None
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("attestation_id", "run_id", "verifier_agent_id"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.step, int) or self.step < 0:
            raise ValueError("attestation step must be non-negative")
        if not isinstance(self.status, AttestationStatus):
            raise ValueError("attestation status must be AttestationStatus")
        if self.status == AttestationStatus.VALID and self.verdict is None:
            raise ValueError("valid attestation requires a verdict")
        if self.status != AttestationStatus.VALID and self.verdict is not None:
            raise ValueError("non-valid attestation cannot have a verdict")
        _assert_sha256(self.raw_sha256, "attestation raw_sha256")
        _assert_json_object(self.metadata, "attestation metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "record_type": self.record_type,
            "status": self.status.value,
            "verdict": self.verdict.value if self.verdict else None,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AttestationRecord:
        return cls(
            attestation_id=str(value["attestation_id"]),
            run_id=str(value["run_id"]),
            verifier_agent_id=str(value["verifier_agent_id"]),
            step=int(value["step"]),
            status=AttestationStatus(value["status"]),
            verdict=(
                AttestationVerdict(value["verdict"])
                if value.get("verdict") is not None
                else None
            ),
            raw_sha256=value.get("raw_sha256"),
            parse_error=value.get("parse_error"),
            evidence_ids=tuple(str(item) for item in value.get("evidence_ids", [])),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class GraderRunRecord:
    record_type: ClassVar[str] = "grader_run"

    grader_id: str
    run_id: str
    kind: str
    version: str
    status: GraderStatus
    task_passed: bool | None
    score: float | None
    implementation_sha256: str
    input_snapshot_sha256: str
    raw_output_sha256: str | None = None
    exit_code: int | None = None
    check_results: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        for name in ("grader_id", "run_id", "kind", "version"):
            _assert_nonempty(getattr(self, name), name)
        if not isinstance(self.status, GraderStatus):
            raise ValueError("grader status must be GraderStatus")
        if self.status != GraderStatus.SUCCESS and (
            self.task_passed is not None or self.score is not None
        ):
            raise ValueError("failed grader run cannot provide task outcome")
        _assert_sha256(
            self.implementation_sha256, "grader implementation_sha256", required=True
        )
        _assert_sha256(
            self.input_snapshot_sha256, "grader input_snapshot_sha256", required=True
        )
        _assert_sha256(self.raw_output_sha256, "grader raw_output_sha256")
        _assert_json_object(self.check_results, "grader check_results")
        _assert_json_object(self.metadata, "grader metadata")

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "record_type": self.record_type, "status": self.status.value}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraderRunRecord:
        return cls(
            grader_id=str(value["grader_id"]),
            run_id=str(value["run_id"]),
            kind=str(value["kind"]),
            version=str(value["version"]),
            status=GraderStatus(value["status"]),
            task_passed=value.get("task_passed"),
            score=(
                float(value["score"]) if value.get("score") is not None else None
            ),
            implementation_sha256=str(value["implementation_sha256"]),
            input_snapshot_sha256=str(value["input_snapshot_sha256"]),
            raw_output_sha256=value.get("raw_output_sha256"),
            exit_code=value.get("exit_code"),
            check_results=dict(value.get("check_results", {})),
            metadata=dict(value.get("metadata", {})),
        )


@dataclass(frozen=True, slots=True)
class RunOutcome:
    record_type: ClassVar[str] = "outcome"

    run_id: str
    success: bool | None
    score: float | None
    final_step: int
    evaluator: str
    outcome_kind: OutcomeKind = OutcomeKind.UNAVAILABLE
    run_status: RunStatus = RunStatus.COMPLETED
    grader_id: str | None = None
    usable_completion: bool | None = None
    safe_completion: bool | None = None
    final_artifact_infected: bool | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    cost_usd: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _assert_nonempty(self.run_id, "outcome run_id")
        _assert_nonempty(self.evaluator, "outcome evaluator")
        if self.success is not None and not isinstance(self.success, bool):
            raise ValueError("outcome success must be boolean or null")
        if self.score is not None and (
            not isinstance(self.score, int | float) or isinstance(self.score, bool)
        ):
            raise ValueError("outcome score must be numeric or null")
        if not isinstance(self.final_step, int) or self.final_step < 0:
            raise ValueError("outcome final_step must be a non-negative integer")
        if not isinstance(self.outcome_kind, OutcomeKind):
            raise ValueError("outcome_kind must be an OutcomeKind")
        if not isinstance(self.run_status, RunStatus):
            raise ValueError("run_status must be a RunStatus")
        if self.outcome_kind in {
            OutcomeKind.DIAGNOSTIC_ONLY,
            OutcomeKind.UNAVAILABLE,
        } and (self.success is not None or self.score is not None):
            raise ValueError(
                "diagnostic/unavailable outcome cannot populate task success or score"
            )
        if (
            self.outcome_kind == OutcomeKind.RECOGNIZED_TASK
            and self.run_status == RunStatus.COMPLETED
            and not self.grader_id
        ):
            raise ValueError("completed recognized task outcome requires grader_id")
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"outcome {name} must be non-negative or null")
        _assert_nonnegative_number(self.latency_ms, "outcome latency_ms")
        _assert_nonnegative_number(self.cost_usd, "outcome cost_usd")
        _assert_json_object(self.details, "outcome details")

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "record_type": self.record_type,
            "outcome_kind": self.outcome_kind.value,
            "run_status": self.run_status.value,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RunOutcome:
        return cls(
            run_id=str(value["run_id"]),
            success=value.get("success"),
            score=(
                float(value["score"]) if value.get("score") is not None else None
            ),
            final_step=int(value["final_step"]),
            evaluator=str(value["evaluator"]),
            outcome_kind=OutcomeKind(value.get("outcome_kind", "unavailable")),
            run_status=RunStatus(value.get("run_status", "completed")),
            grader_id=value.get("grader_id"),
            usable_completion=value.get("usable_completion"),
            safe_completion=value.get("safe_completion"),
            final_artifact_infected=value.get("final_artifact_infected"),
            input_tokens=value.get("input_tokens"),
            output_tokens=value.get("output_tokens"),
            latency_ms=value.get("latency_ms"),
            cost_usd=value.get("cost_usd"),
            details=dict(value.get("details", {})),
        )


TraceRecord: TypeAlias = (
    RunManifest
    | ArtifactRecord
    | InformationAssignmentRecord
    | InjectionRecord
    | PromptRecord
    | MessageRecord
    | EvidenceRecord
    | ModelCallRecord
    | ToolCallRecord
    | AnnotationRecord
    | LifecycleEvent
    | AttestationRecord
    | GraderRunRecord
    | RunOutcome
)


def record_from_dict(value: dict[str, Any]) -> TraceRecord:
    record_type = value.get("record_type")
    classes = {
        RunManifest.record_type: RunManifest,
        ArtifactRecord.record_type: ArtifactRecord,
        InformationAssignmentRecord.record_type: InformationAssignmentRecord,
        InjectionRecord.record_type: InjectionRecord,
        PromptRecord.record_type: PromptRecord,
        MessageRecord.record_type: MessageRecord,
        EvidenceRecord.record_type: EvidenceRecord,
        ModelCallRecord.record_type: ModelCallRecord,
        ToolCallRecord.record_type: ToolCallRecord,
        AnnotationRecord.record_type: AnnotationRecord,
        LifecycleEvent.record_type: LifecycleEvent,
        AttestationRecord.record_type: AttestationRecord,
        GraderRunRecord.record_type: GraderRunRecord,
        RunOutcome.record_type: RunOutcome,
    }
    record_class = classes.get(record_type)
    if record_class is None:
        raise ValueError(f"unsupported record_type {record_type!r}")
    return record_class.from_dict(value)


def prompt_sha256(messages: tuple[dict[str, str], ...]) -> str:
    canonical = json.dumps(
        list(messages),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
