"""Real-provider RQ1 three-arm transformation runner (engineering calibration).

The offline contract in :mod:`mas_error_lifecycle.rq1` builds a synthetic,
``api_called=False`` calibration trace.  This module builds the *real* trace:
one run per arm (C0 raw passthrough, C1 length-matched reference, T abstractive
summary), each followed by a real downstream answer call.  Every bundle is
``api_called=True``, ``purpose="engineering_smoke"`` and
``analysis_eligible=False``; it never emits semantic fact annotations because
those are human/judge work layered on after the run.

Two deliberate, documented engineering compromises apply to this calibration
runner only:

* ``message.artifact_ids`` records *literal* presence (a required fact whose
  registered ground-truth text appears verbatim in the transformed text), not
  semantic preservation.  Semantic preservation remains for the human/judge
  annotation pass, exactly as the RTD adapter distinguishes literal tracer
  survival from belief adoption.
* The v0.2 validator defines ``target_token_count`` as the whitespace-split
  proxy (``rq1_token_count``) and requires the producer model call's
  ``output_tokens`` to equal it.  The real provider reports model tokens, so
  the producer call stores the whitespace count in ``output_tokens`` and
  preserves the actual provider completion tokens in
  ``metadata["provider_completion_tokens"]``.  Input tokens and cost are stored
  verbatim.  This is a known v0.2 calibration limitation, not a billing or
  usage claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from .rq1 import (
    RQ1_TOKEN_COUNT_METHOD,
    RQ1_TOKEN_COUNT_VERSION,
    _transformation_annotation,
    rq1_downstream_contract_sha256,
    rq1_token_count,
    validate_rq1_arm_set,
)
from .schema import (
    AgentSpec,
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

RQ1_REAL_BENCHMARK_ID = "rq1-derived-summary-calibration-v1"
RQ1_REAL_PROTOCOL_KIND = "rq1_real_transformation_calibration"
RQ1_REAL_PROVIDER_ID = "openai-compatible"
RQ1_REAL_SCORER_ID = "rq1-required-fact-scorer"
RQ1_REAL_SCORER_VERSION = "1.0.0"
RQ1_REAL_STOPPING_RULE = "openai-compatible-chat-single-response-v1"
RQ1_REAL_PURPOSE = "engineering_smoke"


@dataclass(frozen=True, slots=True)
class RQ1FixtureManifest:
    """Immutable per-fixture input that a swappable manifest file provides.

    The source text must be strictly longer (chars and whitespace tokens) than
    both the reference text and any in-budget summary, so the three-arm
    ``validate_rq1_arm_set`` invariant holds.
    """

    fixture_id: str
    task_id: str
    source_text: str
    required_facts: tuple[tuple[str, str], ...]
    distractors: tuple[tuple[str, str], ...]
    reference_text: str
    downstream_prompt_template: str
    char_budget: int
    token_budget: int

    def __post_init__(self) -> None:
        self.validate()

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(fact_id for fact_id, _ in self.required_facts)

    @property
    def distractor_ids(self) -> tuple[str, ...]:
        return tuple(item_id for item_id, _ in self.distractors)

    @property
    def fact_texts(self) -> dict[str, str]:
        return dict(self.required_facts)

    def validate(self) -> None:
        if not self.fixture_id.strip() or not self.task_id.strip():
            raise ValueError("RQ1 fixture_id and task_id must be non-empty")
        if not self.source_text:
            raise ValueError("RQ1 source_text must be non-empty")
        if not self.reference_text:
            raise ValueError("RQ1 reference_text must be non-empty")
        if len(self.required_facts) < 1 or len(self.distractors) < 1:
            raise ValueError("RQ1 fixture requires facts and distractors")
        fact_ids = self.fact_ids
        if len(set(fact_ids)) != len(fact_ids):
            raise ValueError("RQ1 required fact IDs must be unique")
        if len(set(self.distractor_ids)) != len(self.distractor_ids):
            raise ValueError("RQ1 distractor IDs must be unique")
        if set(fact_ids) & set(self.distractor_ids):
            raise ValueError("RQ1 fact and distractor IDs must be disjoint")
        if "{transformed_text}" not in self.downstream_prompt_template:
            raise ValueError(
                "downstream_prompt_template must contain {transformed_text}"
            )
        try:
            self.downstream_prompt_template.format(transformed_text="probe")
        except (IndexError, KeyError, ValueError) as exc:
            raise ValueError("downstream_prompt_template is invalid") from exc
        if self.char_budget < 1 or self.token_budget < 1:
            raise ValueError("RQ1 char_budget and token_budget must be positive")
        if not (
            len(self.source_text) > len(self.reference_text)
            and rq1_token_count(self.source_text) > rq1_token_count(self.reference_text)
        ):
            raise ValueError("RQ1 source_text must be longer than reference_text")
        if len(self.reference_text) > self.char_budget:
            raise ValueError("RQ1 reference_text exceeds char_budget")
        if rq1_token_count(self.reference_text) > self.token_budget:
            raise ValueError("RQ1 reference_text exceeds token_budget")


@dataclass(frozen=True, slots=True)
class RealCallEvidence:
    """Provider-agnostic outcome of one real model call."""

    content: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    latency_ms: float | None = None
    raw_response_id: str | None = None

    def validate(self) -> None:
        if not self.content.strip():
            raise ValueError("real call content must be non-empty")
        if not self.provider.strip() or not self.model.strip():
            raise ValueError("real call provider and model must be non-empty")
        if (
            isinstance(self.input_tokens, bool)
            or not isinstance(self.input_tokens, int)
            or self.input_tokens < 0
        ):
            raise ValueError("real call input_tokens must be non-negative")
        if (
            isinstance(self.output_tokens, bool)
            or not isinstance(self.output_tokens, int)
            or self.output_tokens < 0
        ):
            raise ValueError("real call output_tokens must be non-negative")


CallFn = Callable[[tuple[dict[str, str], ...], int | None], RealCallEvidence]


def _arm_suffix(arm: RQ1TransformationArm) -> str:
    return {
        RQ1TransformationArm.RAW_PASSTHROUGH: "c0",
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: "c1",
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: "t",
    }[arm]


def _method_for(arm: RQ1TransformationArm) -> RQ1TransformationMethod:
    return {
        RQ1TransformationArm.RAW_PASSTHROUGH: RQ1TransformationMethod.IDENTITY,
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: (
            RQ1TransformationMethod.REFERENCE_SUMMARY
        ),
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: (
            RQ1TransformationMethod.ABSTRACTIVE_SUMMARY
        ),
    }[arm]


def _producer_kind_for(arm: RQ1TransformationArm) -> RQ1TransformationProducerKind:
    return {
        RQ1TransformationArm.RAW_PASSTHROUGH: RQ1TransformationProducerKind.DETERMINISTIC,
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: (
            RQ1TransformationProducerKind.HUMAN_REFERENCE
        ),
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: RQ1TransformationProducerKind.MODEL,
    }[arm]


def _producer_id_for(arm: RQ1TransformationArm) -> str:
    return {
        RQ1TransformationArm.RAW_PASSTHROUGH: "identity-v1",
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE: "registered-human-reference-v1",
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY: "model-summary-v1",
    }[arm]


def _literal_present_ids(
    manifest: RQ1FixtureManifest, transformed_text: str
) -> tuple[str, ...]:
    """Literal-presence proxy: fact text appearing verbatim in the output."""
    present: list[str] = []
    for fact_id, fact_text in manifest.required_facts:
        if fact_text in transformed_text:
            present.append(fact_id)
    return tuple(present)


def build_real_rq1_bundle(
    *,
    manifest: RQ1FixtureManifest,
    arm: RQ1TransformationArm,
    transformed_text: str,
    downstream_text: str,
    producer_evidence: RealCallEvidence | None,
    downstream_evidence: RealCallEvidence,
    run_id: str,
    repeat_id: str,
    block_id: str,
    started_at: str,
    model: str,
    model_version: str,
    producer_system_prompt: str,
    context_token_cap: int,
    downstream_output_token_cap: int,
    producer_output_token_cap: int,
) -> TraceBundle:
    """Build one real, validating RQ1 arm bundle without semantic annotations."""

    manifest.validate()
    downstream_evidence.validate()
    if producer_evidence is not None:
        producer_evidence.validate()
    suffix = _arm_suffix(arm)
    transformation_id = f"transform-{suffix}"
    tool_call_id = f"tool-source-{suffix}"
    output_event_id = f"event-transform-{suffix}"
    message_id = f"message-transform-{suffix}"
    downstream_prompt_id = f"prompt-downstream-{suffix}"
    downstream_call_id = f"call-downstream-{suffix}"

    fact_ids = manifest.fact_ids
    distractor_ids = manifest.distractor_ids
    source_text = manifest.source_text
    source_sha256 = text_sha256(source_text)
    target_sha256 = text_sha256(transformed_text)

    task_payload = {
        "task_id": manifest.task_id,
        "question_template": manifest.downstream_prompt_template,
        "required_facts": [
            {"fact_id": fact_id, "ground_truth": text}
            for fact_id, text in manifest.required_facts
        ],
        "distractors": [
            {"distractor_id": item_id, "text": text}
            for item_id, text in manifest.distractors
        ],
    }
    task_payload_hash = rq1_downstream_contract_sha256(task_payload)
    downstream_contract = {
        "task_id": manifest.task_id,
        "task_payload_sha256": task_payload_hash,
        "prompt_template": manifest.downstream_prompt_template,
        "prompt_template_sha256": text_sha256(manifest.downstream_prompt_template),
        "provider_id": downstream_evidence.provider,
        "model": downstream_evidence.model,
        "model_version": model_version,
        "context_token_cap": context_token_cap,
        "output_token_cap": downstream_output_token_cap,
        "temperature": 0.0,
        "stopping_rule": RQ1_REAL_STOPPING_RULE,
        "scorer_id": RQ1_REAL_SCORER_ID,
        "scorer_version": RQ1_REAL_SCORER_VERSION,
    }
    downstream_contract_hash = rq1_downstream_contract_sha256(downstream_contract)

    is_raw = arm == RQ1TransformationArm.RAW_PASSTHROUGH
    if is_raw:
        producer_prompt_id = None
        producer_call_id = None
        producer_model = None
        producer_hash = None
    else:
        producer_prompt_id = f"prompt-producer-{suffix}"
        producer_call_id = (
            f"call-producer-{suffix}"
            if arm == RQ1TransformationArm.ABSTRACTIVE_SUMMARY
            else None
        )
        producer_model = (
            producer_evidence.model
            if producer_evidence is not None
            else None
        )
        producer_messages: tuple[dict[str, str], ...] = (
            {"role": "system", "content": producer_system_prompt},
            {"role": "user", "content": source_text},
        )
        producer_hash = prompt_sha256(producer_messages)
    if arm == RQ1TransformationArm.ABSTRACTIVE_SUMMARY and producer_evidence is None:
        raise ValueError("abstractive_summary arm requires producer evidence")

    if is_raw:
        char_budget = len(source_text)
        token_budget = rq1_token_count(source_text)
    else:
        char_budget = manifest.char_budget
        token_budget = manifest.token_budget

    row = RQ1TransformationRecord(
        transformation_id=transformation_id,
        run_id=run_id,
        fixture_id=manifest.fixture_id,
        repeat_id=repeat_id,
        block_id=block_id,
        benchmark_id=RQ1_REAL_BENCHMARK_ID,
        suite_kind="derived",
        protocol_kind=RQ1_REAL_PROTOCOL_KIND,
        arm=arm,
        method=_method_for(arm),
        source_text_sha256=source_sha256,
        target_text_sha256=target_sha256,
        source_char_count=len(source_text),
        target_char_count=len(transformed_text),
        source_token_count=rq1_token_count(source_text),
        target_token_count=rq1_token_count(transformed_text),
        token_count_method=RQ1_TOKEN_COUNT_METHOD,
        token_count_version=RQ1_TOKEN_COUNT_VERSION,
        char_budget=char_budget,
        token_budget=token_budget,
        required_fact_ids=fact_ids,
        source_tool_call_id=tool_call_id,
        parent_event_ids=tuple(f"event-possessed-{suffix}-{fact_id}" for fact_id in fact_ids),
        output_event_id=output_event_id,
        target_message_id=message_id,
        downstream_prompt_ids=(downstream_prompt_id,),
        downstream_contract_sha256=downstream_contract_hash,
        producer_kind=_producer_kind_for(arm),
        producer_id=_producer_id_for(arm),
        source_native_benchmark_id=None,
        producer_model=producer_model,
        producer_prompt_id=producer_prompt_id,
        producer_prompt_sha256=producer_hash,
        producer_call_id=producer_call_id,
        metadata={
            "native_benchmark_claimed": False,
            "calibration_only": False,
            "synthetic_fixture": False,
            "api_called": True,
            "downstream_task_id": manifest.task_id,
            "downstream_contract": dict(downstream_contract),
            "distractor_ids": list(distractor_ids),
            "distractor_count": len(distractor_ids),
            **(
                {
                    "producer_contract": {
                        "provider_id": producer_evidence.provider,
                        "model": producer_evidence.model,
                        "model_version": model_version,
                        "prompt_sha256": producer_hash,
                        "temperature": 0.0,
                        "output_token_cap": producer_output_token_cap,
                        "stopping_rule": RQ1_REAL_STOPPING_RULE,
                    }
                }
                if arm == RQ1TransformationArm.ABSTRACTIVE_SUMMARY
                else {}
            ),
        },
    )
    row.validate()

    manifest_record = RunManifest(
        run_id=run_id,
        task_id=str(manifest.task_id),
        condition_id=arm.value,
        benchmark=RQ1_REAL_BENCHMARK_ID,
        seed=1,
        started_at=started_at,
        agents=(
            AgentSpec("source", "tool-result transformer", downstream_evidence.provider, downstream_evidence.model),
            AgentSpec("consumer", "downstream consumer", downstream_evidence.provider, downstream_evidence.model),
        ),
        topology=(EdgeSpec("source-to-consumer", "source", "consumer"),),
        protocol_kind=RQ1_REAL_PROTOCOL_KIND,
        suite_kind="derived",
        purpose=RQ1_REAL_PURPOSE,
        pair_id=f"{manifest.fixture_id}-pair",
        cluster_id=manifest.fixture_id,
        analysis_eligible=False,
        execution_status="ready",
        review_status="not_required",
        native_task_hash=task_payload_hash,
        config={
            "rq1_fixture_id": manifest.fixture_id,
            "rq1_repeat_id": repeat_id,
            "rq1_block_id": block_id,
            "native_benchmark_claimed": False,
            "source_native_benchmark_id": None,
            "rq1_downstream_contract_sha256": downstream_contract_hash,
            "rq1_downstream_task_id": manifest.task_id,
            "rq1_task_payload_sha256": task_payload_hash,
            "rq1_distractor_ids": list(distractor_ids),
            "rq1_distractor_count": len(distractor_ids),
            "api_called": True,
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
            required_to_surface=True,
            metadata={"rq1_role": "required_fact"},
        )
        for fact_id, text in manifest.required_facts
    ) + tuple(
        ArtifactRecord(
            artifact_id=item_id,
            run_id=run_id,
            source_agent_id="source",
            created_step=0,
            truth_status=TruthStatus.TRUE,
            content=text,
            origin=ArtifactOrigin.ENVIRONMENT,
            kind=ArtifactKind.TOOL_OUTPUT,
            required_to_surface=False,
            metadata={"rq1_role": "distractor"},
        )
        for item_id, text in manifest.distractors
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
            metadata={"fixture_id": manifest.fixture_id},
        )
        for fact_id in (*fact_ids, *distractor_ids)
    )
    tool_call = ToolCallRecord(
        tool_call_id=tool_call_id,
        run_id=run_id,
        agent_id="source",
        step=1,
        tool_name="rq1.fixture_source",
        status=ToolCallStatus.SUCCESS,
        authorized=True,
        result_sha256=source_sha256,
        depends_on_artifact_ids=(*fact_ids, *distractor_ids),
        metadata={
            "source_char_count": len(source_text),
            "source_token_count": rq1_token_count(source_text),
            "token_count_method": RQ1_TOKEN_COUNT_METHOD,
            "token_count_version": RQ1_TOKEN_COUNT_VERSION,
            "api_called": True,
        },
    )

    prompts: list[PromptRecord] = []
    calls: list[ModelCallRecord] = []
    if producer_prompt_id is not None:
        producer_messages = (
            {"role": "system", "content": producer_system_prompt},
            {"role": "user", "content": source_text},
        )
        prompts.append(
            PromptRecord(
                prompt_id=producer_prompt_id,
                run_id=run_id,
                agent_id="source",
                step=2,
                messages=producer_messages,
                artifact_ids=(*fact_ids, *distractor_ids),
                content_sha256=prompt_sha256(producer_messages),
                call_id=producer_call_id,
                metadata={
                    "transformation_id": transformation_id,
                    "purpose": "rq1_transformation_producer",
                    "source_tool_call_id": tool_call_id,
                    "source_text_sha256": source_sha256,
                    "source_segment_sha256": source_sha256,
                    "actual_full_provider_request_available": True,
                },
            )
        )
    if producer_call_id is not None and producer_evidence is not None:
        calls.append(
            ModelCallRecord(
                call_id=producer_call_id,
                run_id=run_id,
                agent_id="source",
                prompt_id=producer_prompt_id or "",
                step=2,
                status=CallStatus.SUCCESS,
                provider=producer_evidence.provider,
                model=producer_evidence.model,
                response_sha256=target_sha256,
                input_tokens=producer_evidence.input_tokens,
                output_tokens=rq1_token_count(transformed_text),
                latency_ms=producer_evidence.latency_ms,
                cost_usd=producer_evidence.cost_usd,
                raw_response_id=producer_evidence.raw_response_id,
                sampling={"temperature": 0.0},
                metadata={
                    "model_version": model_version,
                    "output_token_cap": producer_output_token_cap,
                    "stopping_rule": RQ1_REAL_STOPPING_RULE,
                    "provider_completion_tokens": producer_evidence.output_tokens,
                    "api_called": True,
                },
            )
        )

    if is_raw:
        transmitted_artifact_ids = (*fact_ids, *distractor_ids)
    else:
        transmitted_artifact_ids = _literal_present_ids(manifest, transformed_text)

    message = MessageRecord(
        message_id=message_id,
        run_id=run_id,
        source_agent_id="source",
        target_agent_id="consumer",
        sent_step=4,
        content=transformed_text,
        content_sha256=target_sha256,
        expected_artifact_ids=fact_ids,
        artifact_ids=transmitted_artifact_ids,
        delivered=True,
        delivered_step=5,
        included_prompt_id=downstream_prompt_id,
        local_sequence=1,
        metadata={
            "transformation_id": transformation_id,
            "source_text_sha256": source_sha256,
        },
    )
    downstream_messages = (
        {
            "role": "user",
            "content": manifest.downstream_prompt_template.format(
                transformed_text=transformed_text
            ),
        },
    )
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
                "included_message_sha256": target_sha256,
                "prompt_template_sha256": downstream_contract["prompt_template_sha256"],
                "prompt_template": downstream_contract["prompt_template"],
            },
        )
    )
    calls.append(
        ModelCallRecord(
            call_id=downstream_call_id,
            run_id=run_id,
            agent_id="consumer",
            prompt_id=downstream_prompt_id,
            step=6,
            status=CallStatus.SUCCESS,
            provider=downstream_evidence.provider,
            model=downstream_evidence.model,
            response_sha256=text_sha256(downstream_text),
            input_tokens=downstream_evidence.input_tokens,
            output_tokens=downstream_evidence.output_tokens,
            latency_ms=downstream_evidence.latency_ms,
            cost_usd=downstream_evidence.cost_usd,
            raw_response_id=downstream_evidence.raw_response_id,
            sampling={"temperature": 0.0},
            metadata={
                "model_version": model_version,
                "context_token_cap": context_token_cap,
                "output_token_cap": downstream_output_token_cap,
                "stopping_rule": RQ1_REAL_STOPPING_RULE,
                "scorer_id": RQ1_REAL_SCORER_ID,
                "scorer_version": RQ1_REAL_SCORER_VERSION,
                "api_called": True,
            },
        )
    )

    events: list[LifecycleEvent] = []
    possession_ids = tuple(
        f"event-possessed-{suffix}-{fact_id}" for fact_id in fact_ids
    )
    for fact_id, possession_id in zip(fact_ids, possession_ids, strict=True):
        events.append(
            LifecycleEvent(
                event_id=possession_id,
                run_id=run_id,
                event_type=EventType.ARTIFACT_POSSESSED,
                step=1,
                timestamp=started_at,
                agent_id="source",
                artifact_id=fact_id,
                details={"observation": "fixture_assignment"},
            )
        )
    for distractor_id in distractor_ids:
        events.append(
            LifecycleEvent(
                event_id=f"event-possessed-{suffix}-{distractor_id}",
                run_id=run_id,
                event_type=EventType.ARTIFACT_POSSESSED,
                step=1,
                timestamp=started_at,
                agent_id="source",
                artifact_id=distractor_id,
                details={"observation": "fixture_distractor"},
            )
        )
    events.append(
        LifecycleEvent(
            event_id=output_event_id,
            run_id=run_id,
            event_type=EventType.ACTION_TAKEN,
            step=3,
            timestamp=started_at,
            agent_id="source",
            parent_event_ids=possession_ids,
            details={
                "action_id": f"rq1-transform-{suffix}",
                "depends_on_artifact_ids": [*fact_ids, *distractor_ids],
                "transformation_id": transformation_id,
                "source_tool_call_id": tool_call_id,
                "source_text_sha256": source_sha256,
                "target_text_sha256": target_sha256,
                "target_message_id": message_id,
                "arm": arm.value,
                "method": _method_for(arm).value,
            },
        )
    )
    sent_id_by_fact: dict[str, str] = {}
    delivered_event_by_fact: dict[str, str] = {}
    for fact_id in transmitted_artifact_ids:
        sent_id_by_fact[fact_id] = f"event-sent-{suffix}-{fact_id}"
        delivered_event_by_fact[fact_id] = f"event-delivered-{suffix}-{fact_id}"
    for fact_id in transmitted_artifact_ids:
        events.append(
            LifecycleEvent(
                event_id=sent_id_by_fact[fact_id],
                run_id=run_id,
                event_type=EventType.MESSAGE_SENT,
                step=4,
                timestamp=started_at,
                artifact_id=fact_id,
                source_agent_id="source",
                target_agent_id="consumer",
                edge_id="source-to-consumer",
                parent_event_ids=(output_event_id,),
                details={"message_id": message_id, "artifact_present": True},
            )
        )
    for fact_id in transmitted_artifact_ids:
        events.append(
            LifecycleEvent(
                event_id=delivered_event_by_fact[fact_id],
                run_id=run_id,
                event_type=EventType.MESSAGE_DELIVERED,
                step=5,
                timestamp=started_at,
                artifact_id=fact_id,
                source_agent_id="source",
                target_agent_id="consumer",
                edge_id="source-to-consumer",
                parent_event_ids=(sent_id_by_fact[fact_id],),
                details={"message_id": message_id},
            )
        )
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
                timestamp=started_at,
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
    downstream_event_id = f"event-downstream-{suffix}"
    events.append(
        LifecycleEvent(
            event_id=downstream_event_id,
            run_id=run_id,
            event_type=EventType.ACTION_TAKEN,
            step=7,
            timestamp=started_at,
            agent_id="consumer",
            parent_event_ids=tuple(exposure_event_ids),
            details={
                "action_id": f"rq1-downstream-assessment-{suffix}",
                "depends_on_artifact_ids": list(fact_ids),
                "transformation_id": transformation_id,
                "consumed_prompt_id": downstream_prompt_id,
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
            timestamp=started_at,
            parent_event_ids=(downstream_event_id,),
            details={"status": "engineering_smoke_complete"},
        )
    )

    annotations = [_transformation_annotation(row)]

    bundle = TraceBundle(
        manifest=manifest_record,
        artifacts=artifacts,
        prompts=tuple(prompts),
        events=tuple(events),
        outcome=RunOutcome(
            run_id=run_id,
            success=None,
            score=None,
            final_step=8,
            evaluator=f"{RQ1_REAL_SCORER_ID}@{RQ1_REAL_SCORER_VERSION}",
            outcome_kind=OutcomeKind.DIAGNOSTIC_ONLY,
            run_status=RunStatus.COMPLETED,
            details={
                "analysis_eligible": False,
                "api_called": True,
            },
        ),
        information_assignments=assignments,
        messages=(message,),
        model_calls=tuple(calls),
        tool_calls=(tool_call,),
        annotations=tuple(annotations),
    )
    bundle.validate()
    return bundle


def run_rq1_three_arm_calibration(
    *,
    manifest: RQ1FixtureManifest,
    call: CallFn,
    run_id_base: str,
    repeat_id: str,
    block_id: str,
    started_at: str,
    model: str,
    model_version: str,
    producer_system_prompt: str,
    context_token_cap: int,
    downstream_output_token_cap: int,
    producer_output_token_cap: int,
) -> tuple[TraceBundle, ...]:
    """Run C0/C1/T against a real provider and return three validated bundles."""

    manifest.validate()
    bundles: list[TraceBundle] = []
    for arm in (
        RQ1TransformationArm.RAW_PASSTHROUGH,
        RQ1TransformationArm.LENGTH_MATCHED_REFERENCE,
        RQ1TransformationArm.ABSTRACTIVE_SUMMARY,
    ):
        suffix = _arm_suffix(arm)
        if arm == RQ1TransformationArm.RAW_PASSTHROUGH:
            transformed_text = manifest.source_text
            producer_evidence = None
        elif arm == RQ1TransformationArm.LENGTH_MATCHED_REFERENCE:
            transformed_text = manifest.reference_text
            producer_evidence = None
        else:
            producer_messages: tuple[dict[str, str], ...] = (
                {"role": "system", "content": producer_system_prompt},
                {"role": "user", "content": manifest.source_text},
            )
            producer_evidence = call(producer_messages, producer_output_token_cap)
            transformed_text = producer_evidence.content
            if rq1_token_count(transformed_text) > manifest.token_budget:
                raise ValueError(
                    "model summary exceeds the registered RQ1 token_budget"
                )

        downstream_messages: tuple[dict[str, str], ...] = (
            {
                "role": "user",
                "content": manifest.downstream_prompt_template.format(
                    transformed_text=transformed_text
                ),
            },
        )
        downstream_evidence = call(downstream_messages, downstream_output_token_cap)
        bundle = build_real_rq1_bundle(
            manifest=manifest,
            arm=arm,
            transformed_text=transformed_text,
            downstream_text=downstream_evidence.content,
            producer_evidence=producer_evidence,
            downstream_evidence=downstream_evidence,
            run_id=f"{run_id_base}-{suffix}",
            repeat_id=repeat_id,
            block_id=block_id,
            started_at=started_at,
            model=model,
            model_version=model_version,
            producer_system_prompt=producer_system_prompt,
            context_token_cap=context_token_cap,
            downstream_output_token_cap=downstream_output_token_cap,
            producer_output_token_cap=producer_output_token_cap,
        )
        bundles.append(bundle)

    from .rq1 import extract_rq1_transformations

    validate_rq1_arm_set(
        row for bundle in bundles for row in extract_rq1_transformations(bundle)
    )
    return tuple(bundles)


__all__ = [
    "CallFn",
    "RealCallEvidence",
    "RQ1FixtureManifest",
    "RQ1_REAL_BENCHMARK_ID",
    "RQ1_REAL_PROTOCOL_KIND",
    "build_real_rq1_bundle",
    "run_rq1_three_arm_calibration",
]
