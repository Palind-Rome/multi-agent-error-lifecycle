"""Deterministic lifecycle simulator used to test instrumentation before API runs."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from .schema import (
    AgentSpec,
    ArtifactRecord,
    EdgeSpec,
    EventType,
    LifecycleEvent,
    PromptRecord,
    RunManifest,
    RunOutcome,
    TruthStatus,
    VerificationVerdict,
    prompt_sha256,
)
from .store import TraceBundle


@dataclass(frozen=True, slots=True)
class MockRunConfig:
    seed: int = 7
    topology: str = "converging_dag"
    verification: str = "evidence_required"
    adoption_probability: float = 0.8
    verification_probability: float | None = None
    verification_accuracy: float = 0.9
    transmission_probability: float = 1.0

    def validate(self) -> None:
        if self.topology not in {"chain", "star", "converging_dag"}:
            raise ValueError("topology must be chain, star, or converging_dag")
        if self.verification not in {"none", "selective", "evidence_required"}:
            raise ValueError(
                "verification must be none, selective, or evidence_required"
            )
        for name in (
            "adoption_probability",
            "verification_accuracy",
            "transmission_probability",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.verification_probability is not None and not (
            0.0 <= self.verification_probability <= 1.0
        ):
            raise ValueError("verification_probability must be in [0, 1]")


def run_mock(config: MockRunConfig) -> TraceBundle:
    """Simulate one planted false artifact moving through a fixed topology."""

    config.validate()
    rng = random.Random(config.seed)
    agents, edges, hop_by_agent = _topology(config.topology)
    base_time = datetime.now(UTC).replace(microsecond=0)
    run_id = str(
        uuid5(
            NAMESPACE_URL,
            "mas-error-lifecycle:"
            f"{config.seed}:{config.topology}:{config.verification}:"
            f"{config.adoption_probability}:{config.verification_accuracy}",
        )
    )
    manifest = RunManifest(
        run_id=run_id,
        task_id="mock-planted-false-claim",
        condition_id=f"{config.topology}__{config.verification}",
        benchmark="instrumentation-smoke",
        seed=config.seed,
        started_at=base_time.isoformat(),
        agents=agents,
        topology=edges,
        config={
            "provider": "deterministic-script",
            "topology": config.topology,
            "verification": config.verification,
            "adoption_probability": config.adoption_probability,
            "verification_probability": _verification_probability(config),
            "verification_accuracy": config.verification_accuracy,
            "transmission_probability": config.transmission_probability,
        },
    )
    artifact = ArtifactRecord(
        artifact_id="claim:false:source-format",
        run_id=run_id,
        source_agent_id="root",
        created_step=0,
        truth_status=TruthStatus.FALSE,
        content="The input data is JSON; it is actually CSV.",
        metadata={
            "origin": "controlled_injection",
            "ground_truth": "The input data is CSV.",
            "error_type": "factual",
        },
    )
    events: list[LifecycleEvent] = []
    prompts: list[PromptRecord] = []
    step = 0

    def add_event(event_type: EventType, **kwargs: object) -> LifecycleEvent:
        nonlocal step
        if event_type != EventType.ARTIFACT_GENERATED:
            step += 1
        event = LifecycleEvent(
            event_id=f"event-{len(events) + 1:04d}",
            run_id=run_id,
            event_type=event_type,
            step=step,
            timestamp=(base_time + timedelta(milliseconds=step)).isoformat(),
            **kwargs,
        )
        events.append(event)
        return event

    generated = add_event(
        EventType.ARTIFACT_GENERATED,
        agent_id="root",
        artifact_id=artifact.artifact_id,
        details={"origin": "controlled_injection"},
    )
    contaminated = {"root"}
    verification_probability = _verification_probability(config)

    for edge in edges:
        if edge.source not in contaminated:
            continue
        delivered = rng.random() < config.transmission_probability
        sent = add_event(
            EventType.MESSAGE_SENT,
            artifact_id=artifact.artifact_id,
            source_agent_id=edge.source,
            target_agent_id=edge.target,
            edge_id=edge.edge_id,
            parent_event_ids=(generated.event_id,),
            details={
                "delivered": delivered,
                "artifact_present_in_message": True,
            },
        )
        if not delivered:
            continue
        prompt_id = f"prompt:{edge.target}:{len(prompts) + 1}"
        prompt_messages = (
            {
                "role": "system",
                "content": f"You are agent {edge.target}. Evaluate incoming evidence.",
            },
            {
                "role": "user",
                "content": f"Incoming claim from {edge.source}: {artifact.content}",
            },
        )
        prompts.append(
            PromptRecord(
                prompt_id=prompt_id,
                run_id=run_id,
                agent_id=edge.target,
                step=step + 1,
                messages=prompt_messages,
                artifact_ids=(artifact.artifact_id,),
                content_sha256=prompt_sha256(prompt_messages),
                metadata={"source": "deterministic_mock"},
            )
        )
        exposed = add_event(
            EventType.ARTIFACT_EXPOSED,
            artifact_id=artifact.artifact_id,
            source_agent_id=edge.source,
            target_agent_id=edge.target,
            edge_id=edge.edge_id,
            prompt_id=prompt_id,
            parent_event_ids=(sent.event_id,),
            details={
                "hop": hop_by_agent[edge.target],
                "semantic_fidelity": 1.0,
                "actual_prompt_recorded": True,
            },
        )
        if edge.target in contaminated:
            continue
        if rng.random() >= config.adoption_probability:
            add_event(
                EventType.ARTIFACT_REJECTED,
                agent_id=edge.target,
                artifact_id=artifact.artifact_id,
                source_agent_id=edge.source,
                parent_event_ids=(exposed.event_id,),
                details={"reason": "independent_reasoning"},
            )
            continue

        adopted = add_event(
            EventType.ARTIFACT_ADOPTED,
            agent_id=edge.target,
            artifact_id=artifact.artifact_id,
            source_agent_id=edge.source,
            parent_event_ids=(exposed.event_id,),
            details={
                "hop": hop_by_agent[edge.target],
                "adoption_evidence": "downstream_action_depends_on_claim",
            },
        )
        contaminated.add(edge.target)
        if rng.random() >= verification_probability:
            continue

        started = add_event(
            EventType.VERIFICATION_STARTED,
            agent_id=edge.target,
            artifact_id=artifact.artifact_id,
            parent_event_ids=(adopted.event_id,),
            details={"policy": config.verification, "evidence_required": True},
        )
        correctly_refuted = rng.random() < config.verification_accuracy
        completed = add_event(
            EventType.VERIFICATION_COMPLETED,
            agent_id=edge.target,
            artifact_id=artifact.artifact_id,
            parent_event_ids=(started.event_id,),
            details={
                "verdict": (
                    VerificationVerdict.REFUTED.value
                    if correctly_refuted
                    else VerificationVerdict.SUPPORTED.value
                ),
                "evidence_ids": ["mock-ground-truth-record"],
            },
        )
        if correctly_refuted:
            add_event(
                EventType.ARTIFACT_RECOVERED,
                agent_id=edge.target,
                artifact_id=artifact.artifact_id,
                parent_event_ids=(completed.event_id,),
                details={"mechanism": "evidence_based_rollback"},
            )
            contaminated.discard(edge.target)

    leaf_agents = {
        agent.agent_id for agent in agents
    } - {edge.source for edge in edges}
    contaminated_leaves = leaf_agents & contaminated
    score = 1.0 - (len(contaminated_leaves) / len(leaf_agents))
    add_event(
        EventType.RUN_FINALIZED,
        details={
            "contaminated_agents": sorted(contaminated),
            "contaminated_leaf_agents": sorted(contaminated_leaves),
        },
    )
    outcome = RunOutcome(
        run_id=run_id,
        success=not contaminated_leaves,
        score=score,
        final_step=step,
        evaluator="deterministic-leaf-contamination",
        input_tokens=120 * len(events),
        output_tokens=60 * len(events),
        latency_ms=25.0 * len(events),
        cost_usd=0.0,
        details={"leaf_agents": sorted(leaf_agents)},
    )
    bundle = TraceBundle(manifest, (artifact,), tuple(prompts), tuple(events), outcome)
    bundle.validate()
    return bundle


def _verification_probability(config: MockRunConfig) -> float:
    if config.verification_probability is not None:
        return config.verification_probability
    return {"none": 0.0, "selective": 0.45, "evidence_required": 0.95}[
        config.verification
    ]


def _topology(
    name: str,
) -> tuple[tuple[AgentSpec, ...], tuple[EdgeSpec, ...], dict[str, int]]:
    definitions = {
        "chain": (
            (
                ("root", "source"),
                ("worker-1", "analyst"),
                ("worker-2", "implementer"),
                ("sink", "integrator"),
            ),
            (
                ("root", "worker-1"),
                ("worker-1", "worker-2"),
                ("worker-2", "sink"),
            ),
        ),
        "star": (
            (
                ("root", "coordinator"),
                ("leaf-1", "analyst"),
                ("leaf-2", "implementer"),
                ("leaf-3", "reviewer"),
            ),
            (
                ("root", "leaf-1"),
                ("root", "leaf-2"),
                ("root", "leaf-3"),
            ),
        ),
        "converging_dag": (
            (
                ("root", "source"),
                ("branch-1", "analyst"),
                ("branch-2", "implementer"),
                ("sink", "integrator"),
            ),
            (
                ("root", "branch-1"),
                ("root", "branch-2"),
                ("branch-1", "sink"),
                ("branch-2", "sink"),
            ),
        ),
    }
    agent_rows, edge_rows = definitions[name]
    agents = tuple(
        AgentSpec(agent_id=agent_id, role=role, provider="mock", model="script-v1")
        for agent_id, role in agent_rows
    )
    edges = tuple(
        EdgeSpec(edge_id=f"{source}->{target}", source=source, target=target)
        for source, target in edge_rows
    )
    hops = {"root": 0}
    remaining = list(edges)
    while remaining:
        next_remaining: list[EdgeSpec] = []
        changed = False
        for edge in remaining:
            if edge.source in hops:
                hops[edge.target] = max(hops.get(edge.target, 0), hops[edge.source] + 1)
                changed = True
            else:
                next_remaining.append(edge)
        if not changed:
            raise ValueError(f"topology {name} is cyclic or disconnected")
        remaining = next_remaining
    return agents, edges, hops
