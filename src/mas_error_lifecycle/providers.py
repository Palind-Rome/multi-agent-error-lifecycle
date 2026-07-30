"""Provider-neutral request/response contracts.

Real API adapters should implement ``ModelProvider`` without leaking API keys
or vendor-specific response objects into trace files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ModelRequest:
    run_id: str
    agent_id: str
    prompt_id: str
    messages: tuple[ChatMessage, ...]
    temperature: float = 0.0
    max_output_tokens: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ModelResponse:
    content: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float | None = None
    raw_response_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        """Execute one model request."""


class ProviderRouter:
    """Resolve a distinct provider per agent for heterogeneous teams."""

    def __init__(
        self,
        providers: dict[str, ModelProvider],
        *,
        default: ModelProvider | None = None,
    ) -> None:
        self._providers = dict(providers)
        self._default = default

    def complete(self, request: ModelRequest) -> ModelResponse:
        provider = self._providers.get(request.agent_id, self._default)
        if provider is None:
            raise KeyError(
                f"no provider configured for agent {request.agent_id!r}; "
                "set an agent-specific provider or a default"
            )
        return provider.complete(request)

    @property
    def configured_agents(self) -> Sequence[str]:
        return tuple(sorted(self._providers))
