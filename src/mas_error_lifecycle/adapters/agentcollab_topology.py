"""Matched topology rewrites for AgentCollabBench task dictionaries."""

from __future__ import annotations

import copy
from typing import Any


def rewire_agentcollab_task(
    task: dict[str, Any],
    topology: str,
) -> dict[str, Any]:
    """Return a deep-copied task with agents held fixed and edges rewired.

    Supported labels are ``chain``, ``star``, ``converging_dag``, and
    ``fully_connected_dag``. The controlled injection source becomes the root
    when one is defined. At least four agents are required for a genuine
    converging DAG with two independent middle branches.
    """

    if topology not in {"chain", "star", "converging_dag", "fully_connected_dag"}:
        raise ValueError(
            "topology must be chain, star, converging_dag, or fully_connected_dag"
        )
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
    root = _injection_source(rewritten) or agent_ids[0]
    if root not in agent_ids:
        raise ValueError(f"injection source {root!r} is not a topology agent")
    ordered = [root, *(agent_id for agent_id in agent_ids if agent_id != root)]

    if topology == "chain":
        edges = list(zip(ordered, ordered[1:]))
        upstream_type = "linear_chain"
    elif topology == "star":
        if len(ordered) < 3:
            raise ValueError("star topology requires at least three agents")
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
    rewritten["task_id"] = f"{original_task_id}__topology-{topology}"
    rewritten["topology"] = {
        **topology_data,
        "type": upstream_type,
        "agents": agents,
        "edges": [[source, target] for source, target in edges],
        "speaking_order": ordered,
        "experimental_topology_label": topology,
        "source_task_id": original_task_id,
    }
    rewritten.setdefault("experimental_metadata", {}).update(
        {
            "intervention": "matched_topology_rewrite",
            "topology_label": topology,
            "held_fixed": [
                "description",
                "agent_roles",
                "agent_system_prompts",
                "injections",
                "ground_truth",
            ],
            "changed": ["edges", "receives_from", "speaking_order", "root_centrality"],
        }
    )
    return rewritten


def _injection_source(task: dict[str, Any]) -> str | None:
    injections = task.get("injections", {})
    cpr = injections.get("cpr", {}) if isinstance(injections, dict) else {}
    if isinstance(cpr, dict) and cpr.get("seed_agent"):
        return str(cpr["seed_agent"])
    return None
