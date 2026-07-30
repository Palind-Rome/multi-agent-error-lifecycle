"""Pinned AgentCollabBench runner shim with per-agent provider routing.

The upstream ``TaskRunner`` accepts one provider for every role. This factory
uses its synchronous call order to select a provider immediately before each
agent call and records the exact request messages. It is tested against upstream
commit ``f016f60``; re-run the offline smoke test when upgrading upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AgentCollabEvaluation:
    task_id: str
    metric: str
    score: float
    detailed: Any
    run_result: Any

    def to_adapter_payload(self) -> dict[str, Any]:
        """Return a JSON-safe payload accepted by the lifecycle adapter."""

        return {
            "task_id": self.task_id,
            "scores": {self.metric: self.score},
            "errors": {},
            "run_result": self.run_result.to_dict(),
        }


def create_agentcollab_runner(
    providers: dict[str, Any],
    *,
    metric: str,
    default_provider: Any | None = None,
    verbose: bool = False,
) -> Any:
    """Create an upstream-compatible TaskRunner with per-agent providers."""

    from agentcollabbench.harness.provider import LLMProvider
    from agentcollabbench.harness.runner import TaskRunner

    if not providers and default_provider is None:
        raise ValueError("at least one agent provider or default_provider is required")

    class _RoutingProvider(LLMProvider):
        def __init__(self) -> None:
            self.active_agent_id: str | None = None
            self.calls: list[dict[str, Any]] = []

        def activate(self, agent_id: str) -> None:
            self.active_agent_id = agent_id

        def _active_provider(self) -> Any:
            if self.active_agent_id is None:
                raise RuntimeError("provider router has no active agent")
            provider = providers.get(self.active_agent_id, default_provider)
            if provider is None:
                raise KeyError(
                    f"no AgentCollabBench provider configured for "
                    f"{self.active_agent_id!r}"
                )
            return provider

        def chat(self, messages: list[Any], **kwargs: Any) -> Any:
            provider = self._active_provider()
            response = provider.chat(messages, **kwargs)
            self.calls.append(
                {
                    "agent_id": self.active_agent_id,
                    "provider": provider.provider_name(),
                    "model": response.model,
                    "messages": [
                        {"role": message.role, "content": message.content}
                        for message in messages
                    ],
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                }
            )
            return response

        def provider_name(self) -> str:
            return self._active_provider().provider_name()

    router = _RoutingProvider()

    class _PerAgentTaskRunner(TaskRunner):
        def _system_prompt_for_metric(
            self,
            config: dict[str, Any],
            agent_id: str,
            task: dict[str, Any],
        ) -> str:
            router.activate(agent_id)
            return super()._system_prompt_for_metric(config, agent_id, task)

        def run_task(self, task: dict[str, Any]) -> Any:
            router.calls.clear()
            result = super().run_task(task)
            result.trace["provider_requests"] = list(router.calls)
            result.trace["provider_routing"] = {
                "mode": "per_agent",
                "configured_agents": sorted(providers),
                "has_default": default_provider is not None,
                "upstream_tested_commit": "f016f60",
            }
            return result

    return _PerAgentTaskRunner(provider=router, metric=metric, verbose=verbose)


def evaluate_agentcollab_task(
    task: dict[str, Any],
    providers: dict[str, Any],
    *,
    metric: str,
    metric_config: dict[str, Any] | None = None,
    default_provider: Any | None = None,
    verbose: bool = False,
) -> AgentCollabEvaluation:
    """Run and score one task while retaining the instrumented full result."""

    from agentcollabbench.harness.schema import validate_task
    from agentcollabbench.metrics import CLCMetric, CPRMetric, IDRMetric, RTDMetric

    metric_classes = {
        "rtd": RTDMetric,
        "idr": IDRMetric,
        "cpr": CPRMetric,
        "clc": CLCMetric,
    }
    metric_class = metric_classes.get(metric)
    if metric_class is None:
        raise ValueError(f"unsupported metric {metric!r}")
    validate_task(task)
    config = dict(metric_config or {})
    if metric in {"cpr", "idr"} and not (
        config.get("judge_provider") or config.get("violation_keywords")
    ):
        raise ValueError(
            f"{metric} requires an explicit judge_provider or pre-registered "
            "violation_keywords"
        )
    runner = create_agentcollab_runner(
        providers,
        metric=metric,
        default_provider=default_provider,
        verbose=verbose,
    )
    run_result = runner.run_task(task)
    evaluator = metric_class()
    evaluator.setup(config)
    try:
        score = float(
            evaluator.compute(
                run_result.scenario,
                run_result.output,
                run_result.trace,
            )
        )
        detailed = getattr(evaluator, "get_full_result", lambda: None)()
        if detailed is None:
            detailed_function = getattr(evaluator, "compute_detailed", None)
            if detailed_function is not None:
                detailed = detailed_function(
                    run_result.scenario,
                    run_result.output,
                    run_result.trace,
                )
    finally:
        evaluator.teardown()
    return AgentCollabEvaluation(
        task_id=run_result.task_id,
        metric=metric,
        score=score,
        detailed=detailed,
        run_result=run_result,
    )
