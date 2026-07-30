"""Generate explicitly derived AgentCollabBench counterfactual stress tasks."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


DERIVED_PROTOCOL_KIND = "agentcollab_derived_counterfactual"


def generate_agentcollab_derived_counterfactual(
    task: dict[str, Any],
    topology: str,
) -> dict[str, Any]:
    """Return an unvalidated derived variant, never a native benchmark task.

    The generator preserves role text and system prompts but changes routing,
    speaking order, leaf contributors, context volume, and exposure opportunity.
    It therefore estimates a graph/protocol bundle unless a later construct
    review supplies a fixed external aggregator and matched opportunity design.
    """

    allowed = {"chain", "broadcast_star", "converging_dag", "fully_connected_dag"}
    if topology not in allowed:
        raise ValueError(f"topology must be one of {sorted(allowed)}")
    source_hash = _task_hash(task)
    rewritten = copy.deepcopy(task)
    topology_data = rewritten.get("topology")
    if not isinstance(topology_data, dict):
        raise ValueError("task.topology must be an object")
    agents = topology_data.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        raise ValueError("topology rewrite requires at least two agents")
    agent_ids = [str(agent["agent_id"]) for agent in agents]
    if len(agent_ids) != len(set(agent_ids)):
        raise ValueError("agent IDs must be unique")
    root = _injection_source(rewritten) or _native_root(rewritten) or agent_ids[0]
    if root not in agent_ids:
        raise ValueError(f"injection source {root!r} is not a topology agent")
    ordered = [root, *(agent_id for agent_id in agent_ids if agent_id != root)]

    if topology == "chain":
        edges = list(zip(ordered, ordered[1:]))
        upstream_type = "linear_chain"
    elif topology == "broadcast_star":
        if len(ordered) < 3:
            raise ValueError("broadcast_star requires at least three agents")
        edges = [(root, target) for target in ordered[1:]]
        upstream_type = "branching_tree"
    elif topology == "converging_dag":
        if len(ordered) < 4:
            raise ValueError(
                "converging_dag requires at least four agents for two middle branches"
            )
        sink = ordered[-1]
        middle = ordered[1:-1]
        edges = [(root, agent_id) for agent_id in middle]
        edges.extend((agent_id, sink) for agent_id in middle)
        upstream_type = "converging_dag"
    else:
        edges = [
            (source, target)
            for source_index, source in enumerate(ordered)
            for target in ordered[source_index + 1 :]
        ]
        upstream_type = "fully_connected"

    parents: dict[str, list[str]] = {agent_id: [] for agent_id in ordered}
    for source, target in edges:
        parents[target].append(source)
    for agent in agents:
        agent["receives_from"] = parents[str(agent["agent_id"])]

    original_task_id = str(rewritten.get("task_id", "unknown"))
    variant_id = (
        f"{original_task_id}__derived-{topology}__{source_hash[:10]}"
    )
    rewritten["task_id"] = variant_id
    rewritten["topology"] = {
        **topology_data,
        "type": upstream_type,
        "agents": agents,
        "edges": [[source, target] for source, target in edges],
        "speaking_order": ordered,
        "derived_topology_label": topology,
        "source_task_id": original_task_id,
        "source_task_sha256": source_hash,
    }
    rewritten.setdefault("experimental_metadata", {}).update(
        {
            "protocol_kind": DERIVED_PROTOCOL_KIND,
            "suite_name": "AgentCollabBench-derived",
            "variant_id": variant_id,
            "source_benchmark": "AgentCollabBench",
            "source_task_id": original_task_id,
            "source_task_sha256": source_hash,
            "intervention": "derived_graph_protocol_stress",
            "topology_label": topology,
            "review_status": "unvalidated",
            "execution_status": "paused",
            "analysis_eligible": False,
            "causal_eligible": False,
            "native_score_export_allowed": False,
            "held_fixed": [
                "description",
                "agent_ids",
                "agent_roles",
                "agent_system_prompts",
                "injections",
                "ground_truth",
            ],
            "changed": [
                "edges",
                "receives_from",
                "speaking_order",
                "root_centrality",
                "leaf_contributors",
                "context_volume",
                "exposure_opportunities",
            ],
            "known_unmatched": [
                "final_output_contributor_count",
                "message_count",
                "communication_tokens",
                "hop_opportunities",
            ],
            "required_reviews": [
                "topology_realism",
                "metric_artifact_isolation",
                "fixed_aggregator_and_opportunity_audit",
            ],
        }
    )
    return rewritten


def rewire_agentcollab_task(
    task: dict[str, Any],
    topology: str,
) -> dict[str, Any]:
    """Compatibility alias for the explicitly derived generator."""

    if topology == "star":
        topology = "broadcast_star"
    return generate_agentcollab_derived_counterfactual(task, topology)


def _injection_source(task: dict[str, Any]) -> str | None:
    injections = task.get("injections", {})
    if not isinstance(injections, dict):
        return None
    cpr = injections.get("cpr", {})
    if isinstance(cpr, dict) and cpr.get("seed_agent"):
        return str(cpr["seed_agent"])
    return None


def _native_root(task: dict[str, Any]) -> str | None:
    topology = task.get("topology", {})
    agents = topology.get("agents", []) if isinstance(topology, dict) else []
    for agent in agents:
        if isinstance(agent, dict) and not agent.get("receives_from"):
            return str(agent.get("agent_id"))
    return None


def _task_hash(task: dict[str, Any]) -> str:
    canonical = json.dumps(
        task, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
