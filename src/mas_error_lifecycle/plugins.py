"""Closed benchmark-plugin contracts for one-assignment execution.

The registry is deliberately immutable.  Configuration may select a plugin
that is already present, but it cannot import code or register a new runner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .design import PlanItem
from .store import TraceBundle


_PLUGIN_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}")


class PluginRegistryError(ValueError):
    """Raised when a closed registry or plugin declaration is invalid."""


class UnknownBenchmarkPlugin(LookupError):
    """Raised when an assignment selects no member of the closed registry."""


@dataclass(frozen=True, slots=True)
class PluginExecutionContext:
    """Non-secret shared context supplied to a benchmark plugin."""

    started_at: str


@dataclass(frozen=True, slots=True)
class RawBenchmarkRun:
    """One JSON-compatible native benchmark result prior to adaptation."""

    payload: Mapping[str, Any]
    schema_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("raw benchmark payload must be a mapping")
        if not isinstance(self.schema_version, str) or not self.schema_version.strip():
            raise ValueError("raw benchmark schema_version must be non-empty")


@runtime_checkable
class BenchmarkPlugin(Protocol):
    """Minimum executable boundary implemented once per benchmark harness."""

    key: str
    version: str
    raw_schema_version: str
    trace_benchmark: str
    allows_network: bool
    supported_plan_versions: frozenset[str]
    supported_factor_bindings: frozenset[str]

    def validate_assignment(self, assignment: PlanItem) -> None:
        """Reject an assignment that this plugin cannot execute faithfully."""

    def run(
        self,
        assignment: PlanItem,
        context: PluginExecutionContext,
    ) -> RawBenchmarkRun:
        """Execute the native harness and return its JSON-compatible raw result."""

    def adapt(
        self,
        raw_run: RawBenchmarkRun,
        assignment: PlanItem,
        context: PluginExecutionContext,
    ) -> TraceBundle:
        """Convert the persisted native result into the canonical trace schema."""


class BenchmarkPluginRegistry:
    """An immutable, duplicate-free set of explicitly constructed plugins."""

    __slots__ = ("_plugins",)

    def __init__(self, plugins: Iterable[BenchmarkPlugin]) -> None:
        resolved: dict[str, BenchmarkPlugin] = {}
        for plugin in plugins:
            self._validate_plugin(plugin)
            if plugin.key in resolved:
                raise PluginRegistryError(
                    f"duplicate benchmark plugin key {plugin.key!r}"
                )
            resolved[plugin.key] = plugin
        self._plugins: Mapping[str, BenchmarkPlugin] = MappingProxyType(resolved)

    @staticmethod
    def _validate_plugin(plugin: BenchmarkPlugin) -> None:
        if not isinstance(plugin, BenchmarkPlugin):
            raise PluginRegistryError(
                "benchmark plugin does not implement the required contract"
            )
        if not isinstance(plugin.key, str) or not _PLUGIN_KEY_PATTERN.fullmatch(
            plugin.key
        ):
            raise PluginRegistryError(
                "benchmark plugin key must match [a-z][a-z0-9_.-]{0,63}"
            )
        for attribute in ("version", "raw_schema_version", "trace_benchmark"):
            value = getattr(plugin, attribute)
            if not isinstance(value, str) or not value.strip():
                raise PluginRegistryError(
                    f"benchmark plugin {attribute} must be a non-empty string"
                )
        if not isinstance(plugin.allows_network, bool):
            raise PluginRegistryError(
                "benchmark plugin allows_network must be boolean"
            )
        if plugin.allows_network:
            raise PluginRegistryError(
                "stage-1 benchmark registry does not accept network-capable plugins"
            )
        for attribute in ("supported_plan_versions", "supported_factor_bindings"):
            values = getattr(plugin, attribute)
            if not isinstance(values, frozenset) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise PluginRegistryError(
                    f"benchmark plugin {attribute} must be a frozenset of "
                    "non-empty strings"
                )
        if not plugin.supported_plan_versions:
            raise PluginRegistryError(
                "benchmark plugin must support at least one plan version"
            )

    def resolve(self, key: str) -> BenchmarkPlugin:
        if not isinstance(key, str) or not _PLUGIN_KEY_PATTERN.fullmatch(key):
            raise UnknownBenchmarkPlugin("assignment benchmark_plugin is invalid")
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise UnknownBenchmarkPlugin(
                f"benchmark plugin {key!r} is not in the closed registry"
            ) from exc

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))


EMPTY_PLUGIN_REGISTRY = BenchmarkPluginRegistry(())


__all__ = [
    "BenchmarkPlugin",
    "BenchmarkPluginRegistry",
    "EMPTY_PLUGIN_REGISTRY",
    "PluginExecutionContext",
    "PluginRegistryError",
    "RawBenchmarkRun",
    "UnknownBenchmarkPlugin",
]
