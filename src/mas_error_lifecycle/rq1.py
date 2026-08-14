"""Auditable, offline RQ1 tool-result transformation calibration.

This module intentionally implements a derived synthetic suite.  It never
calls a provider and it does not claim native AgentCollabBench validity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from .annotation import (
    RQ1_FACT_ANNOTATION_TAXONOMY,
    RQ1FactAnnotation,
    RQ1FactAnnotationStage,
    RQ1FactAnnotationStatus,
    RQ1FactObservationStatus,
)
from .schema import (
    AgentSpec,
    AnnotationRecord,
    ArtifactKind,
    ArtifactOrigin,
    ArtifactRecord,
    CallStatus,
    EdgeSpec,
    EventType,
    InformationAssignmentRecord,
    LifecycleEvent,
    MessageRecord,
    ModelCallRecord,
    OutcomeKind,
    PromptRecord,
    RQ1_TRANSFORMATION_TAXONOMY,
    RQ1_TRANSFORMATION_TAXONOMY_VERSION,
    RQ1TransformationArm,
    RQ1TransformationMethod,
    RQ1TransformationProducerKind,
    RQ1TransformationRecord,
    RunManifest,
    RunOutcome,
    RunStatus,
    ToolCallRecord,
    ToolCallStatus,
    TruthStatus,
    prompt_sha256,
    text_sha256,
)
from .store import TraceBundle

RQ1_OFFLINE_FIXTURE_ID = "rq1-tool-summary-calibration-v1"
RQ1_OFFLINE_BENCHMARK_ID = "RQ1DerivedToolSummaryCalibration"
RQ1_OFFLINE_PROTOCOL_KIND = "rq1_offline_transformation_calibration"
RQ1_TOKEN_COUNT_METHOD = "whitespace_split"
RQ1_TOKEN_COUNT_VERSION = "1"


def rq1_token_count(text: str) -> int:
    """Count Unicode whitespace-delimited segments (calibration proxy only)."""

    if not isinstance(text, str):
        raise TypeError("RQ1 token counting requires text")
    return len(text.split())


def rq1_downstream_contract_sha256(contract: dict[str, Any]) -> str:
    """Hash a held-fixed downstream contract using canonical JSON."""

    canonical = json.dumps(
        contract,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return text_sha256(canonical)


def extract_rq1_transformations(bundle: TraceBundle) -> tuple[RQ1TransformationRecord, ...]:
    """Parse typed contracts from their versioned AnnotationRecord envelope."""

    rows: list[RQ1TransformationRecord] = []
    for annotation in bundle.annotations:
        if annotation.taxonomy != RQ1_TRANSFORMATION_TAXONOMY:
            continue
        annotation.validate()
        raw = annotation.metadata.get("transformation")
        if not isinstance(raw, dict):
            raise ValueError("missing RQ1 transformation contract")
        row = RQ1TransformationRecord.from_dict(raw)
        row.validate()
        rows.append(row)
    return tuple(rows)


def validate_rq1_arm_set(
    transformations: Iterable[RQ1TransformationRecord],
) -> tuple[RQ1TransformationRecord, ...]:
    """Require one comparable C0/C1/T triple per fixture/repeat/block."""

    rows = tuple(transformations)
    if not rows:
        raise ValueError("RQ1 arm-set validation requires transformations")
    groups: dict[tuple[str, str, str], list[RQ1TransformationRecord]] = {}
    seen_ids: set[str] = set()
    for row in rows:
        row.validate()
        if row.transformation_id in seen_ids:
            raise ValueError("duplicate RQ1 transformation_id")
        seen_ids.add(row.transformation_id)
        groups.setdefault((row.fixture_id, row.repeat_id, row.block_id), []).append(row)

    expected_arms = set(RQ1TransformationArm)
    for key, group in groups.items():
        by_arm = {row.arm: row for row in group}
        if len(group) != len(expected_arms) or set(by_arm) != expected_arms:
            raise ValueError(
                "each RQ1 fixture/repeat/block requires exactly one "
                "raw_passthrough, length_matched_reference, and abstractive_summary"
            )
        first = group[0]
        for row in group[1:]:
            if row.benchmark_id != first.benchmark_id:
                raise ValueError("RQ1 arm block benchmark_id mismatch")
            if row.protocol_kind != first.protocol_kind:
                raise ValueError("RQ1 arm block protocol_kind mismatch")
            if row.source_text_sha256 != first.source_text_sha256:
                raise ValueError("RQ1 arm block source hash mismatch")
            if row.source_char_count != first.source_char_count:
                raise ValueError("RQ1 arm block source char count mismatch")
            if row.source_token_count != first.source_token_count:
                raise ValueError("RQ1 arm block source token count mismatch")
            if row.required_fact_ids != first.required_fact_ids:
                raise ValueError("RQ1 arm block required fact IDs mismatch")
            if row.token_count_method != first.token_count_method:
                raise ValueError("RQ1 arm block token count method mismatch")
            if row.token_count_version != first.token_count_version:
                raise ValueError("RQ1 arm block token count version mismatch")
            if row.tokenizer_name != first.tokenizer_name:
                raise ValueError("RQ1 arm block tokenizer mismatch")
            if row.metadata.get("downstream_task_id") != first.metadata.get(
                "downstream_task_id"
            ):
                raise ValueError("RQ1 arm block downstream task mismatch")
            if row.downstream_contract_sha256 != first.downstream_contract_sha256:
                raise ValueError("RQ1 arm block downstream contract mismatch")
            if row.metadata.get("downstream_contract") != first.metadata.get(
                "downstream_contract"
            ):
                raise ValueError("RQ1 arm block downstream contract mismatch")
            if row.metadata.get("distractor_ids") != first.metadata.get("distractor_ids"):
                raise ValueError("RQ1 arm block distractor manifest mismatch")

        reference = by_arm[RQ1TransformationArm.LENGTH_MATCHED_REFERENCE]
        treatment = by_arm[RQ1TransformationArm.ABSTRACTIVE_SUMMARY]
        raw = by_arm[RQ1TransformationArm.RAW_PASSTHROUGH]
        if (reference.char_budget, reference.token_budget) != (
            treatment.char_budget,
            treatment.token_budget,
        ):
            raise ValueError("C1 and T must have identical char/token budgets")
        if not (
            raw.target_char_count > reference.target_char_count
            and raw.target_char_count > treatment.target_char_count
            and raw.target_token_count > reference.target_token_count
            and raw.target_token_count > treatment.target_token_count
        ):
            raise ValueError("C0 raw input must be longer than C1 and T")

    by_fixture: dict[str, list[RQ1TransformationRecord]] = {}
    for row in rows:
        by_fixture.setdefault(row.fixture_id, []).append(row)
    for fixture_id, fixture_rows in by_fixture.items():
        first = fixture_rows[0]
        fixed_signature = (
            first.benchmark_id,
            first.protocol_kind,
            first.source_text_sha256,
            first.source_char_count,
            first.source_token_count,
            first.required_fact_ids,
            first.token_count_method,
            first.token_count_version,
            first.tokenizer_name,
            first.downstream_contract_sha256,
            tuple(first.metadata.get("distractor_ids", [])),
            first.metadata["downstream_contract"]["task_payload_sha256"],
        )
        for row in fixture_rows[1:]:
            row_signature = (
                row.benchmark_id,
                row.protocol_kind,
                row.source_text_sha256,
                row.source_char_count,
                row.source_token_count,
                row.required_fact_ids,
                row.token_count_method,
                row.token_count_version,
                row.tokenizer_name,
                row.downstream_contract_sha256,
                tuple(row.metadata.get("distractor_ids", [])),
                row.metadata["downstream_contract"]["task_payload_sha256"],
            )
            if row_signature != fixed_signature:
                raise ValueError(
                    f"RQ1 fixture {fixture_id} drifts across repeats/blocks"
                )
        producer_baseline_by_arm: dict[RQ1TransformationArm, tuple[Any, ...]] = {}
        for row in fixture_rows:
            producer_signature: tuple[Any, ...] = (
                row.producer_kind,
                row.producer_id,
                row.producer_model,
                row.producer_prompt_sha256,
                json.dumps(
                    row.metadata.get("producer_contract"),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
            if row.arm == RQ1TransformationArm.LENGTH_MATCHED_REFERENCE:
                producer_signature += (
                    row.target_text_sha256,
                    row.target_char_count,
                    row.target_token_count,
                )
            baseline = producer_baseline_by_arm.setdefault(row.arm, producer_signature)
            if producer_signature != baseline:
                raise ValueError(
                    f"RQ1 fixture {fixture_id} producer policy drifts across repeats"
                )
    return rows


def _validate_rq1_bundle_records(bundle: TraceBundle) -> None:
    """Cross-check nested RQ1 contracts after generic bundle validation."""

    rows = extract_rq1_transformations(bundle)
    if not rows:
        raise ValueError("declared RQ1 trace is missing its transformation contract")
    if len(rows) != 1:
        raise ValueError("each RQ1 transformation trace must contain exactly one contract")
    row = rows[0]
    manifest = bundle.manifest
    if manifest.suite_kind != "derived" or manifest.suite_kind != row.suite_kind:
        raise ValueError("RQ1 transformation manifest must be an explicit derived suite")
    if manifest.protocol_kind != row.protocol_kind:
        raise ValueError("RQ1 transformation protocol_kind mismatch")
    if manifest.benchmark != row.benchmark_id:
        raise ValueError("RQ1 transformation benchmark identity mismatch")
    if manifest.config.get("rq1_fixture_id") != row.fixture_id:
        raise ValueError("RQ1 transformation fixture identity mismatch")
    if manifest.config.get("rq1_repeat_id") != row.repeat_id:
        raise ValueError("RQ1 transformation repeat identity mismatch")
    if manifest.config.get("rq1_block_id") != row.block_id:
        raise ValueError("RQ1 transformation block identity mismatch")
    if manifest.config.get("native_benchmark_claimed") is not False:
        raise ValueError("RQ1 derived manifest must deny native benchmark identity")
    if manifest.config.get("source_native_benchmark_id") != row.source_native_benchmark_id:
        raise ValueError("RQ1 source-native benchmark identity mismatch")
    if manifest.config.get("rq1_downstream_contract_sha256") != row.downstream_contract_sha256:
        raise ValueError("RQ1 manifest downstream contract hash mismatch")
    downstream_contract = row.metadata["downstream_contract"]
    if downstream_contract["task_id"] != manifest.task_id:
        raise ValueError("RQ1 downstream task must equal manifest.task_id")
    if row.metadata.get("downstream_task_id") != downstream_contract["task_id"]:
        raise ValueError("RQ1 downstream task metadata mismatch")
    if manifest.native_task_hash != downstream_contract["task_payload_sha256"]:
        raise ValueError("RQ1 immutable task payload hash mismatch")
    if manifest.config.get("rq1_task_payload_sha256") != downstream_contract[
        "task_payload_sha256"
    ]:
        raise ValueError("RQ1 manifest task payload hash mismatch")
    if row.metadata.get("calibration_only") is True:
        if manifest.analysis_eligible:
            raise ValueError("calibration-only RQ1 trace cannot be analysis_eligible")
        if bundle.outcome.outcome_kind != OutcomeKind.DIAGNOSTIC_ONLY:
            raise ValueError("calibration-only RQ1 trace requires diagnostic outcome")
        if manifest.purpose == "measurement":
            raise ValueError("calibration-only RQ1 trace cannot claim measurement purpose")
    synthetic_evidence = (
        row.metadata.get("synthetic_fixture") is True
        or manifest.config.get("offline_only") is True
        or bundle.outcome.details.get("synthetic_fixture") is True
        or any(artifact.metadata.get("synthetic") is True for artifact in bundle.artifacts)
        or any(call.provider == "offline_fixture" for call in bundle.model_calls)
        or any(call.metadata.get("offline_replay") is True for call in bundle.model_calls)
        or any(call.tool_name.startswith("offline.") for call in bundle.tool_calls)
    )
    if synthetic_evidence:
        if row.benchmark_id != RQ1_OFFLINE_BENCHMARK_ID:
            raise ValueError("synthetic RQ1 trace must retain offline benchmark identity")
        if row.metadata.get("calibration_only") is not True:
            raise ValueError("offline RQ1 benchmark requires calibration_only=true")
        if row.metadata.get("synthetic_fixture") is not True:
            raise ValueError("offline RQ1 benchmark requires synthetic_fixture=true")
        if row.metadata.get("api_called") is not False:
            raise ValueError("offline RQ1 benchmark must deny API use")
        if manifest.purpose != "offline_calibration":
            raise ValueError("offline RQ1 benchmark requires offline_calibration purpose")
        if manifest.analysis_eligible:
            raise ValueError("offline calibration traces cannot be analysis_eligible")
        if bundle.outcome.outcome_kind != OutcomeKind.DIAGNOSTIC_ONLY:
            raise ValueError("offline RQ1 calibration requires diagnostic-only outcome")
        if manifest.config.get("api_called") is not False:
            raise ValueError("offline RQ1 calibration must deny API use")
        if manifest.config.get("offline_only") is not True:
            raise ValueError("offline RQ1 calibration must retain offline_only=true")

    artifacts = {item.artifact_id: item for item in bundle.artifacts}
    assignments = {item.artifact_id: item for item in bundle.information_assignments}
    events = {item.event_id: item for item in bundle.events}
    tools = {item.tool_call_id: item for item in bundle.tool_calls}
    messages = {item.message_id: item for item in bundle.messages}
    prompts = {item.prompt_id: item for item in bundle.prompts}
    calls = {item.call_id: item for item in bundle.model_calls}

    source_call = tools.get(row.source_tool_call_id)
    if source_call is None or source_call.status != ToolCallStatus.SUCCESS:
        raise ValueError("RQ1 source_tool_call_id must reference a successful tool call")
    if source_call.result_sha256 != row.source_text_sha256:
        raise ValueError("RQ1 source tool result hash mismatch")
    if not set(row.required_fact_ids).issubset(source_call.depends_on_artifact_ids):
        raise ValueError("RQ1 source tool required-fact lineage mismatch")
    expected_source_metadata = {
        "source_char_count": row.source_char_count,
        "source_token_count": row.source_token_count,
        "token_count_method": row.token_count_method,
        "token_count_version": row.token_count_version,
    }
    if any(
        source_call.metadata.get(key) != value
        for key, value in expected_source_metadata.items()
    ):
        raise ValueError("RQ1 source tool count provenance mismatch")

    for fact_id in row.required_fact_ids:
        artifact = artifacts.get(fact_id)
        if artifact is None or artifact.truth_status != TruthStatus.TRUE:
            raise ValueError("RQ1 required_fact_ids must reference true artifacts")
        assignment = assignments.get(fact_id)
        if assignment is None or assignment.required_for_solution is not True:
            raise ValueError("RQ1 required facts need required information assignments")
    distractor_ids = row.metadata.get("distractor_ids")
    if not isinstance(distractor_ids, list) or row.metadata.get(
        "distractor_count"
    ) != len(distractor_ids):
        raise ValueError("RQ1 distractor manifest is invalid")
    if manifest.config.get("rq1_distractor_ids") != distractor_ids or manifest.config.get(
        "rq1_distractor_count"
    ) != len(distractor_ids):
        raise ValueError("RQ1 manifest distractor declaration mismatch")
    for distractor_id in distractor_ids:
        if distractor_id in row.required_fact_ids or distractor_id not in artifacts:
            raise ValueError("RQ1 distractors must exist outside required opportunities")
        assignment = assignments.get(distractor_id)
        if assignment is None or assignment.required_for_solution is not False:
            raise ValueError("RQ1 distractors require non-required assignments")
    if not set(distractor_ids).issubset(source_call.depends_on_artifact_ids):
        raise ValueError("RQ1 source tool distractor lineage mismatch")

    parent_events = [events.get(event_id) for event_id in row.parent_event_ids]
    if any(event is None for event in parent_events):
        raise ValueError("RQ1 parent_event_ids reference missing events")
    if any(event.event_type != EventType.ARTIFACT_POSSESSED for event in parent_events if event):
        raise ValueError("RQ1 parent events must be possession observations")
    if {event.artifact_id for event in parent_events if event} != set(row.required_fact_ids):
        raise ValueError("RQ1 parent-event fact lineage mismatch")

    output_event = events.get(row.output_event_id)
    if output_event is None or output_event.event_type != EventType.ACTION_TAKEN:
        raise ValueError("RQ1 output_event_id must reference an action event")
    if output_event.parent_event_ids != row.parent_event_ids:
        raise ValueError("RQ1 output event parent lineage mismatch")
    output_expected = {
        "transformation_id": row.transformation_id,
        "source_tool_call_id": row.source_tool_call_id,
        "source_text_sha256": row.source_text_sha256,
        "target_text_sha256": row.target_text_sha256,
        "target_message_id": row.target_message_id,
        "arm": row.arm.value,
        "method": row.method.value,
    }
    if any(output_event.details.get(key) != value for key, value in output_expected.items()):
        raise ValueError("RQ1 output event contract/hash mismatch")
    if set(output_event.details.get("depends_on_artifact_ids", [])) != set(
        source_call.depends_on_artifact_ids
    ):
        raise ValueError("RQ1 output event source-artifact lineage mismatch")

    message = messages.get(row.target_message_id)
    if message is None:
        raise ValueError("RQ1 target_message_id references a missing message")
    if message.content_sha256 != row.target_text_sha256:
        raise ValueError("RQ1 target message hash mismatch")
    if len(message.content) != row.target_char_count:
        raise ValueError("RQ1 target message char count mismatch")
    if rq1_token_count(message.content) != row.target_token_count:
        raise ValueError("RQ1 target message token count mismatch")
    if tuple(message.expected_artifact_ids) != row.required_fact_ids:
        raise ValueError("RQ1 target message expected-fact lineage mismatch")
    if message.included_prompt_id not in row.downstream_prompt_ids:
        raise ValueError("RQ1 target message is not linked to a downstream prompt")
    if message.metadata.get("transformation_id") != row.transformation_id:
        raise ValueError("RQ1 target message transformation lineage mismatch")
    if row.arm == RQ1TransformationArm.RAW_PASSTHROUGH and any(
        artifacts[artifact_id].content not in message.content
        for artifact_id in source_call.depends_on_artifact_ids
    ):
        raise ValueError("RQ1 raw source text omits a declared source artifact")
    sent = [
        event
        for event in bundle.events
        if event.event_type == EventType.MESSAGE_SENT
        and event.details.get("message_id") == message.message_id
    ]
    if {event.artifact_id for event in sent} != set(message.artifact_ids):
        raise ValueError("RQ1 message-sent artifact lineage mismatch")
    if any(row.output_event_id not in event.parent_event_ids for event in sent):
        raise ValueError("RQ1 message-sent events must descend from output_event_id")

    downstream_response_by_prompt: dict[str, str] = {}
    for prompt_id in row.downstream_prompt_ids:
        prompt = prompts.get(prompt_id)
        if prompt is None:
            raise ValueError("RQ1 downstream_prompt_ids reference missing prompts")
        if prompt.agent_id != message.target_agent_id:
            raise ValueError("RQ1 downstream prompt has the wrong target agent")
        if prompt.metadata.get("actual_full_provider_request_available") is not True:
            raise ValueError("RQ1 downstream prompt must be a full provider request")
        if prompt.metadata.get("transformation_id") != row.transformation_id:
            raise ValueError("RQ1 downstream prompt transformation lineage mismatch")
        if message.message_id not in prompt.metadata.get("included_message_ids", []):
            raise ValueError("RQ1 downstream prompt is not linked to target message")
        if prompt.metadata.get("included_message_sha256") != row.target_text_sha256:
            raise ValueError("RQ1 downstream prompt included-message hash mismatch")
        if prompt.metadata.get("prompt_template_sha256") != downstream_contract[
            "prompt_template_sha256"
        ]:
            raise ValueError("RQ1 downstream prompt template hash mismatch")
        if prompt.metadata.get("prompt_template") != downstream_contract[
            "prompt_template"
        ]:
            raise ValueError("RQ1 downstream prompt template mismatch")
        expected_downstream_messages = (
            {
                "role": "user",
                "content": downstream_contract["prompt_template"].format(
                    transformed_text=message.content
                ),
            },
        )
        if prompt.messages != expected_downstream_messages:
            raise ValueError("RQ1 downstream prompt does not match canonical template")
        if not any(message.content in item["content"] for item in prompt.messages):
            raise ValueError("RQ1 downstream prompt does not contain target message text")
        if prompt.call_id is None:
            raise ValueError("RQ1 downstream prompt requires a linked model call")
        downstream_call = calls.get(prompt.call_id)
        if downstream_call is None or downstream_call.prompt_id != prompt.prompt_id:
            raise ValueError("RQ1 downstream prompt/model-call linkage mismatch")
        if downstream_call.status != CallStatus.SUCCESS:
            raise ValueError("RQ1 downstream model call must be successful")
        if downstream_call.response_sha256 is None:
            raise ValueError("RQ1 downstream model call requires a response hash")
        downstream_response_by_prompt[prompt_id] = downstream_call.response_sha256
        if row.metadata.get("calibration_only") is True and downstream_call.metadata.get(
            "api_called"
        ) is not False:
            raise ValueError("offline RQ1 downstream call must deny API use")
        if downstream_call.model != downstream_contract["model"]:
            raise ValueError("RQ1 downstream model mismatch")
        if downstream_call.provider != downstream_contract["provider_id"]:
            raise ValueError("RQ1 downstream provider mismatch")
        expected_call_metadata = {
            "model_version": downstream_contract["model_version"],
            "context_token_cap": downstream_contract["context_token_cap"],
            "output_token_cap": downstream_contract["output_token_cap"],
            "stopping_rule": downstream_contract["stopping_rule"],
            "scorer_id": downstream_contract["scorer_id"],
            "scorer_version": downstream_contract["scorer_version"],
        }
        if any(
            downstream_call.metadata.get(key) != value
            for key, value in expected_call_metadata.items()
        ):
            raise ValueError("RQ1 downstream model-call contract mismatch")
        if downstream_call.sampling.get("temperature") != downstream_contract[
            "temperature"
        ]:
            raise ValueError("RQ1 downstream temperature mismatch")
        if row.metadata.get("calibration_only") is True and (
            downstream_call.input_tokens is None
            or downstream_call.output_tokens is None
        ):
            raise ValueError(
                "offline RQ1 downstream call requires observed token counts"
            )
        if (
            downstream_call.input_tokens is not None
            and downstream_call.input_tokens > downstream_contract["context_token_cap"]
        ):
            raise ValueError("RQ1 downstream context token cap exceeded")
        if (
            downstream_call.output_tokens is not None
            and downstream_call.output_tokens > downstream_contract["output_token_cap"]
        ):
            raise ValueError("RQ1 downstream output token cap exceeded")

    if row.producer_prompt_id is not None:
        producer_prompt = prompts.get(row.producer_prompt_id)
        if producer_prompt is None:
            raise ValueError("RQ1 producer_prompt_id references a missing prompt")
        if producer_prompt.content_sha256 != row.producer_prompt_sha256:
            raise ValueError("RQ1 producer prompt hash mismatch")
        if producer_prompt.metadata.get("transformation_id") != row.transformation_id:
            raise ValueError("RQ1 producer prompt transformation lineage mismatch")
        if producer_prompt.metadata.get("source_tool_call_id") != row.source_tool_call_id:
            raise ValueError("RQ1 producer prompt source-tool lineage mismatch")
        if producer_prompt.metadata.get("source_text_sha256") != row.source_text_sha256:
            raise ValueError("RQ1 producer prompt source hash mismatch")
        if producer_prompt.metadata.get("source_segment_sha256") != row.source_text_sha256:
            raise ValueError("RQ1 producer prompt source segment hash mismatch")
        if producer_prompt.metadata.get("actual_full_provider_request_available") is not True:
            raise ValueError("RQ1 producer prompt must be a full request")
        if set(producer_prompt.artifact_ids) != set(source_call.depends_on_artifact_ids):
            raise ValueError("RQ1 producer prompt source-artifact lineage mismatch")
        source_segments = [
            item["content"]
            for item in producer_prompt.messages
            if text_sha256(item["content"]) == row.source_text_sha256
        ]
        if len(source_segments) != 1:
            raise ValueError("RQ1 producer prompt omits the exact source result segment")
        if any(
            artifacts[artifact_id].content not in source_segments[0]
            for artifact_id in source_call.depends_on_artifact_ids
        ):
            raise ValueError("RQ1 producer source segment omits a declared artifact")
    if row.producer_call_id is not None:
        producer_call = calls.get(row.producer_call_id)
        if producer_call is None:
            raise ValueError("RQ1 producer_call_id references a missing model call")
        if producer_call.prompt_id != row.producer_prompt_id:
            raise ValueError("RQ1 producer model call prompt mismatch")
        if producer_call.model != row.producer_model:
            raise ValueError("RQ1 producer model mismatch")
        producer_contract = row.metadata.get("producer_contract")
        if not isinstance(producer_contract, dict):
            raise ValueError("RQ1 model producer contract is missing")
        if producer_call.provider != producer_contract["provider_id"]:
            raise ValueError("RQ1 producer provider mismatch")
        if producer_call.metadata.get("model_version") != producer_contract[
            "model_version"
        ]:
            raise ValueError("RQ1 producer model version mismatch")
        if producer_call.sampling.get("temperature") != producer_contract[
            "temperature"
        ]:
            raise ValueError("RQ1 producer temperature mismatch")
        if producer_call.metadata.get("output_token_cap") != producer_contract[
            "output_token_cap"
        ]:
            raise ValueError("RQ1 producer output cap mismatch")
        if producer_call.metadata.get("stopping_rule") != producer_contract[
            "stopping_rule"
        ]:
            raise ValueError("RQ1 producer stopping rule mismatch")
        if producer_call.status != CallStatus.SUCCESS:
            raise ValueError("RQ1 producer model call must be successful")
        if producer_call.response_sha256 != row.target_text_sha256:
            raise ValueError("RQ1 producer model response hash mismatch")
        if producer_call.output_tokens != row.target_token_count:
            raise ValueError("RQ1 producer output token count mismatch")
        if row.metadata.get("calibration_only") is True and producer_call.input_tokens is None:
            raise ValueError("offline RQ1 producer call requires observed input tokens")
        if row.metadata.get("calibration_only") is True and producer_call.metadata.get(
            "api_called"
        ) is not False:
            raise ValueError("offline RQ1 calibration producer call must deny API use")

    for annotation in bundle.annotations:
        if annotation.taxonomy != RQ1_FACT_ANNOTATION_TAXONOMY:
            continue
        fact = RQ1FactAnnotation.from_record(annotation)
        if fact.transformation_id != row.transformation_id:
            raise ValueError("RQ1 fact annotation transformation mismatch")
        if fact.fact_id not in row.required_fact_ids:
            raise ValueError("RQ1 fact annotation references a non-required fact")
        if fact.stage == RQ1FactAnnotationStage.TRANSFORMATION_OUTPUT:
            if fact.target_event_ids != (row.output_event_id,):
                raise ValueError("RQ1 transformation fact annotation target mismatch")
            if any(span not in message.content for span in fact.evidence_spans):
                raise ValueError("RQ1 transformation evidence span is absent from output")
        else:
            for event_id in fact.target_event_ids:
                event = events[event_id]
                if event.details.get("transformation_id") != row.transformation_id:
                    raise ValueError("RQ1 downstream fact event lineage mismatch")
                if event.details.get("consumed_prompt_id") not in row.downstream_prompt_ids:
                    raise ValueError("RQ1 downstream fact prompt lineage mismatch")
                observations = event.details.get("fact_observation_statuses", {})
                if observations.get(fact.fact_id) != fact.observation_status.value:
                    raise ValueError("RQ1 downstream observation status mismatch")
                prompt_id = str(event.details.get("consumed_prompt_id"))
                if event.details.get("downstream_output_sha256") != (
                    downstream_response_by_prompt[prompt_id]
                ):
                    raise ValueError("RQ1 downstream response/event hash mismatch")
                output_text = event.details.get("downstream_output_text")
                if not isinstance(output_text, str) or text_sha256(output_text) != (
                    event.details.get("downstream_output_sha256")
                ):
                    raise ValueError("RQ1 downstream output text/hash mismatch")
                if any(span not in output_text for span in fact.evidence_spans):
                    raise ValueError(
                        "RQ1 downstream evidence span is absent from output"
                    )
    expected_evaluator = (
        f"{downstream_contract['scorer_id']}@{downstream_contract['scorer_version']}"
    )
    if bundle.outcome.evaluator != expected_evaluator:
        raise ValueError("RQ1 outcome scorer contract mismatch")


def validate_rq1_transformation_bundle(bundle: TraceBundle) -> None:
    """Validate generic trace invariants plus all nested RQ1 cross-references."""

    bundle.validate()


@dataclass(frozen=True, slots=True)
class RQ1OfflineCalibration:
    fixture_id: str
    bundles: tuple[TraceBundle, ...]
    transformations: tuple[RQ1TransformationRecord, ...]
    transformation_metrics: Any
    downstream_metrics: Any

    def to_dict(self, *, include_traces: bool = False) -> dict[str, Any]:
        result = {
            "fixture_id": self.fixture_id,
            "suite_kind": "derived",
            "analysis_eligible": False,
            "api_called": False,
            "arms": [row.arm.value for row in self.transformations],
            "transformation_metrics": self.transformation_metrics.to_dict(),
            "downstream_metrics": self.downstream_metrics.to_dict(),
        }
        if include_traces:
            result["traces"] = [
                [record.to_dict() for record in bundle.records()]
                for bundle in self.bundles
            ]
        return result


def _transformation_annotation(row: RQ1TransformationRecord) -> AnnotationRecord:
    record = AnnotationRecord(
        annotation_id=f"ann-transform-{row.arm.value}",
        run_id=row.run_id,
        taxonomy=RQ1_TRANSFORMATION_TAXONOMY,
        taxonomy_version=RQ1_TRANSFORMATION_TAXONOMY_VERSION,
        labels=(f"arm:{row.arm.value}", f"method:{row.method.value}"),
        annotator="offline-fixture-contract",
        identifiability="synthetic_ground_truth",
        target_event_ids=(row.output_event_id,),
        evidence_event_ids=row.parent_event_ids,
        metadata={"transformation": row.to_dict()},
    )
    record.validate()
    return record


def build_offline_rq1_calibration_fixture() -> tuple[TraceBundle, ...]:
    """Build one deterministic synthetic fixture in all three experimental arms."""

    facts = (
        ("fact-region", "Deployment region is eu-west-1."),
        ("fact-retention", "Retention period is 14 days."),
        ("fact-backup", "Never delete backups before validation."),
        ("fact-schema", "Required schema version is 7."),
        ("fact-owner", "Owning team is platform."),
        ("fact-port", "Service port is 8443."),
    )
    fact_ids = tuple(item[0] for item in facts)
    distractors = (
        ("distractor-request", "Synthetic request identifier is SYN-42."),
        ("distractor-shard", "Diagnostic log shard is alpha."),
        ("distractor-color", "Debug display color is amber."),
        ("distractor-retry", "Fixture retry counter is 2."),
        ("distractor-timezone", "Annotation timezone note is UTC."),
        ("distractor-checksum", "Checksum label is DEMO."),
    )
    distractor_ids = tuple(item[0] for item in distractors)
    source_text = (
        "Synthetic tool result. Deployment region is eu-west-1. Retention period is "
        "14 days. Never delete backups before validation. Required schema version is "
        "7. Owning team is platform. Service port is 8443. Synthetic request identifier "
        "is SYN-42. Diagnostic log shard is alpha. Debug display color is amber. Fixture "
        "retry counter is 2. Annotation timezone note is UTC. Checksum label is DEMO."
    )
    reference_text = (
        "Use eu-west-1; retain for 14 days; never delete backups before validation; "
        "require schema version 7; owner platform; port 8443."
    )
    summary_text = (
        "Use the EU region with 14-day retention. Delete backups before checking. "
        "Owner: platform. Port: 8443."
    )
    target_by_arm = {
        RQ1TransformationArm.RAW_PASSTHROUGH: source_text,
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: reference_text,
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: summary_text,
    }
    shared_char_budget = max(len(reference_text), len(summary_text))
    shared_token_budget = max(
        rq1_token_count(reference_text), rq1_token_count(summary_text)
    )
    transform_statuses = {
        RQ1TransformationArm.RAW_PASSTHROUGH: {
            fact_id: (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, text)
            for fact_id, text in facts
        },
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: {
            "fact-region": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "eu-west-1"),
            "fact-retention": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "14 days"),
            "fact-backup": (
                RQ1FactAnnotationStatus.PRESERVED_CORRECTLY,
                "never delete backups before validation",
            ),
            "fact-schema": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "schema version 7"),
            "fact-owner": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "owner platform"),
            "fact-port": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "port 8443"),
        },
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: {
            "fact-region": (RQ1FactAnnotationStatus.PARTIAL, "EU region"),
            "fact-retention": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "14-day retention"),
            "fact-backup": (
                RQ1FactAnnotationStatus.DISTORTED_OR_CONTRADICTED,
                "Delete backups before checking",
            ),
            "fact-schema": (RQ1FactAnnotationStatus.OMITTED, ""),
            "fact-owner": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "Owner: platform"),
            "fact-port": (RQ1FactAnnotationStatus.PRESERVED_CORRECTLY, "Port: 8443"),
        },
    }
    downstream_text_by_arm = {
        RQ1TransformationArm.RAW_PASSTHROUGH: "Confirmed downstream: " + source_text,
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: (
            "Confirmed downstream: " + reference_text
        ),
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: (
            "Apply 14-day retention in the EU. Delete backups before validation. "
            "The platform team handles the change; schema details are absent."
        ),
    }
    downstream_prompt_template = "Apply this synthetic tool result:\n{transformed_text}"
    task_payload = {
        "task_id": "apply-synthetic-deployment-policy-v1",
        "question_template": downstream_prompt_template,
        "required_facts": [
            {"fact_id": fact_id, "ground_truth": text} for fact_id, text in facts
        ],
        "distractors": [
            {"distractor_id": distractor_id, "text": text}
            for distractor_id, text in distractors
        ],
    }
    task_payload_hash = rq1_downstream_contract_sha256(task_payload)
    downstream_contract = {
        "task_id": "apply-synthetic-deployment-policy-v1",
        "task_payload_sha256": task_payload_hash,
        "prompt_template": downstream_prompt_template,
        "prompt_template_sha256": text_sha256(downstream_prompt_template),
        "provider_id": "offline_fixture",
        "model": "offline-fixture/downstream-replay",
        "model_version": "v1",
        "context_token_cap": 512,
        "output_token_cap": 128,
        "temperature": 0.0,
        "stopping_rule": "synthetic_response_end_v1",
        "scorer_id": "rq1-required-fact-scorer",
        "scorer_version": "1.0.0",
    }
    downstream_contract_hash = rq1_downstream_contract_sha256(downstream_contract)
    bundles: list[TraceBundle] = []
    for arm in RQ1TransformationArm:
        suffix = {
            RQ1TransformationArm.RAW_PASSTHROUGH: "c0",
            RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: "c1",
            RQ1TransformationArm.ABSTRACTIVE_SUMMARY: "t",
        }[arm]
        run_id = f"rq1-offline-{suffix}"
        transformation_id = f"transform-{suffix}"
        tool_call_id = f"tool-source-{suffix}"
        output_event_id = f"event-transform-{suffix}"
        message_id = f"message-transform-{suffix}"
        downstream_prompt_id = f"prompt-downstream-{suffix}"
        producer_prompt_id = (
            None
            if arm == RQ1TransformationArm.RAW_PASSTHROUGH
            else f"prompt-producer-{suffix}"
        )
        producer_call_id = (
            f"call-producer-{suffix}"
            if arm == RQ1TransformationArm.ABSTRACTIVE_SUMMARY
            else None
        )
        producer_model = "offline-fixture/model-replay-v1" if producer_call_id else None
        target_text = target_by_arm[arm]
        producer_messages = (
            {
                "role": "system",
                "content": (
                    "Synthetic offline transformation fixture. Transform the next "
                    "tool-result message under the registered arm and budget."
                ),
            },
            {"role": "user", "content": source_text},
        )
        producer_hash = prompt_sha256(producer_messages) if producer_prompt_id else None
        possession_ids = tuple(f"event-possessed-{suffix}-{fact_id}" for fact_id in fact_ids)
        row = RQ1TransformationRecord(
            transformation_id=transformation_id,
            run_id=run_id,
            fixture_id=RQ1_OFFLINE_FIXTURE_ID,
            repeat_id="repeat-001",
            block_id="block-001",
            benchmark_id=RQ1_OFFLINE_BENCHMARK_ID,
            suite_kind="derived",
            protocol_kind=RQ1_OFFLINE_PROTOCOL_KIND,
            arm=arm,
            method={
                RQ1TransformationArm.RAW_PASSTHROUGH: RQ1TransformationMethod.IDENTITY,
                RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: (
                    RQ1TransformationMethod.REFERENCE_SUMMARY
                ),
                RQ1TransformationArm.ABSTRACTIVE_SUMMARY: (
                    RQ1TransformationMethod.ABSTRACTIVE_SUMMARY
                ),
            }[arm],
            source_text_sha256=text_sha256(source_text),
            target_text_sha256=text_sha256(target_text),
            source_char_count=len(source_text),
            target_char_count=len(target_text),
            source_token_count=rq1_token_count(source_text),
            target_token_count=rq1_token_count(target_text),
            token_count_method=RQ1_TOKEN_COUNT_METHOD,
            token_count_version=RQ1_TOKEN_COUNT_VERSION,
            char_budget=(
                len(source_text)
                if arm == RQ1TransformationArm.RAW_PASSTHROUGH
                else shared_char_budget
            ),
            token_budget=(
                rq1_token_count(source_text)
                if arm == RQ1TransformationArm.RAW_PASSTHROUGH
                else shared_token_budget
            ),
            required_fact_ids=fact_ids,
            source_tool_call_id=tool_call_id,
            parent_event_ids=possession_ids,
            output_event_id=output_event_id,
            target_message_id=message_id,
            downstream_prompt_ids=(downstream_prompt_id,),
            downstream_contract_sha256=downstream_contract_hash,
            producer_kind={
                RQ1TransformationArm.RAW_PASSTHROUGH: RQ1TransformationProducerKind.DETERMINISTIC,
                RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: (
                    RQ1TransformationProducerKind.HUMAN_REFERENCE
                ),
                RQ1TransformationArm.ABSTRACTIVE_SUMMARY: RQ1TransformationProducerKind.MODEL,
            }[arm],
            producer_id={
                RQ1TransformationArm.RAW_PASSTHROUGH: "identity-v1",
                RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: "registered-human-reference-v1",
                RQ1TransformationArm.ABSTRACTIVE_SUMMARY: "offline-model-replay-v1",
            }[arm],
            source_native_benchmark_id=None,
            producer_model=producer_model,
            producer_prompt_id=producer_prompt_id,
            producer_prompt_sha256=producer_hash,
            producer_call_id=producer_call_id,
            metadata={
                "native_benchmark_claimed": False,
                "calibration_only": True,
                "synthetic_fixture": True,
                "api_called": False,
                "downstream_task_id": downstream_contract["task_id"],
                "downstream_contract": dict(downstream_contract),
                "distractor_ids": list(distractor_ids),
                "distractor_count": len(distractor_ids),
                **(
                    {
                        "producer_contract": {
                            "provider_id": "offline_fixture",
                            "model": producer_model,
                            "model_version": "v1",
                            "prompt_sha256": producer_hash,
                            "temperature": 0.0,
                            "output_token_cap": shared_token_budget,
                            "stopping_rule": "synthetic_response_end_v1",
                        }
                    }
                    if arm == RQ1TransformationArm.ABSTRACTIVE_SUMMARY
                    else {}
                ),
            },
        )
        row.validate()

        manifest = RunManifest(
            run_id=run_id,
            task_id=str(downstream_contract["task_id"]),
            condition_id=arm.value,
            benchmark=RQ1_OFFLINE_BENCHMARK_ID,
            seed=1,
            started_at="2026-08-14T00:00:00Z",
            agents=(
                AgentSpec("source", "tool-result transformer", "offline", "fixture"),
                AgentSpec("consumer", "downstream consumer", "offline", "fixture"),
            ),
            topology=(EdgeSpec("source-to-consumer", "source", "consumer"),),
            protocol_kind=RQ1_OFFLINE_PROTOCOL_KIND,
            suite_kind="derived",
            purpose="offline_calibration",
            pair_id="rq1-offline-pair",
            cluster_id="rq1-offline-fixture",
            analysis_eligible=False,
            native_task_hash=task_payload_hash,
            config={
                "rq1_fixture_id": RQ1_OFFLINE_FIXTURE_ID,
                "rq1_repeat_id": "repeat-001",
                "rq1_block_id": "block-001",
                "native_benchmark_claimed": False,
                "source_native_benchmark_id": None,
                "rq1_downstream_contract_sha256": downstream_contract_hash,
                "rq1_downstream_task_id": downstream_contract["task_id"],
                "rq1_task_payload_sha256": task_payload_hash,
                "rq1_distractor_ids": list(distractor_ids),
                "rq1_distractor_count": len(distractor_ids),
                "offline_only": True,
                "api_called": False,
            },
        )
        artifacts = tuple(
            ArtifactRecord(
                artifact_id=fact_id,
                run_id=run_id,
                source_agent_id="source",
                created_step=0,
                truth_status=TruthStatus.TRUE,
                content=text,
                origin=ArtifactOrigin.ENVIRONMENT,
                kind=ArtifactKind.TOOL_OUTPUT,
                required_to_surface=fact_id in fact_ids,
                metadata={
                    "synthetic": True,
                    "rq1_role": (
                        "required_fact" if fact_id in fact_ids else "distractor"
                    ),
                },
            )
            for fact_id, text in (*facts, *distractors)
        )
        assignments = tuple(
            InformationAssignmentRecord(
                assignment_id=f"assignment-{suffix}-{fact_id}",
                run_id=run_id,
                artifact_id=fact_id,
                holder_agent_ids=("source",),
                authorized_agent_ids=("source", "consumer"),
                visibility_scope="source_tool_result",
                required_for_solution=fact_id in fact_ids,
                metadata={"fixture_id": RQ1_OFFLINE_FIXTURE_ID},
            )
            for fact_id in (*fact_ids, *distractor_ids)
        )
        tool_call = ToolCallRecord(
            tool_call_id=tool_call_id,
            run_id=run_id,
            agent_id="source",
            step=1,
            tool_name="offline.synthetic_fixture",
            status=ToolCallStatus.SUCCESS,
            authorized=True,
            result_sha256=row.source_text_sha256,
            depends_on_artifact_ids=(*fact_ids, *distractor_ids),
            metadata={
                "source_char_count": row.source_char_count,
                "source_token_count": row.source_token_count,
                "token_count_method": row.token_count_method,
                "token_count_version": row.token_count_version,
                "api_called": False,
            },
        )
        prompts: list[PromptRecord] = []
        calls: list[ModelCallRecord] = []
        if producer_prompt_id:
            prompts.append(
                PromptRecord(
                    prompt_id=producer_prompt_id,
                    run_id=run_id,
                    agent_id="source",
                    step=2,
                    messages=producer_messages,
                    artifact_ids=(*fact_ids, *distractor_ids),
                    content_sha256=producer_hash or "",
                    call_id=producer_call_id,
                    metadata={
                        "transformation_id": transformation_id,
                        "purpose": "rq1_transformation_producer",
                        "source_tool_call_id": tool_call_id,
                        "source_text_sha256": row.source_text_sha256,
                        "source_segment_sha256": row.source_text_sha256,
                        "actual_full_provider_request_available": True,
                        "synthetic": True,
                    },
                )
            )
        if producer_call_id:
            calls.append(
                ModelCallRecord(
                    call_id=producer_call_id,
                    run_id=run_id,
                    agent_id="source",
                    prompt_id=producer_prompt_id or "",
                    step=2,
                    status=CallStatus.SUCCESS,
                    provider="offline_fixture",
                    model=producer_model or "",
                    response_sha256=row.target_text_sha256,
                    input_tokens=sum(
                        rq1_token_count(item["content"])
                        for item in producer_messages
                    ),
                    output_tokens=row.target_token_count,
                    sampling={"temperature": 0.0},
                    metadata={
                        "api_called": False,
                        "offline_replay": True,
                        "model_version": "v1",
                        "output_token_cap": shared_token_budget,
                        "stopping_rule": "synthetic_response_end_v1",
                    },
                )
            )
        successful_fact_ids = tuple(
            fact_id
            for fact_id, (status, _) in transform_statuses[arm].items()
            if status == RQ1FactAnnotationStatus.PRESERVED_CORRECTLY
        )
        transmitted_artifact_ids = (
            (*successful_fact_ids, *distractor_ids)
            if arm == RQ1TransformationArm.RAW_PASSTHROUGH
            else successful_fact_ids
        )
        message = MessageRecord(
            message_id=message_id,
            run_id=run_id,
            source_agent_id="source",
            target_agent_id="consumer",
            sent_step=4,
            content=target_text,
            content_sha256=row.target_text_sha256,
            expected_artifact_ids=fact_ids,
            artifact_ids=transmitted_artifact_ids,
            delivered=True,
            delivered_step=5,
            included_prompt_id=downstream_prompt_id,
            local_sequence=1,
            metadata={
                "transformation_id": transformation_id,
                "source_text_sha256": row.source_text_sha256,
            },
        )
        downstream_messages = (
            {
                "role": "user",
                "content": downstream_prompt_template.format(
                    transformed_text=target_text
                ),
            },
        )
        downstream_call_id = f"call-downstream-{suffix}"
        prompts.append(
            PromptRecord(
                prompt_id=downstream_prompt_id,
                run_id=run_id,
                agent_id="consumer",
                step=6,
                messages=downstream_messages,
                artifact_ids=transmitted_artifact_ids,
                content_sha256=prompt_sha256(downstream_messages),
                call_id=downstream_call_id,
                metadata={
                    "actual_full_provider_request_available": True,
                    "transformation_id": transformation_id,
                    "included_message_ids": [message_id],
                    "included_message_sha256": row.target_text_sha256,
                    "prompt_template_sha256": downstream_contract[
                        "prompt_template_sha256"
                    ],
                    "prompt_template": downstream_contract["prompt_template"],
                    "synthetic": True,
                },
            )
        )
        downstream_text = downstream_text_by_arm[arm]
        calls.append(
            ModelCallRecord(
                call_id=downstream_call_id,
                run_id=run_id,
                agent_id="consumer",
                prompt_id=downstream_prompt_id,
                step=6,
                status=CallStatus.SUCCESS,
                provider="offline_fixture",
                model=str(downstream_contract["model"]),
                response_sha256=text_sha256(downstream_text),
                input_tokens=rq1_token_count(downstream_messages[0]["content"]),
                output_tokens=rq1_token_count(downstream_text),
                sampling={"temperature": downstream_contract["temperature"]},
                metadata={
                    "api_called": False,
                    "offline_replay": True,
                    "model_version": downstream_contract["model_version"],
                    "context_token_cap": downstream_contract["context_token_cap"],
                    "output_token_cap": downstream_contract["output_token_cap"],
                    "stopping_rule": downstream_contract["stopping_rule"],
                    "scorer_id": downstream_contract["scorer_id"],
                    "scorer_version": downstream_contract["scorer_version"],
                },
            )
        )

        events: list[LifecycleEvent] = []
        for fact_id, possession_id in zip(fact_ids, possession_ids, strict=True):
            events.append(
                LifecycleEvent(
                    event_id=possession_id,
                    run_id=run_id,
                    event_type=EventType.ARTIFACT_POSSESSED,
                    step=1,
                    timestamp="2026-08-14T00:00:01Z",
                    agent_id="source",
                    artifact_id=fact_id,
                    details={"observation": "synthetic_fixture_assignment"},
                )
            )
        for distractor_id in distractor_ids:
            events.append(
                LifecycleEvent(
                    event_id=f"event-possessed-{suffix}-{distractor_id}",
                    run_id=run_id,
                    event_type=EventType.ARTIFACT_POSSESSED,
                    step=1,
                    timestamp="2026-08-14T00:00:01Z",
                    agent_id="source",
                    artifact_id=distractor_id,
                    details={"observation": "synthetic_fixture_distractor"},
                )
            )
        events.append(
            LifecycleEvent(
                event_id=output_event_id,
                run_id=run_id,
                event_type=EventType.ACTION_TAKEN,
                step=3,
                timestamp="2026-08-14T00:00:03Z",
                agent_id="source",
                parent_event_ids=possession_ids,
                details={
                    "action_id": f"rq1-transform-{suffix}",
                    "depends_on_artifact_ids": [*fact_ids, *distractor_ids],
                    "transformation_id": transformation_id,
                    "source_tool_call_id": tool_call_id,
                    "source_text_sha256": row.source_text_sha256,
                    "target_text_sha256": row.target_text_sha256,
                    "target_message_id": message_id,
                    "arm": arm.value,
                    "method": row.method.value,
                },
            )
        )
        delivered_event_by_fact: dict[str, str] = {}
        sent_events: list[LifecycleEvent] = []
        delivered_events: list[LifecycleEvent] = []
        for fact_id in transmitted_artifact_ids:
            sent_id = f"event-sent-{suffix}-{fact_id}"
            delivered_id = f"event-delivered-{suffix}-{fact_id}"
            delivered_event_by_fact[fact_id] = delivered_id
            sent_events.append(
                LifecycleEvent(
                    event_id=sent_id,
                    run_id=run_id,
                    event_type=EventType.MESSAGE_SENT,
                    step=4,
                    timestamp="2026-08-14T00:00:04Z",
                    artifact_id=fact_id,
                    source_agent_id="source",
                    target_agent_id="consumer",
                    edge_id="source-to-consumer",
                    parent_event_ids=(output_event_id,),
                    details={
                        "message_id": message_id,
                        "artifact_present": True,
                    },
                )
            )
            delivered_events.append(
                LifecycleEvent(
                    event_id=delivered_id,
                    run_id=run_id,
                    event_type=EventType.MESSAGE_DELIVERED,
                    step=5,
                    timestamp="2026-08-14T00:00:05Z",
                    artifact_id=fact_id,
                    source_agent_id="source",
                    target_agent_id="consumer",
                    edge_id="source-to-consumer",
                    parent_event_ids=(sent_id,),
                    details={"message_id": message_id},
                )
            )
        events.extend(sent_events)
        events.extend(delivered_events)
        exposure_event_ids: list[str] = []
        for fact_id in transmitted_artifact_ids:
            exposure_event_id = f"event-exposed-{suffix}-{fact_id}"
            exposure_event_ids.append(exposure_event_id)
            events.append(
                LifecycleEvent(
                    event_id=exposure_event_id,
                    run_id=run_id,
                    event_type=EventType.ARTIFACT_EXPOSED,
                    step=6,
                    timestamp="2026-08-14T00:00:06Z",
                    artifact_id=fact_id,
                    target_agent_id="consumer",
                    prompt_id=downstream_prompt_id,
                    parent_event_ids=(delivered_event_by_fact[fact_id],),
                    details={
                        "exposure_evidence": "exact_provider_request",
                        "parent_message_ids": [message_id],
                    },
                )
            )

        downstream_statuses = {
            fact_id: (
                RQ1FactAnnotationStatus.CORRECTLY_REFLECTED,
                RQ1FactObservationStatus.COMPLETE_VALID,
                transform_statuses[arm][fact_id][1],
            )
            for fact_id in fact_ids
        }
        if arm == RQ1TransformationArm.ABSTRACTIVE_SUMMARY:
            downstream_statuses = {
                "fact-region": (
                    RQ1FactAnnotationStatus.MENTIONED_ONLY,
                    RQ1FactObservationStatus.COMPLETE_VALID,
                    "EU",
                ),
                "fact-retention": (
                    RQ1FactAnnotationStatus.CORRECTLY_REFLECTED,
                    RQ1FactObservationStatus.COMPLETE_VALID,
                    "14-day retention",
                ),
                "fact-backup": (
                    RQ1FactAnnotationStatus.INCORRECTLY_REFLECTED,
                    RQ1FactObservationStatus.COMPLETE_VALID,
                    "Delete backups before validation",
                ),
                "fact-schema": (
                    RQ1FactAnnotationStatus.ABSENT,
                    RQ1FactObservationStatus.COMPLETE_VALID,
                    "",
                ),
                "fact-owner": (
                    RQ1FactAnnotationStatus.UNKNOWN,
                    RQ1FactObservationStatus.COMPLETE_VALID,
                    "",
                ),
                "fact-port": (
                    RQ1FactAnnotationStatus.ABSENT,
                    RQ1FactObservationStatus.COMPLETE_VALID,
                    "",
                ),
            }
        downstream_event_id = f"event-downstream-{suffix}"
        events.append(
            LifecycleEvent(
                event_id=downstream_event_id,
                run_id=run_id,
                event_type=EventType.ACTION_TAKEN,
                step=7,
                timestamp="2026-08-14T00:00:07Z",
                agent_id="consumer",
                parent_event_ids=tuple(exposure_event_ids),
                details={
                    "action_id": f"rq1-downstream-assessment-{suffix}",
                    "depends_on_artifact_ids": list(transmitted_artifact_ids),
                    "transformation_id": transformation_id,
                    "consumed_prompt_id": downstream_prompt_id,
                    "fact_observation_statuses": {
                        fact_id: downstream_statuses[fact_id][1].value
                        for fact_id in fact_ids
                    },
                    "downstream_output_sha256": text_sha256(downstream_text),
                    "downstream_output_text": downstream_text,
                },
            )
        )
        events.append(
            LifecycleEvent(
                event_id=f"event-final-{suffix}",
                run_id=run_id,
                event_type=EventType.RUN_FINALIZED,
                step=8,
                timestamp="2026-08-14T00:00:08Z",
                parent_event_ids=(downstream_event_id,),
                details={"status": "offline_calibration_complete"},
            )
        )

        annotations: list[AnnotationRecord] = [_transformation_annotation(row)]
        for fact_id in fact_ids:
            transform_status, transform_span = transform_statuses[arm][fact_id]
            annotations.append(
                RQ1FactAnnotation(
                    annotation_id=f"ann-transform-fact-{suffix}-{fact_id}",
                    run_id=run_id,
                    transformation_id=transformation_id,
                    fact_id=fact_id,
                    stage=RQ1FactAnnotationStage.TRANSFORMATION_OUTPUT,
                    status=transform_status,
                    observation_status=RQ1FactObservationStatus.COMPLETE_VALID,
                    target_event_ids=(output_event_id,),
                    annotator="offline-fixture-ground-truth",
                    evidence_spans=((transform_span,) if transform_span else ()),
                    metadata={"synthetic": True},
                ).to_record()
            )
            downstream_status, observation_status, downstream_span = downstream_statuses[fact_id]
            annotations.append(
                RQ1FactAnnotation(
                    annotation_id=f"ann-downstream-fact-{suffix}-{fact_id}",
                    run_id=run_id,
                    transformation_id=transformation_id,
                    fact_id=fact_id,
                    stage=RQ1FactAnnotationStage.DOWNSTREAM_OUTPUT,
                    status=downstream_status,
                    observation_status=observation_status,
                    target_event_ids=(downstream_event_id,),
                    annotator="offline-fixture-ground-truth",
                    evidence_spans=((downstream_span,) if downstream_span else ()),
                    metadata={"synthetic": True},
                ).to_record()
            )

        bundle = TraceBundle(
            manifest=manifest,
            artifacts=artifacts,
            prompts=tuple(prompts),
            events=tuple(events),
            outcome=RunOutcome(
                run_id=run_id,
                success=None,
                score=None,
                final_step=8,
                evaluator=(
                    f"{downstream_contract['scorer_id']}@"
                    f"{downstream_contract['scorer_version']}"
                ),
                outcome_kind=OutcomeKind.DIAGNOSTIC_ONLY,
                run_status=RunStatus.COMPLETED,
                details={
                    "synthetic_fixture": True,
                    "analysis_eligible": False,
                    "api_called": False,
                },
            ),
            information_assignments=assignments,
            messages=(message,),
            model_calls=tuple(calls),
            tool_calls=(tool_call,),
            annotations=tuple(annotations),
        )
        bundle.validate()
        bundles.append(bundle)

    validate_rq1_arm_set(
        row for bundle in bundles for row in extract_rq1_transformations(bundle)
    )
    return tuple(bundles)


def run_offline_rq1_calibration() -> RQ1OfflineCalibration:
    """Build, validate, and score the fully offline 1-fixture x 3-arm suite."""

    from .metrics import compute_rq1_transformation_metrics

    bundles = build_offline_rq1_calibration_fixture()
    transformations = tuple(
        row for bundle in bundles for row in extract_rq1_transformations(bundle)
    )
    validate_rq1_arm_set(transformations)
    annotations = tuple(
        annotation for bundle in bundles for annotation in bundle.annotations
    )
    return RQ1OfflineCalibration(
        fixture_id=RQ1_OFFLINE_FIXTURE_ID,
        bundles=bundles,
        transformations=transformations,
        transformation_metrics=compute_rq1_transformation_metrics(
            transformations,
            annotations,
            stage=RQ1FactAnnotationStage.TRANSFORMATION_OUTPUT,
        ),
        downstream_metrics=compute_rq1_transformation_metrics(
            transformations,
            annotations,
            stage=RQ1FactAnnotationStage.DOWNSTREAM_OUTPUT,
        ),
    )
