"""Pinned AgentCollabBench runner shim with per-agent provider routing.

The upstream ``TaskRunner`` accepts one provider for every role. This factory
uses its synchronous call order to select a provider immediately before each
agent call and records the exact request messages. It is tested against upstream
commit ``f016f60``; re-run the offline smoke test when upgrading upstream.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from math import isfinite
from typing import Any


@dataclass(slots=True)
class AgentCollabEvaluation:
    task_id: str
    metric: str
    score: float
    detailed: Any
    run_result: Any
    run_context: dict[str, Any] | None = None
    judge_provenance: dict[str, Any] | None = None

    def to_adapter_payload(self) -> dict[str, Any]:
        """Return a JSON-safe payload accepted by the lifecycle adapter."""

        payload = {
            "task_id": self.task_id,
            "scores": {self.metric: self.score},
            "errors": {},
            "detailed": self.detailed,
            "run_context": self.run_context,
            "judge_provenance": self.judge_provenance,
            "run_result": self.run_result.to_dict(),
        }
        normalized = _to_json_value(payload)
        if not isinstance(normalized, dict):
            raise TypeError("adapter payload normalization must preserve an object")
        return normalized


def _to_json_value(value: Any) -> Any:
    """Normalize upstream result objects without leaking arbitrary repr strings."""

    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    if isinstance(value, Enum):
        return _to_json_value(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _to_json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_to_json_value(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _to_json_value(to_dict())
    return {
        "_non_json_type": f"{type(value).__module__}.{type(value).__qualname__}"
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
            call_index = len(self.calls)
            call_id = f"agentcollab-call-{call_index + 1:05d}"
            started_at = time.time()
            started_monotonic = time.perf_counter()
            record: dict[str, Any] = {
                "call_id": call_id,
                "call_index": call_index,
                "agent_id": self.active_agent_id,
                "provider": provider.provider_name(),
                "model": "unknown",
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
                "sampling": {
                    key: kwargs[key]
                    for key in (
                        "temperature",
                        "top_p",
                        "max_tokens",
                        "max_output_tokens",
                        "seed",
                        "stop",
                    )
                    if key in kwargs
                },
                "request_started_at": started_at,
                "status": "attempted",
            }
            self.calls.append(record)
            try:
                response = provider.chat(messages, **kwargs)
            except Exception as exc:
                record.update(
                    {
                        "status": "error",
                        "response_finished_at": time.time(),
                        "latency_ms": (
                            time.perf_counter() - started_monotonic
                        )
                        * 1000.0,
                        "error_type": type(exc).__name__,
                    }
                )
                raise
            record.update(
                {
                    "status": "success",
                    "response_finished_at": time.time(),
                    "latency_ms": (
                        time.perf_counter() - started_monotonic
                    )
                    * 1000.0,
                    "model": response.model,
                    "response_content": response.content,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "cost_usd": getattr(response, "cost_usd", None),
                    "raw_response_id": getattr(response, "raw_response_id", None),
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
    run_context: dict[str, Any] | None = None,
    judge_provenance: dict[str, Any] | None = None,
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
    if (
        metric in {"cpr", "idr"}
        and run_context
        and run_context.get("analysis_eligible")
        and not judge_provenance
    ):
        raise ValueError(
            "analysis-eligible CPR/IDR run requires calibrated judge_provenance"
        )
    if config.get("violation_keywords") and judge_provenance is None:
        judge_provenance = {
            "scoring_mode": "keyword_smoke_non_native",
            "analysis_eligible": False,
        }
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
        run_context=run_context,
        judge_provenance=judge_provenance,
    )
