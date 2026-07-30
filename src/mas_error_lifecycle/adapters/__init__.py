"""Adapters for external multi-agent benchmarks."""

from .agentcollabbench import convert_agentcollab_result
from .agentcollab_runner import (
    AgentCollabEvaluation,
    create_agentcollab_runner,
    evaluate_agentcollab_task,
)
from .agentcollab_topology import rewire_agentcollab_task

__all__ = [
    "AgentCollabEvaluation",
    "convert_agentcollab_result",
    "create_agentcollab_runner",
    "evaluate_agentcollab_task",
    "rewire_agentcollab_task",
]
