"""Convert full AgentCollabBench results without inventing exposure/adoption."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

from ..schema import (
    AgentSpec,
    AnnotationRecord,
    ArtifactKind,
    ArtifactOrigin,
    ArtifactRecord,
    CallStatus,
    EdgeSpec,
    EventType,
    InformationAssignmentRecord,
    InjectionRecord,
    LifecycleEvent,
    MessageRecord,
    ModelCallRecord,
    OutcomeKind,
    PromptRecord,
    RunManifest,
    RunOutcome,
    RunStatus,
    TruthStatus,
    prompt_sha256,
    text_sha256,
)
from ..store import TraceBundle


@dataclass(frozen=True, slots=True)
class _ArtifactProbe:
    artifact: ArtifactRecord
    markers: tuple[str, ...]
    matcher: Callable[[str], bool]


def convert_agentcollab_result(
    payload: dict[str, Any],
    *,
    run_context: dict[str, Any] | None = None,
) -> TraceBundle:
    """Convert one full result while preserving what is and is not observed.

    Exact output markers become ``artifact_surfaced`` plus a non-authoritative
    annotation. They never become primary adoption. A handoff proves delivery,
    but exposure is emitted only when the artifact is observed in the receiver's
    exact provider request.
    """

    raw_run = payload.get("run_result") or payload
    if not isinstance(raw_run, dict):
        raise ValueError("payload.run_result must be an object")
    scenario = raw_run.get("scenario")
    trace = raw_run.get("trace")
    if not isinstance(scenario, dict) or not isinstance(trace, dict):
        raise ValueError("full AgentCollabBench scenario and trace are required")
    context = dict(run_context or payload.get("run_context") or {})
    task_id = str(raw_run.get("task_id") or scenario.get("task_id") or "unknown")
    topology = scenario.get("topology", {})
    agent_rows = topology.get("agents", [])
    api_calls = [row for row in trace.get("api_calls", []) if isinstance(row, dict)]
    api_by_agent: dict[str, dict[str, Any]] = {}
    for call in api_calls:
        if call.get("agent_id"):
            api_by_agent.setdefault(str(call["agent_id"]), call)
    agents = tuple(
        AgentSpec(
            agent_id=str(row["agent_id"]),
            role=str(row.get("role") or row["agent_id"]),
            provider=str(
                api_by_agent.get(str(row["agent_id"]), {}).get("provider", "unknown")
            ),
            model=str(
                api_by_agent.get(str(row["agent_id"]), {}).get("model", "unknown")
            ),
            metadata={"system_prompt_present": bool(row.get("system_prompt"))},
        )
        for row in agent_rows
    )
    edges = tuple(
        EdgeSpec(
            edge_id=f"{edge[0]}->{edge[1]}",
            source=str(edge[0]),
            target=str(edge[1]),
        )
        for edge in topology.get("edges", [])
        if isinstance(edge, list) and len(edge) == 2
    )
    edge_ids = {edge.edge_id for edge in edges}

    experimental = scenario.get("experimental_metadata", {})
    if not isinstance(experimental, dict):
        experimental = {}
    derived = (
        experimental.get("protocol_kind")
        == "agentcollab_derived_counterfactual"
    )
    benchmark = "AgentCollabBench-derived" if derived else "AgentCollabBench"
    protocol_kind = (
        "agentcollab_derived_counterfactual"
        if derived
        else str(context.get("protocol_kind", "agentcollab_native_observational"))
    )
    context_analysis_eligible = bool(context.get("analysis_eligible", False))
    analysis_eligible = (
        context_analysis_eligible
        and not derived
        and bool(context.get("condition_id"))
        and context.get("seed") is not None
    )
    canonical = json.dumps(
        {"payload": payload, "run_context": context},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    raw_result_hash = hashlib.sha256(canonical).hexdigest()
    run_id = str(context.get("run_id") or f"acb-{raw_result_hash[:20]}")
    base_time = datetime.now(UTC).replace(microsecond=0)
    provider_rows = [
        row for row in trace.get("provider_requests", []) if isinstance(row, dict)
    ]
    api_usage_complete = bool(api_calls) and all(
        isinstance(row.get("input_tokens"), int)
        and isinstance(row.get("output_tokens"), int)
        for row in api_calls
    )
    usage_complete = api_usage_complete and len(provider_rows) == len(api_calls)
    manifest = RunManifest(
        run_id=run_id,
        task_id=task_id,
        condition_id=str(
            context.get(
                "condition_id",
                f"{protocol_kind}:unassigned-observational-import",
            )
        ),
        benchmark=benchmark,
        seed=int(context["seed"]) if context.get("seed") is not None else None,
        started_at=base_time.isoformat(),
        agents=agents,
        topology=edges,
        protocol_kind=protocol_kind,
        suite_kind="derived" if derived else "native",
        purpose=str(context.get("purpose", "engineering_import")),
        pair_id=context.get("pair_id"),
        cluster_id=str(context.get("cluster_id", task_id)),
        assignment_id=context.get("assignment_id"),
        analysis_eligible=analysis_eligible,
        execution_status=(
            str(experimental.get("execution_status", "paused"))
            if derived
            else "ready"
        ),
        review_status=(
            str(experimental.get("review_status", "unvalidated"))
            if derived
            else str(context.get("review_status", "native"))
        ),
        preregistration_hash=context.get("preregistration_hash"),
        native_task_hash=(
            experimental.get("source_task_sha256")
            if derived
            else context.get("native_task_hash")
        ),
        upstream_commit=str(
            context.get(
                "upstream_commit",
                trace.get("provider_routing", {}).get(
                    "upstream_tested_commit", "unknown"
                ),
            )
        ),
        code_commit=context.get("code_commit"),
        config={
            "source_schema": "AgentCollabBench.RunResult",
            "metric_applicability": scenario.get("metric_applicability", []),
            "topology_type": topology.get("type"),
            "raw_result_sha256": raw_result_hash,
            "experimental_metadata": experimental,
            "assignment_observed": bool(context),
            "usage_reconciliation_complete": usage_complete,
            "construct_warning": (
                "Derived topology variants are non-native and non-causal until "
                "construct review; handoff-only evidence never counts as exposure."
                if derived
                else "Native diagnostic protocol; final task outcome is unavailable."
            ),
        },
    )

    probes = _extract_artifacts(scenario, run_id)
    artifacts = tuple(probe.artifact for probe in probes)
    assignments = tuple(
        InformationAssignmentRecord(
            assignment_id=f"assignment:{probe.artifact.artifact_id}",
            run_id=run_id,
            artifact_id=probe.artifact.artifact_id,
            holder_agent_ids=(str(probe.artifact.source_agent_id),),
            authorized_agent_ids=(str(probe.artifact.source_agent_id),),
            visibility_scope="benchmark_injected_source_context",
            required_for_solution=probe.artifact.required_to_surface,
            metadata={"metric": probe.artifact.metadata.get("injection_type")},
        )
        for probe in probes
    )
    injections = tuple(
        InjectionRecord(
            injection_id=f"injection:{probe.artifact.artifact_id}",
            run_id=run_id,
            artifact_id=probe.artifact.artifact_id,
            corruption_type=str(
                probe.artifact.metadata.get("injection_type", "benchmark_probe")
            ),
            validation_verdict="not_measured",
            target_agent_id=probe.artifact.source_agent_id,
            nominal_dose=1.0,
            realized_dose=None,
            dose_unit="atomic_artifact",
            ground_truth_ref=(
                "scenario.injections.cpr.ground_truth"
                if probe.artifact.truth_status == TruthStatus.FALSE
                else "scenario.injections.rtd.tracer_id"
            ),
            validator="AgentCollabBench protocol",
        )
        for probe in probes
    )

    events: list[LifecycleEvent] = []
    prompts: list[PromptRecord] = []
    messages: list[MessageRecord] = []
    model_calls: list[ModelCallRecord] = []
    annotations: list[AnnotationRecord] = []
    step = 0

    def add(event_type: EventType, **kwargs: Any) -> LifecycleEvent:
        nonlocal step
        step += 1
        event = LifecycleEvent(
            event_id=f"event-{len(events) + 1:05d}",
            run_id=run_id,
            event_type=event_type,
            step=step,
            timestamp=(base_time + timedelta(milliseconds=step)).isoformat(),
            **kwargs,
        )
        events.append(event)
        return event

    latest: dict[tuple[str, str], LifecycleEvent] = {}
    pending_deliveries: dict[tuple[str, str], list[LifecycleEvent]] = {}
    for probe in probes:
        source = str(probe.artifact.source_agent_id)
        possessed = add(
            EventType.ARTIFACT_POSSESSED,
            agent_id=source,
            artifact_id=probe.artifact.artifact_id,
            details={
                "turn_index": 0,
                "observation": "benchmark_injection_receipt",
                "origin": probe.artifact.origin.value,
            },
        )
        latest[(probe.artifact.artifact_id, source)] = possessed

    calls_by_agent = _calls_by_agent(provider_rows)
    handoffs = [row for row in trace.get("handoffs", []) if isinstance(row, dict)]
    handoff_used: set[int] = set()
    outgoing_count = {
        agent.agent_id: max(
            1,
            sum(edge.source == agent.agent_id for edge in edges),
        )
        for agent in agents
    }
    turns = [
        row
        for row in trace.get("turns", [])
        if isinstance(row, dict) and row.get("agent_id") and not row.get("synthetic")
    ]

    for turn_index, turn in enumerate(turns, 1):
        agent_id = str(turn["agent_id"])
        output = str(turn.get("content", ""))
        call = _pop_next_call(calls_by_agent, agent_id)
        prompt: PromptRecord | None = None
        if call is not None:
            prompt, call_record = _record_call(
                call,
                output,
                turn_index,
                run_id,
                step + 1,
                probes,
            )
            prompts.append(prompt)
            model_calls.append(call_record)
            for probe in probes:
                artifact_id = probe.artifact.artifact_id
                if artifact_id not in prompt.artifact_ids:
                    continue
                parents = pending_deliveries.pop((artifact_id, agent_id), [])
                if not parents:
                    state = latest.get((artifact_id, agent_id))
                    parents = [state] if state is not None else []
                message_ids = [
                    str(parent.details.get("message_id"))
                    for parent in parents
                    if parent.details.get("message_id")
                ]
                exposed = add(
                    EventType.ARTIFACT_EXPOSED,
                    artifact_id=artifact_id,
                    source_agent_id=(
                        parents[-1].source_agent_id if parents else None
                    ),
                    target_agent_id=agent_id,
                    prompt_id=prompt.prompt_id,
                    parent_event_ids=tuple(parent.event_id for parent in parents),
                    details={
                        "turn_index": turn_index,
                        "call_id": prompt.call_id,
                        "message_id": message_ids[-1] if len(message_ids) == 1 else None,
                        "parent_message_ids": message_ids,
                        "exposure_evidence": "exact_provider_request",
                    },
                )
                latest[(artifact_id, agent_id)] = exposed
                for message_id in message_ids:
                    _mark_included_prompt(messages, message_id, prompt.prompt_id)

        for probe in probes:
            artifact_id = probe.artifact.artifact_id
            if not probe.matcher(output):
                continue
            state = latest.get((artifact_id, agent_id))
            if state is None:
                state = add(
                    EventType.ARTIFACT_POSSESSED,
                    agent_id=agent_id,
                    artifact_id=artifact_id,
                    details={
                        "turn_index": turn_index,
                        "observation": "inferred_from_observed_output",
                        "authorized": False,
                    },
                )
            surfaced = add(
                EventType.ARTIFACT_SURFACED,
                agent_id=agent_id,
                artifact_id=artifact_id,
                parent_event_ids=(state.event_id,),
                details={
                    "turn_index": turn_index,
                    "opportunity_id": f"turn:{turn_index}:{agent_id}",
                    "channel": "model_output",
                    "surface_evidence": "exact_marker",
                    "semantic_fidelity": None,
                },
            )
            latest[(artifact_id, agent_id)] = surfaced
            annotations.append(
                AnnotationRecord(
                    annotation_id=f"annotation:{len(annotations) + 1:05d}",
                    run_id=run_id,
                    taxonomy="surface-proxy",
                    taxonomy_version="0.2.0",
                    labels=("marker_surface_proxy", "textual_reproduction"),
                    annotator="deterministic-marker",
                    identifiability="surface_only",
                    target_event_ids=(surfaced.event_id,),
                    artifact_id=artifact_id,
                    agent_id=agent_id,
                    evidence_spans=(next(
                        marker for marker in probe.markers if _literal_present(output, marker)
                    ),),
                    confidence=1.0,
                    metadata={
                        "authoritative_adoption": False,
                        "polarity_unknown": True,
                    },
                )
            )

        matching_handoffs = _consume_handoffs(
            handoffs,
            handoff_used,
            agent_id,
            output,
            outgoing_count.get(agent_id, 1),
        )
        for handoff_index, handoff in matching_handoffs:
            receiver = str(handoff.get("receiver", ""))
            if not receiver:
                continue
            known_probes = [
                probe
                for probe in probes
                if (probe.artifact.artifact_id, agent_id) in latest
            ]
            present_probes = [probe for probe in known_probes if probe.matcher(output)]
            message_id = str(
                handoff.get("message_id")
                or f"agentcollab-handoff:{handoff_index}:{agent_id}:{receiver}"
            )
            sent_steps: list[int] = []
            delivered_steps: list[int] = []
            for probe in known_probes:
                artifact_id = probe.artifact.artifact_id
                present = probe in present_probes
                state = latest[(artifact_id, agent_id)]
                sent = add(
                    EventType.MESSAGE_SENT,
                    artifact_id=artifact_id,
                    source_agent_id=agent_id,
                    target_agent_id=receiver,
                    edge_id=(
                        f"{agent_id}->{receiver}"
                        if f"{agent_id}->{receiver}" in edge_ids
                        else None
                    ),
                    parent_event_ids=(state.event_id,),
                    details={
                        "message_id": message_id,
                        "artifact_present": present,
                        "turn_index": turn_index,
                    },
                )
                delivered_event = add(
                    EventType.MESSAGE_DELIVERED,
                    artifact_id=artifact_id,
                    source_agent_id=agent_id,
                    target_agent_id=receiver,
                    edge_id=(
                        f"{agent_id}->{receiver}"
                        if f"{agent_id}->{receiver}" in edge_ids
                        else None
                    ),
                    parent_event_ids=(sent.event_id,),
                    details={
                        "message_id": message_id,
                        "turn_index": turn_index,
                    },
                )
                sent_steps.append(sent.step)
                delivered_steps.append(delivered_event.step)
                if present and receiver != "__output__":
                    pending_deliveries.setdefault((artifact_id, receiver), []).append(
                        delivered_event
                    )
            messages.append(
                MessageRecord(
                    message_id=message_id,
                    run_id=run_id,
                    source_agent_id=agent_id,
                    target_agent_id=receiver,
                    sent_step=min(sent_steps) if sent_steps else step,
                    content=output,
                    content_sha256=text_sha256(output),
                    expected_artifact_ids=tuple(
                        probe.artifact.artifact_id for probe in known_probes
                    ),
                    artifact_ids=tuple(
                        probe.artifact.artifact_id for probe in present_probes
                    ),
                    delivered=True,
                    delivered_step=max(delivered_steps) if delivered_steps else step,
                    local_sequence=turn_index,
                    metadata={
                        "source": "upstream_handoff",
                        "upstream_timestamp": handoff.get("timestamp"),
                    },
                )
            )

    for agent_id, queue in calls_by_agent.items():
        for call in queue:
            prompt, call_record = _record_call(
                call,
                "",
                len(turns) + len(model_calls) + 1,
                run_id,
                step + 1,
                probes,
            )
            prompts.append(prompt)
            model_calls.append(call_record)
            for probe in probes:
                artifact_id = probe.artifact.artifact_id
                if artifact_id not in prompt.artifact_ids:
                    continue
                parents = pending_deliveries.pop((artifact_id, agent_id), [])
                exposed = add(
                    EventType.ARTIFACT_EXPOSED,
                    artifact_id=artifact_id,
                    source_agent_id=(
                        parents[-1].source_agent_id if parents else None
                    ),
                    target_agent_id=agent_id,
                    prompt_id=prompt.prompt_id,
                    parent_event_ids=tuple(parent.event_id for parent in parents),
                    details={
                        "turn_index": len(turns) + len(model_calls),
                        "call_id": prompt.call_id,
                        "message_id": (
                            parents[-1].details.get("message_id")
                            if len(parents) == 1
                            else None
                        ),
                        "parent_message_ids": [
                            parent.details.get("message_id") for parent in parents
                        ],
                        "exposure_evidence": "exact_provider_request",
                    },
                )
                latest[(artifact_id, agent_id)] = exposed

    add(
        EventType.RUN_FINALIZED,
        details={
            "turn_index": len(turns),
            "raw_scores": payload.get("scores", {}),
            "raw_errors": payload.get("errors", {}),
            "task_outcome_available": False,
            "unconsumed_handoffs": len(handoffs) - len(handoff_used),
        },
    )
    input_tokens = (
        sum(int(call["input_tokens"]) for call in api_calls)
        if api_usage_complete
        else None
    )
    output_tokens = (
        sum(int(call["output_tokens"]) for call in api_calls)
        if api_usage_complete
        else None
    )
    outcome = RunOutcome(
        run_id=run_id,
        success=None,
        score=None,
        final_step=step,
        evaluator="AgentCollabBench-diagnostic-only",
        outcome_kind=OutcomeKind.DIAGNOSTIC_ONLY,
        run_status=RunStatus.COMPLETED,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=None,
        cost_usd=None,
        details={
            "diagnostic_scores": payload.get("scores", {}),
            "detailed_evaluation": payload.get("detailed"),
            "native_score": not derived,
            "note": "Diagnostic scores are not final task success.",
        },
    )
    bundle = TraceBundle(
        manifest=manifest,
        artifacts=artifacts,
        prompts=tuple(prompts),
        events=tuple(events),
        outcome=outcome,
        information_assignments=assignments,
        injections=injections,
        messages=tuple(messages),
        model_calls=tuple(model_calls),
        annotations=tuple(annotations),
    )
    bundle.validate()
    return bundle


def _extract_artifacts(
    scenario: dict[str, Any], run_id: str
) -> list[_ArtifactProbe]:
    injections = scenario.get("injections", {})
    extracted: list[_ArtifactProbe] = []
    cpr = injections.get("cpr", {}) if isinstance(injections, dict) else {}
    if isinstance(cpr, dict) and cpr.get("false_fact"):
        false_fact = str(cpr["false_fact"])
        artifact = ArtifactRecord(
            artifact_id="agentcollab:cpr:false-fact",
            run_id=run_id,
            source_agent_id=str(cpr.get("seed_agent") or _root_agent(scenario)),
            created_step=0,
            truth_status=TruthStatus.FALSE,
            content=false_fact,
            origin=ArtifactOrigin.CONTROLLED_INJECTION,
            kind=ArtifactKind.CLAIM,
            origin_actor_id="AgentCollabBench-harness",
            metadata={
                "injection_type": "cpr",
                "ground_truth": cpr.get("ground_truth"),
            },
        )
        extracted.append(
            _ArtifactProbe(
                artifact=artifact,
                markers=(false_fact,),
                matcher=lambda content, marker=false_fact: _literal_present(
                    content, marker
                ),
            )
        )
    rtd = injections.get("rtd", {}) if isinstance(injections, dict) else {}
    if isinstance(rtd, dict) and rtd:
        constraints = rtd.get("constraints")
        rows = constraints if isinstance(constraints, list) else [rtd]
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            tracer_id = str(row.get("tracer_id", "")).strip()
            if not tracer_id:
                continue
            artifact = ArtifactRecord(
                artifact_id=f"agentcollab:rtd:tracer-{index}",
                run_id=run_id,
                source_agent_id=_root_agent(scenario),
                created_step=0,
                truth_status=TruthStatus.TRUE,
                content=tracer_id,
                origin=ArtifactOrigin.BENCHMARK_PROBE,
                kind=ArtifactKind.TRACER,
                origin_actor_id="AgentCollabBench-harness",
                required_to_surface=True,
                metadata={
                    "injection_type": "rtd",
                    "tracer_id": tracer_id,
                    "anchor_excluded_from_canonical_match": row.get("anchor"),
                },
            )
            extracted.append(
                _ArtifactProbe(
                    artifact=artifact,
                    markers=(tracer_id,),
                    matcher=lambda content, marker=tracer_id: _canonical_tracer_present(
                        content, marker
                    ),
                )
            )
    if not extracted:
        raise ValueError(
            "adapter v0.2 currently supports CPR false_fact and RTD tracer tasks; "
            "IDR/CLC require separate lifecycle mappings"
        )
    return extracted


def _root_agent(scenario: dict[str, Any]) -> str:
    topology = scenario.get("topology", {})
    agents = topology.get("agents", [])
    for agent in agents:
        if isinstance(agent, dict) and not agent.get("receives_from"):
            return str(agent.get("agent_id"))
    if agents and isinstance(agents[0], dict):
        return str(agents[0].get("agent_id"))
    raise ValueError("cannot identify root agent")


def _literal_present(content: str, marker: str) -> bool:
    return bool(marker) and marker.casefold() in content.casefold()


def _canonical_tracer_present(content: str, marker: str) -> bool:
    if not marker:
        return False
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(marker)}(?![A-Za-z0-9_])"
    return re.search(pattern, content, flags=re.IGNORECASE) is not None


def _calls_by_agent(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    queues: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        if not row.get("agent_id"):
            continue
        normalized = dict(row)
        normalized.setdefault("call_id", f"agentcollab-call-{index + 1:05d}")
        normalized.setdefault("call_index", index)
        queues.setdefault(str(row["agent_id"]), []).append(normalized)
    return queues


def _pop_next_call(
    queues: dict[str, list[dict[str, Any]]], agent_id: str
) -> dict[str, Any] | None:
    queue = queues.get(agent_id, [])
    return queue.pop(0) if queue else None


def _record_call(
    row: dict[str, Any],
    fallback_response: str,
    turn_index: int,
    run_id: str,
    step: int,
    probes: list[_ArtifactProbe],
) -> tuple[PromptRecord, ModelCallRecord]:
    raw_messages = row.get("messages", [])
    messages = tuple(
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in raw_messages
        if isinstance(message, dict) and "role" in message and "content" in message
    )
    if not messages:
        messages = ({"role": "user", "content": "[request unavailable]"},)
    combined = "\n".join(message["content"] for message in messages)
    artifact_ids = tuple(
        probe.artifact.artifact_id for probe in probes if probe.matcher(combined)
    )
    call_id = str(row["call_id"])
    agent_id = str(row["agent_id"])
    prompt_id = f"agentcollab-provider-request:{call_id}:{agent_id}"
    prompt = PromptRecord(
        prompt_id=prompt_id,
        run_id=run_id,
        agent_id=agent_id,
        step=step,
        messages=messages,
        artifact_ids=artifact_ids,
        content_sha256=prompt_sha256(messages),
        call_id=call_id,
        round_id=f"turn-{turn_index}",
        metadata={
            "source": "instrumented_provider_request",
            "actual_full_provider_request_available": bool(raw_messages),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "call_index": row.get("call_index"),
            "request_started_at": row.get("request_started_at"),
        },
    )
    response = str(row.get("response_content", fallback_response))
    status_raw = str(row.get("status", "success"))
    status = (
        CallStatus(status_raw)
        if status_raw in {item.value for item in CallStatus}
        else CallStatus.ERROR
    )
    call = ModelCallRecord(
        call_id=call_id,
        run_id=run_id,
        agent_id=agent_id,
        prompt_id=prompt_id,
        step=step,
        status=status,
        provider=str(row.get("provider", "unknown")),
        model=str(row.get("model", "unknown")),
        response_sha256=text_sha256(response) if response else None,
        input_tokens=(
            int(row["input_tokens"])
            if isinstance(row.get("input_tokens"), int)
            else None
        ),
        output_tokens=(
            int(row["output_tokens"])
            if isinstance(row.get("output_tokens"), int)
            else None
        ),
        latency_ms=(
            float(row["latency_ms"])
            if isinstance(row.get("latency_ms"), int | float)
            else None
        ),
        cost_usd=(
            float(row["cost_usd"])
            if isinstance(row.get("cost_usd"), int | float)
            else None
        ),
        raw_response_id=row.get("raw_response_id"),
        error_type=row.get("error_type"),
        sampling=dict(row.get("sampling", {})),
        metadata={
            "turn_index": turn_index,
            "response_finished_at": row.get("response_finished_at"),
        },
    )
    return prompt, call


def _consume_handoffs(
    handoffs: list[dict[str, Any]],
    used: set[int],
    sender: str,
    content: str,
    limit: int,
) -> list[tuple[int, dict[str, Any]]]:
    matched: list[tuple[int, dict[str, Any]]] = []
    for index, handoff in enumerate(handoffs):
        if index in used:
            continue
        if str(handoff.get("sender", "")) != sender:
            continue
        if str(handoff.get("content", "")) != content:
            continue
        used.add(index)
        matched.append((index, handoff))
        if len(matched) >= limit:
            break
    return matched


def _mark_included_prompt(
    messages: list[MessageRecord], message_id: str, prompt_id: str
) -> None:
    for index, message in enumerate(messages):
        if message.message_id == message_id and message.included_prompt_id is None:
            messages[index] = replace(message, included_prompt_id=prompt_id)
            return
