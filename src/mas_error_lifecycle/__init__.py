"""Error-lifecycle instrumentation for LLM multi-agent systems."""

from .metrics import RunMetrics, compute_metrics
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
)
from .store import TraceBundle, TraceValidationError, load_trace, write_trace

__all__ = [
    "AgentSpec",
    "ArtifactRecord",
    "EdgeSpec",
    "EventType",
    "LifecycleEvent",
    "PromptRecord",
    "RunManifest",
    "RunMetrics",
    "RunOutcome",
    "TraceBundle",
    "TraceValidationError",
    "TruthStatus",
    "VerificationVerdict",
    "compute_metrics",
    "load_trace",
    "write_trace",
]

__version__ = "0.1.0"
