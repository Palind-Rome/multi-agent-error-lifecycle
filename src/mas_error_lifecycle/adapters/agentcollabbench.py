"""Convert AgentCollabBench's full RunResult JSON into the lifecycle schema."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from ..schema import (
    AgentSpec,
    ArtifactRecord,
    EdgeSpec,
    EventType,
    LifecycleEvent,
    PromptRecord,
    RunManifest,
    RunOutcome,
    TruthStatus,
    prompt_sha256,
)
from ..store import TraceBundle


def convert_agentcollab_result(payload: dict[str, Any]) -> TraceBundle:
    """Convert a full AgentCollabBench result.

    Accepted input is either ``RunResult.to_dict()`` or a richer evaluation
    object containing it under ``run_result``. Exact marker reproduction is
    recorded as a *provisional* adoption proxy; it must not be confused with a
    semantic, action-grounded adoption label.
    """

    raw_run = payload.get("run_result") or payload
    if not isinstance(raw_run, dict):
        raise ValueError("payload.run_result must be an object")
    scenario = raw_run.get("scenario")
    trace = raw_run.get("trace")
    if not isinstance(scenario, dict) or not isinstance(trace, dict):
        raise ValueError("full AgentCollabBench scenario and trace are required")
    task_id = str(raw_run.get("task_id") or scenario.get("task_id") or "unknown")
    topology = scenario.get("topology", {})
    agent_rows = topology.get("agents", [])
    api_calls = trace.get("api_calls", [])
    api_by_agent: dict[str, dict[str, Any]] = {}
    for call in api_calls:
        if isinstance(call, dict) and call.get("agent_id"):
            api_by_agent.setdefault(str(call["agent_id"]), call)
    agents = tuple(
        AgentSpec(
            agent_id=str(row["agent_id"]),
            role=str(row.get("role") or row["agent_id"]),
            provider=str(api_by_agent.get(str(row["agent_id"]), {}).get("provider", "unknown")),
            model=str(api_by_agent.get(str(row["agent_id"]), {}).get("model", "unknown")),
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
    canonical = json.dumps(raw_run, sort_keys=True, ensure_ascii=False).encode()
    run_id = "acb-" + hashlib.sha256(canonical).hexdigest()[:16]
    base_time = datetime.now(UTC).replace(microsecond=0)
    manifest = RunManifest(
        run_id=run_id,
        task_id=task_id,
        condition_id="agentcollabbench-import",
        benchmark="AgentCollabBench",
        seed=0,
        started_at=base_time.isoformat(),
        agents=agents,
        topology=edges,
        config={
            "source_schema": "AgentCollabBench.RunResult",
            "metric_applicability": scenario.get("metric_applicability", []),
            "topology_type": topology.get("type"),
            "warning": (
                "Actual provider prompts are absent upstream; handoffs prove parent output "
                "availability, while exact-marker output is only a provisional adoption proxy."
            ),
        },
    )
    artifacts_and_markers = _extract_artifacts(scenario, run_id)
    artifacts = tuple(item[0] for item in artifacts_and_markers)
    hop_by_artifact = {
        artifact.artifact_id: _shortest_hops(edges, artifact.source_agent_id)
        for artifact, _ in artifacts_and_markers
    }
    events: list[LifecycleEvent] = []
    prompts: list[PromptRecord] = []
    step = 0

    def add(event_type: EventType, **kwargs: Any) -> LifecycleEvent:
        nonlocal step
        if event_type != EventType.ARTIFACT_GENERATED:
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

    generated_events: dict[str, LifecycleEvent] = {}
    for artifact, _ in artifacts_and_markers:
        generated_events[artifact.artifact_id] = add(
            EventType.ARTIFACT_GENERATED,
            agent_id=artifact.source_agent_id,
            artifact_id=artifact.artifact_id,
            details={"origin": artifact.metadata.get("injection_type", "unknown")},
        )

    turn_contents: dict[str, list[str]] = {}
    for turn in trace.get("turns", []):
        if isinstance(turn, dict) and turn.get("agent_id") and not turn.get("synthetic"):
            turn_contents.setdefault(str(turn["agent_id"]), []).append(
                str(turn.get("content", ""))
            )

    actual_prompts = _provider_request_prompts(
        trace.get("provider_requests", []),
        artifacts_and_markers,
        run_id,
    )
    prompts.extend(prompt for _, prompt in actual_prompts)

    active_agents: dict[str, set[str]] = {
        artifact.artifact_id: {artifact.source_agent_id}
        for artifact, _ in artifacts_and_markers
    }
    handoffs = [item for item in trace.get("handoffs", []) if isinstance(item, dict)]
    for handoff_index, handoff in enumerate(handoffs):
        sender = str(handoff.get("sender", ""))
        receiver = str(handoff.get("receiver", ""))
        content = str(handoff.get("content", ""))
        if not sender or not receiver:
            continue
        for artifact, markers in artifacts_and_markers:
            if sender not in active_agents[artifact.artifact_id]:
                continue
            marker_present = _contains_any(content, markers)
            sent = add(
                EventType.MESSAGE_SENT,
                artifact_id=artifact.artifact_id,
                source_agent_id=sender,
                target_agent_id=receiver,
                edge_id=(
                    f"{sender}->{receiver}"
                    if receiver != "__output__"
                    and any(
                        edge.source == sender and edge.target == receiver for edge in edges
                    )
                    else None
                ),
                parent_event_ids=(generated_events[artifact.artifact_id].event_id,),
                details={
                    "delivered": True,
                    "exact_marker_present": marker_present,
                    "artifact_present_in_message": marker_present,
                    "source": "upstream_handoff",
                },
            )
            if receiver == "__output__" or not marker_present:
                continue
            actual_prompt = next(
                (
                    prompt
                    for request_agent, prompt in actual_prompts
                    if request_agent == receiver
                    and artifact.artifact_id in prompt.artifact_ids
                ),
                None,
            )
            if actual_prompt is not None:
                prompt_id = actual_prompt.prompt_id
                actual_prompt_recorded = True
                exposure_evidence = "artifact in exact provider request"
            else:
                prompt_id = (
                    f"agentcollab-handoff:{handoff_index}:{receiver}:"
                    f"{artifact.artifact_id}"
                )
                prompt_messages = ({"role": "user", "content": content},)
                prompts.append(
                    PromptRecord(
                        prompt_id=prompt_id,
                        run_id=run_id,
                        agent_id=receiver,
                        step=step + 1,
                        messages=prompt_messages,
                        artifact_ids=(artifact.artifact_id,),
                        content_sha256=prompt_sha256(prompt_messages),
                        metadata={
                            "source": "upstream_handoff",
                            "completeness": "partial_parent_context",
                            "actual_full_provider_request_available": False,
                        },
                    )
                )
                actual_prompt_recorded = False
                exposure_evidence = "parent output in upstream handoff"
            exposed = add(
                EventType.ARTIFACT_EXPOSED,
                artifact_id=artifact.artifact_id,
                source_agent_id=sender,
                target_agent_id=receiver,
                edge_id=f"{sender}->{receiver}",
                prompt_id=prompt_id,
                parent_event_ids=(sent.event_id,),
                details={
                    "hop": hop_by_artifact[artifact.artifact_id].get(receiver),
                    "semantic_fidelity": 1.0,
                    "actual_prompt_recorded": actual_prompt_recorded,
                    "exposure_evidence": exposure_evidence,
                },
            )
            receiver_reproduced = any(
                _contains_any(output, markers) for output in turn_contents.get(receiver, [])
            )
            if receiver_reproduced and receiver not in active_agents[artifact.artifact_id]:
                add(
                    EventType.ARTIFACT_ADOPTED,
                    agent_id=receiver,
                    artifact_id=artifact.artifact_id,
                    source_agent_id=sender,
                    parent_event_ids=(exposed.event_id,),
                    details={
                        "hop": hop_by_artifact[artifact.artifact_id].get(receiver, 0),
                        "adoption_evidence": "exact_marker_reproduction",
                        "provisional": True,
                        "semantic_or_action_adoption_confirmed": False,
                    },
                )
                active_agents[artifact.artifact_id].add(receiver)

    add(
        EventType.RUN_FINALIZED,
        details={
            "raw_scores": payload.get("scores", {}),
            "raw_errors": payload.get("errors", {}),
            "task_outcome_available": False,
        },
    )
    input_tokens = sum(
        int(call.get("input_tokens", 0))
        for call in api_calls
        if isinstance(call, dict)
    )
    output_tokens = sum(
        int(call.get("output_tokens", 0))
        for call in api_calls
        if isinstance(call, dict)
    )
    outcome = RunOutcome(
        run_id=run_id,
        success=None,
        score=None,
        final_step=step,
        evaluator="not-available-in-AgentCollabBench",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=None,
        cost_usd=None,
        details={
            "diagnostic_scores": payload.get("scores", {}),
            "note": "AgentCollabBench diagnostic scores are not final task success.",
        },
    )
    bundle = TraceBundle(manifest, artifacts, tuple(prompts), tuple(events), outcome)
    bundle.validate()
    return bundle


def _extract_artifacts(
    scenario: dict[str, Any], run_id: str
) -> list[tuple[ArtifactRecord, tuple[str, ...]]]:
    injections = scenario.get("injections", {})
    extracted: list[tuple[ArtifactRecord, tuple[str, ...]]] = []
    cpr = injections.get("cpr", {})
    if isinstance(cpr, dict) and cpr.get("false_fact"):
        false_fact = str(cpr["false_fact"])
        extracted.append(
            (
                ArtifactRecord(
                    artifact_id="agentcollab:cpr:false-fact",
                    run_id=run_id,
                    source_agent_id=str(cpr.get("seed_agent") or _root_agent(scenario)),
                    created_step=0,
                    truth_status=TruthStatus.FALSE,
                    content=false_fact,
                    metadata={
                        "injection_type": "cpr",
                        "ground_truth": cpr.get("ground_truth"),
                    },
                ),
                (false_fact,),
            )
        )
    rtd = injections.get("rtd", {})
    if isinstance(rtd, dict) and rtd:
        constraints = rtd.get("constraints")
        rows = constraints if isinstance(constraints, list) else [rtd]
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            tracer_id = str(row.get("tracer_id", "")).strip()
            anchor = str(row.get("anchor", "")).strip()
            markers = tuple(value for value in (tracer_id, anchor) if value)
            if markers:
                extracted.append(
                    (
                        ArtifactRecord(
                            artifact_id=f"agentcollab:rtd:tracer-{index}",
                            run_id=run_id,
                            source_agent_id=_root_agent(scenario),
                            created_step=0,
                            truth_status=TruthStatus.TRUE,
                            content=anchor or tracer_id,
                            metadata={"injection_type": "rtd", "tracer_id": tracer_id},
                        ),
                        markers,
                    )
                )
    if not extracted:
        raise ValueError(
            "adapter currently requires a CPR false_fact or RTD tracer artifact"
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


def _contains_any(content: str, markers: tuple[str, ...]) -> bool:
    lowered = content.casefold()
    return any(marker.casefold() in lowered for marker in markers if marker)


def _shortest_hops(edges: tuple[EdgeSpec, ...], source: str) -> dict[str, int]:
    hops = {source: 0}
    frontier = [source]
    while frontier:
        current = frontier.pop(0)
        for edge in edges:
            if edge.source == current and edge.target not in hops:
                hops[edge.target] = hops[current] + 1
                frontier.append(edge.target)
    return hops


def _provider_request_prompts(
    rows: Any,
    artifacts_and_markers: list[tuple[ArtifactRecord, tuple[str, ...]]],
    run_id: str,
) -> list[tuple[str, PromptRecord]]:
    prompts: list[tuple[str, PromptRecord]] = []
    if not isinstance(rows, list):
        return prompts
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("agent_id"):
            continue
        raw_messages = row.get("messages", [])
        if not isinstance(raw_messages, list) or not raw_messages:
            continue
        messages = tuple(
            {"role": str(message["role"]), "content": str(message["content"])}
            for message in raw_messages
            if isinstance(message, dict) and "role" in message and "content" in message
        )
        if not messages:
            continue
        combined = "\n".join(message["content"] for message in messages)
        artifact_ids = tuple(
            artifact.artifact_id
            for artifact, markers in artifacts_and_markers
            if _contains_any(combined, markers)
        )
        agent_id = str(row["agent_id"])
        prompt = PromptRecord(
            prompt_id=f"agentcollab-provider-request:{index}:{agent_id}",
            run_id=run_id,
            agent_id=agent_id,
            step=index,
            messages=messages,
            artifact_ids=artifact_ids,
            content_sha256=prompt_sha256(messages),
            metadata={
                "source": "instrumented_provider_request",
                "actual_full_provider_request_available": True,
                "provider": row.get("provider"),
                "model": row.get("model"),
            },
        )
        prompts.append((agent_id, prompt))
    return prompts
