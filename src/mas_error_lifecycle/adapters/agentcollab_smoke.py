"""Guarded, single-task AgentCollabBench engineering smoke driver.

This module is deliberately not a run-plan executor.  Its executable allowlist
contains one tracked, untouched AgentCollabBench RTD task, marks the result as
analysis-ineligible, and keeps every raw request/response under the repository's
git-ignored ``outputs/private`` directory.
"""

from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import math
import multiprocessing
import os
import random
import re
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

from .agentcollab_runner import evaluate_agentcollab_task
from .agentcollabbench import convert_agentcollab_result

# This driver imports upstream code only after integrity checks.  Its process and
# spawned HTTP workers must never create importable bytecode beside that code.
sys.dont_write_bytecode = True


PURPOSE = "engineering_smoke"
ANALYSIS_ELIGIBLE = False
TESTED_AGENTCOLLAB_COMMIT = "f016f600568b6d8127dc861e4c83c87b72750d63"
PAPERBYPASS_BASE_URL = "https://aigateway.paperbypass.com/api/v1"
PAPERBYPASS_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"
MIN_INPUT_PRICE_USD_PER_MILLION = Decimal("0.04815")
MIN_OUTPUT_PRICE_USD_PER_MILLION = Decimal("0.19305")
MAX_RESPONSE_BODY_BYTES = 4 * 1024 * 1024
MAX_SELECTED_HEADER_CHARACTERS = 4096
MAX_API_KEY_CHARACTERS = 16 * 1024
_WORKER_STOP_GRACE_SECONDS = 0.1
_API_KEY_INPUT_METHODS = frozenset(
    {"caller_memory", "interactive_getpass", "stdin_single_line"}
)
APPROVED_METRIC = "rtd"
APPROVED_TASK_ID = "TASK-DATAENG-RTD-060"
APPROVED_TASK_FILENAME = "TASK-DATAENG-RTD-060.json"
APPROVED_TASK_SHA256 = (
    "9bb822c2bc1555104fa9ae63c5ee050a1e1b35603396dddc92634e8a609ed92b"
)
PRIVATE_OUTPUT_PARTS = ("outputs", "private")
_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
_MONEY_QUANTUM = Decimal("0.000000000001")


class SmokeConfigurationError(ValueError):
    """Raised before a provider call when a hard gate is not satisfied."""


class BudgetExceeded(RuntimeError):
    """Raised when a call cannot stay within a declared run cap."""


class ProviderRequestError(RuntimeError):
    """Raised for a safe, non-secret-bearing provider failure."""


class SmokeExecutionError(RuntimeError):
    """Safe public error pointing to a durable private ledger."""

    def __init__(self, stage: str, error_type: str, ledger_path: Path):
        self.stage = stage
        self.error_type = error_type
        self.ledger_path = ledger_path
        super().__init__(
            f"AgentCollabBench smoke failed during {stage} ({error_type}); "
            f"see private ledger {ledger_path}"
        )


@dataclass(frozen=True, slots=True)
class ProviderSettings:
    """OpenAI-compatible endpoint settings; the API key is never stored here."""

    base_url: str
    model: str
    temperature: float = 0.0
    request_timeout_seconds: float = 30.0
    send_seed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or self.base_url not in {
            PAPERBYPASS_BASE_URL,
            f"{PAPERBYPASS_BASE_URL}/",
        }:
            raise SmokeConfigurationError(
                "provider.base_url must be exactly the approved PaperBypass API base"
            )
        base_url = self.base_url.rstrip("/")
        if not isinstance(self.model, str) or self.model != PAPERBYPASS_MODEL:
            raise SmokeConfigurationError(
                "provider.model must be exactly the approved pinned model"
            )
        model = self.model
        if not base_url or base_url == "UNSET":
            raise SmokeConfigurationError("provider.base_url must be explicit")
        if not model or model == "UNSET":
            raise SmokeConfigurationError("provider.model must be explicit")
        _validate_base_url(base_url)
        if not math.isfinite(self.temperature) or not 0.0 <= self.temperature <= 2.0:
            raise SmokeConfigurationError(
                "provider.temperature must be finite and between 0 and 2"
            )
        if (
            not math.isfinite(self.request_timeout_seconds)
            or self.request_timeout_seconds <= 0
        ):
            raise SmokeConfigurationError(
                "provider.request_timeout_seconds must be positive and finite"
            )
        if not isinstance(self.send_seed, bool):
            raise SmokeConfigurationError("provider.send_seed must be boolean")
        object.__setattr__(self, "base_url", base_url)
        object.__setattr__(self, "model", model)

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """Positive per-run caps plus conservative configured pricing ceilings."""

    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_output_tokens_per_call: int
    max_wall_seconds: float
    max_cost_usd: Decimal
    max_input_cost_usd_per_million_tokens: Decimal
    max_output_cost_usd_per_million_tokens: Decimal

    def __post_init__(self) -> None:
        for name in (
            "max_calls",
            "max_input_tokens",
            "max_output_tokens",
            "max_output_tokens_per_call",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise SmokeConfigurationError(f"limits.{name} must be a positive integer")
        if self.max_output_tokens_per_call > self.max_output_tokens:
            raise SmokeConfigurationError(
                "limits.max_output_tokens_per_call cannot exceed max_output_tokens"
            )
        if not math.isfinite(self.max_wall_seconds) or self.max_wall_seconds <= 0:
            raise SmokeConfigurationError(
                "limits.max_wall_seconds must be positive and finite"
            )
        for name in (
            "max_cost_usd",
            "max_input_cost_usd_per_million_tokens",
            "max_output_cost_usd_per_million_tokens",
        ):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise SmokeConfigurationError(
                    f"limits.{name} must be a positive finite decimal"
                )
        if (
            self.max_input_cost_usd_per_million_tokens
            < MIN_INPUT_PRICE_USD_PER_MILLION
        ):
            raise SmokeConfigurationError(
                "limits.max_input_cost_usd_per_million_tokens is below the "
                "approved price floor"
            )
        if (
            self.max_output_cost_usd_per_million_tokens
            < MIN_OUTPUT_PRICE_USD_PER_MILLION
        ):
            raise SmokeConfigurationError(
                "limits.max_output_cost_usd_per_million_tokens is below the "
                "approved price floor"
            )


@dataclass(frozen=True, slots=True)
class SmokeSettings:
    provider: ProviderSettings
    limits: BudgetLimits


@dataclass(frozen=True, slots=True)
class HTTPResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class SmokeLLMResponse:
    """Duck-typed AgentCollabBench ``LLMResponse`` with cost provenance."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    raw_response_id: str | None = None


@dataclass(frozen=True, slots=True)
class CallReservation:
    call_index: int
    call_id: str
    estimated_input_tokens: int
    max_output_tokens: int
    timeout_seconds: float
    estimated_max_cost_usd: Decimal


@dataclass(frozen=True, slots=True)
class SettledCall:
    accounted_cost_usd: Decimal
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class SmokeRunResult:
    run_id: str
    task_id: str
    metric: str
    diagnostic_score: float
    run_directory: Path
    ledger_path: Path
    raw_result_path: Path
    trace_path: Path


Transport = Callable[[str, Mapping[str, str], bytes, float], HTTPResult]


def read_api_key_from_user_input(
    *,
    use_stdin: bool,
    stdin: Any | None = None,
) -> tuple[str, str]:
    """Read a key from hidden input or one non-TTY stdin line, never the env."""

    _assert_api_key_not_in_environment()
    if use_stdin:
        source = sys.stdin if stdin is None else stdin
        isatty = getattr(source, "isatty", None)
        if callable(isatty) and isatty():
            raise SmokeConfigurationError(
                "--api-key-stdin requires non-TTY stdin; omit it for hidden input"
            )
        value = source.readline(MAX_API_KEY_CHARACTERS + 2)
        input_method = "stdin_single_line"
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("PaperBypass API key: ")
        except (EOFError, getpass.GetPassWarning) as exc:
            raise SmokeConfigurationError(
                "hidden API-key input is unavailable; pipe one line with "
                "--api-key-stdin"
            ) from exc
        input_method = "interactive_getpass"

    if not isinstance(value, str):
        raise SmokeConfigurationError("PaperBypass API key must be text")
    if len(value) > MAX_API_KEY_CHARACTERS + 1:
        raise SmokeConfigurationError("PaperBypass API key input is too long")
    if value.endswith("\n"):
        value = value[:-1]
        if value.endswith("\r"):
            value = value[:-1]
    return _validate_api_key(value), input_method


def _validate_api_key(value: str) -> str:
    if not value or value != value.strip() or "\n" in value or "\r" in value:
        raise SmokeConfigurationError(
            "PaperBypass API key has invalid whitespace or line breaks"
        )
    if len(value) > MAX_API_KEY_CHARACTERS:
        raise SmokeConfigurationError("PaperBypass API key input is too long")
    return value


def _assert_api_key_not_in_environment() -> None:
    if "PAPERBYPASS_API_KEY" in os.environ:
        raise SmokeConfigurationError(
            "PAPERBYPASS_API_KEY must be absent from the initial process "
            "environment; use hidden input or --api-key-stdin"
        )


def load_smoke_settings(
    *,
    repository_root: Path,
    config_path: Path | None,
    overrides: Mapping[str, Any],
) -> SmokeSettings:
    """Load a git-ignored local TOML and apply explicit CLI overrides."""

    raw: dict[str, dict[str, Any]] = {"provider": {}, "limits": {}}
    if config_path is not None:
        _assert_local_config_is_untracked(config_path, repository_root)
        with config_path.open("rb") as handle:
            parsed = tomllib.load(handle)
        if not isinstance(parsed, dict):
            raise SmokeConfigurationError("local config must be a TOML table")
        unexpected_sections = set(parsed) - {"provider", "limits"}
        if unexpected_sections:
            raise SmokeConfigurationError(
                "unsupported local config section(s): "
                + ", ".join(sorted(unexpected_sections))
            )
        for section in ("provider", "limits"):
            value = parsed.get(section, {})
            if not isinstance(value, dict):
                raise SmokeConfigurationError(f"[{section}] must be a TOML table")
            raw[section].update(value)

    provider_keys = {
        "base_url",
        "model",
        "temperature",
        "request_timeout_seconds",
        "send_seed",
    }
    limit_keys = {
        "max_calls",
        "max_input_tokens",
        "max_output_tokens",
        "max_output_tokens_per_call",
        "max_wall_seconds",
        "max_cost_usd",
        "max_input_cost_usd_per_million_tokens",
        "max_output_cost_usd_per_million_tokens",
    }
    unexpected_provider = set(raw["provider"]) - provider_keys
    unexpected_limits = set(raw["limits"]) - limit_keys
    if unexpected_provider or unexpected_limits:
        names = sorted(unexpected_provider | unexpected_limits)
        raise SmokeConfigurationError(
            "unsupported local config key(s): " + ", ".join(names)
        )

    for key, value in overrides.items():
        if value is None:
            continue
        if key in provider_keys:
            raw["provider"][key] = value
        elif key in limit_keys:
            raw["limits"][key] = value
        else:
            raise SmokeConfigurationError(f"unsupported CLI override {key!r}")

    missing = [
        f"provider.{key}"
        for key in ("base_url", "model")
        if key not in raw["provider"]
    ]
    missing.extend(
        f"limits.{key}" for key in sorted(limit_keys) if key not in raw["limits"]
    )
    if missing:
        raise SmokeConfigurationError(
            "missing explicit smoke setting(s): " + ", ".join(missing)
        )

    provider = ProviderSettings(
        base_url=str(raw["provider"]["base_url"]),
        model=str(raw["provider"]["model"]),
        temperature=float(raw["provider"].get("temperature", 0.0)),
        request_timeout_seconds=float(
            raw["provider"].get("request_timeout_seconds", 30.0)
        ),
        send_seed=_strict_bool(raw["provider"].get("send_seed", False), "send_seed"),
    )
    limits = BudgetLimits(
        max_calls=_strict_int(raw["limits"]["max_calls"], "max_calls"),
        max_input_tokens=_strict_int(
            raw["limits"]["max_input_tokens"], "max_input_tokens"
        ),
        max_output_tokens=_strict_int(
            raw["limits"]["max_output_tokens"], "max_output_tokens"
        ),
        max_output_tokens_per_call=_strict_int(
            raw["limits"]["max_output_tokens_per_call"],
            "max_output_tokens_per_call",
        ),
        max_wall_seconds=float(raw["limits"]["max_wall_seconds"]),
        max_cost_usd=_decimal(raw["limits"]["max_cost_usd"], "max_cost_usd"),
        max_input_cost_usd_per_million_tokens=_decimal(
            raw["limits"]["max_input_cost_usd_per_million_tokens"],
            "max_input_cost_usd_per_million_tokens",
        ),
        max_output_cost_usd_per_million_tokens=_decimal(
            raw["limits"]["max_output_cost_usd_per_million_tokens"],
            "max_output_cost_usd_per_million_tokens",
        ),
    )
    return SmokeSettings(provider=provider, limits=limits)


class PrivateRunStore:
    """Atomic, mode-0600 persistence rooted at ``outputs/private/<run_id>``."""

    def __init__(self, run_directory: Path, secret: str):
        self.run_directory = run_directory
        self._secret = secret

    @classmethod
    def create(
        cls,
        repository_root: Path,
        run_id: str,
        secret: str,
    ) -> PrivateRunStore:
        if not secret:
            raise SmokeConfigurationError("API key must be non-empty")
        if not _RUN_ID_PATTERN.fullmatch(run_id):
            raise SmokeConfigurationError(
                "run_id must contain only letters, digits, '.', '_' or '-'"
            )
        root = repository_root.resolve()
        outputs = root / PRIVATE_OUTPUT_PARTS[0]
        private_root = outputs / PRIVATE_OUTPUT_PARTS[1]
        for candidate in (outputs, private_root):
            if candidate.is_symlink():
                raise SmokeConfigurationError(
                    f"private output boundary cannot be a symlink: {candidate}"
                )
        private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if private_root.resolve() != private_root:
            raise SmokeConfigurationError(
                "outputs/private resolves outside its literal repository path"
            )
        os.chmod(private_root, 0o700)
        if (root / ".git").exists():
            ignored = _run_git(
                root,
                ["check-ignore", "--quiet", "--", "outputs/private/probe"],
            )
            if ignored.returncode != 0:
                raise SmokeConfigurationError(
                    "outputs/private must be git-ignored before a smoke run"
                )
        run_directory = private_root / run_id
        try:
            run_directory.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise SmokeConfigurationError(
                f"private run directory already exists: {run_directory}"
            ) from exc
        (run_directory / "raw").mkdir(mode=0o700)
        return cls(run_directory, secret)

    def write_json(
        self,
        relative_path: str,
        value: Any,
        *,
        overwrite: bool = False,
    ) -> Path:
        redacted = _redact_value(value, self._secret)
        rendered = json.dumps(
            redacted,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        return self.write_text(relative_path, rendered + "\n", overwrite=overwrite)

    def write_text(
        self,
        relative_path: str,
        value: str,
        *,
        overwrite: bool = False,
    ) -> Path:
        destination = self._destination(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe_value = value.replace(self._secret, "[REDACTED]")
        _atomic_write_private(destination, safe_value, overwrite=overwrite)
        return destination

    def _destination(self, relative_path: str) -> Path:
        candidate = self.run_directory / relative_path
        resolved_parent = candidate.parent.resolve()
        try:
            resolved_parent.relative_to(self.run_directory.resolve())
        except ValueError as exc:
            raise SmokeConfigurationError(
                "private artifact path escapes the run directory"
            ) from exc
        return candidate


class RunLedger:
    """Durable run/call state rewritten atomically at every boundary."""

    def __init__(
        self,
        store: PrivateRunStore,
        *,
        run_id: str,
        task_id: str,
        metric: str,
        native_task_sha256: str,
        upstream_commit: str,
        settings: SmokeSettings,
        seed: int,
        api_key_input_method: str = "caller_memory",
    ) -> None:
        if api_key_input_method not in _API_KEY_INPUT_METHODS:
            raise SmokeConfigurationError("invalid API-key input method label")
        self.store = store
        self.path = store.run_directory / "failure-ledger.json"
        self.document: dict[str, Any] = {
            "schema_version": "agentcollab-engineering-smoke-ledger/2",
            "run_id": run_id,
            "task_id": task_id,
            "metric": metric,
            "purpose": PURPOSE,
            "analysis_eligible": ANALYSIS_ELIGIBLE,
            "native_task_sha256": native_task_sha256,
            "upstream_commit": upstream_commit,
            "python_injection_seed": seed,
            "provider_seed_sent": settings.provider.send_seed,
            "provider": {
                "kind": "openai-compatible",
                "base_url": settings.provider.base_url,
                "model": settings.provider.model,
                "api_key_input_method": api_key_input_method,
                "api_key_persisted": False,
            },
            "limits": _limits_dict(settings.limits),
            "status": "initialized",
            "stage": "initialized",
            "calls": [],
            "budget": {},
            "failure": None,
            "artifacts": {},
            "updated_at": _utc_now(),
        }
        self._flush()

    def mark_running(self, budget: BudgetGate) -> None:
        self.document["status"] = "running"
        self.document["stage"] = "provider_execution"
        self.document["budget"] = budget.snapshot()
        self._flush()

    def call_started(
        self,
        reservation: CallReservation,
        request_path: Path,
        budget: BudgetGate,
    ) -> None:
        self.document["calls"].append(
            {
                "call_index": reservation.call_index,
                "call_id": reservation.call_id,
                "status": "started",
                "request_path": request_path.relative_to(
                    self.store.run_directory
                ).as_posix(),
                "response_path": None,
                "estimated_input_tokens": reservation.estimated_input_tokens,
                "max_output_tokens": reservation.max_output_tokens,
                "timeout_seconds": reservation.timeout_seconds,
                "estimated_max_cost_usd": _money(
                    reservation.estimated_max_cost_usd
                ),
                "started_at": _utc_now(),
                "finished_at": None,
                "error_type": None,
            }
        )
        self.document["budget"] = budget.snapshot()
        self._flush()

    def call_succeeded(
        self,
        reservation: CallReservation,
        response_path: Path,
        settled: SettledCall,
        budget: BudgetGate,
    ) -> None:
        call = self._call(reservation.call_index)
        call.update(
            {
                "status": "success",
                "response_path": response_path.relative_to(
                    self.store.run_directory
                ).as_posix(),
                "input_tokens": settled.input_tokens,
                "output_tokens": settled.output_tokens,
                "accounted_cost_usd": _money(settled.accounted_cost_usd),
                "finished_at": _utc_now(),
            }
        )
        self.document["budget"] = budget.snapshot()
        self._flush()

    def call_failed(
        self,
        reservation: CallReservation,
        *,
        error_type: str,
        response_path: Path | None,
        budget: BudgetGate,
    ) -> None:
        call = self._call(reservation.call_index)
        call.update(
            {
                "status": "failed",
                "response_path": (
                    response_path.relative_to(self.store.run_directory).as_posix()
                    if response_path is not None
                    else None
                ),
                "error_type": error_type,
                "finished_at": _utc_now(),
            }
        )
        self.document["status"] = "provider_failed"
        self.document["stage"] = "provider_execution"
        self.document["budget"] = budget.snapshot()
        self.document["failure"] = {
            "stage": "provider_execution",
            "error_type": error_type,
            "recorded_at": _utc_now(),
        }
        self._flush()

    def mark_failed(self, stage: str, error_type: str, budget: BudgetGate) -> None:
        self.document["status"] = "failed"
        self.document["stage"] = stage
        self.document["budget"] = budget.snapshot()
        prior = self.document.get("failure")
        self.document["failure"] = {
            "stage": stage,
            "error_type": error_type,
            "recorded_at": _utc_now(),
            "provider_failure_recorded": bool(prior),
        }
        self._flush()

    def mark_completed(
        self,
        *,
        raw_result_path: Path,
        trace_path: Path,
        budget: BudgetGate,
    ) -> None:
        self.document["status"] = "completed"
        self.document["stage"] = "completed"
        self.document["budget"] = budget.snapshot()
        self.document["failure"] = None
        self.document["artifacts"] = {
            "raw_result": raw_result_path.relative_to(
                self.store.run_directory
            ).as_posix(),
            "lifecycle_trace": trace_path.relative_to(
                self.store.run_directory
            ).as_posix(),
        }
        self._flush()

    def _call(self, call_index: int) -> dict[str, Any]:
        for call in self.document["calls"]:
            if call["call_index"] == call_index:
                return call
        raise RuntimeError(f"ledger is missing call index {call_index}")

    def _flush(self) -> None:
        self.document["updated_at"] = _utc_now()
        self.store.write_json("failure-ledger.json", self.document, overwrite=True)


class BudgetGate:
    """Sequential hard gate for calls, tokens, wall time, and bounded cost."""

    def __init__(
        self,
        limits: BudgetLimits,
        *,
        started_monotonic: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits
        self._monotonic = monotonic
        self._started = monotonic() if started_monotonic is None else started_monotonic
        self.calls_started = 0
        self.calls_completed = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.accounted_cost_usd = Decimal("0")
        self.unreconciled_calls = 0

    def reserve(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        requested_max_output_tokens: int | None,
        request_timeout_seconds: float,
    ) -> CallReservation:
        remaining_wall = self.remaining_wall_seconds()
        if remaining_wall <= 0:
            raise BudgetExceeded("max_wall_seconds reached before provider call")
        if self.calls_started >= self.limits.max_calls:
            raise BudgetExceeded("max_calls reached before provider call")

        estimated_input = conservative_input_token_bound(messages)
        if self.input_tokens + estimated_input > self.limits.max_input_tokens:
            raise BudgetExceeded(
                "conservative input-token bound would exceed max_input_tokens"
            )
        remaining_output = self.limits.max_output_tokens - self.output_tokens
        if remaining_output <= 0:
            raise BudgetExceeded("max_output_tokens reached before provider call")

        requested = (
            self.limits.max_output_tokens_per_call
            if requested_max_output_tokens is None
            else requested_max_output_tokens
        )
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise BudgetExceeded("requested max output tokens must be positive")
        candidate_output = min(
            requested,
            remaining_output,
            self.limits.max_output_tokens_per_call,
        )
        input_cost = _token_cost(
            estimated_input,
            self.limits.max_input_cost_usd_per_million_tokens,
        )
        remaining_cost = self.limits.max_cost_usd - self.accounted_cost_usd
        affordable = remaining_cost - input_cost
        if affordable <= 0:
            raise BudgetExceeded(
                "configured input-cost ceiling would exceed max_cost_usd"
            )
        output_price = self.limits.max_output_cost_usd_per_million_tokens
        affordable_output = int(
            (
                affordable * Decimal(1_000_000) / output_price
            ).to_integral_value(rounding=ROUND_FLOOR)
        )
        allowed_output = min(candidate_output, affordable_output)
        if allowed_output <= 0:
            raise BudgetExceeded(
                "configured output-cost ceiling leaves no token under max_cost_usd"
            )

        self.calls_started += 1
        call_index = self.calls_started
        estimated_max_cost = input_cost + _token_cost(allowed_output, output_price)
        return CallReservation(
            call_index=call_index,
            call_id=f"openai-compatible-{call_index:05d}",
            estimated_input_tokens=estimated_input,
            max_output_tokens=allowed_output,
            timeout_seconds=min(request_timeout_seconds, remaining_wall),
            estimated_max_cost_usd=estimated_max_cost,
        )

    def settle(
        self,
        reservation: CallReservation,
        *,
        input_tokens: int,
        output_tokens: int,
        known_cost_usd: Decimal | None,
    ) -> SettledCall:
        for name, value in (
            ("input_tokens", input_tokens),
            ("output_tokens", output_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                self.abandon(reservation)
                raise BudgetExceeded(f"provider returned invalid {name} usage")

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        estimated_cost = _token_cost(
            input_tokens,
            self.limits.max_input_cost_usd_per_million_tokens,
        ) + _token_cost(
            output_tokens,
            self.limits.max_output_cost_usd_per_million_tokens,
        )
        accounted = (
            max(estimated_cost, known_cost_usd)
            if known_cost_usd is not None
            else estimated_cost
        )
        self.accounted_cost_usd += accounted
        self.calls_completed += 1

        failures: list[str] = []
        if input_tokens > reservation.estimated_input_tokens:
            failures.append("provider input usage exceeded conservative pre-call bound")
        if output_tokens > reservation.max_output_tokens:
            failures.append("provider output usage exceeded requested max_tokens")
        if self.input_tokens > self.limits.max_input_tokens:
            failures.append("max_input_tokens exceeded")
        if self.output_tokens > self.limits.max_output_tokens:
            failures.append("max_output_tokens exceeded")
        if self.accounted_cost_usd > self.limits.max_cost_usd:
            failures.append("max_cost_usd exceeded")
        if self.remaining_wall_seconds() < 0:
            failures.append("max_wall_seconds exceeded")
        if failures:
            raise BudgetExceeded("; ".join(failures))
        return SettledCall(
            accounted_cost_usd=accounted,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def abandon(self, reservation: CallReservation) -> None:
        """Account a failed call at its pre-reserved ceiling when usage is unknown."""

        self.accounted_cost_usd += reservation.estimated_max_cost_usd
        self.unreconciled_calls += 1

    def assert_runtime(self) -> None:
        if self.remaining_wall_seconds() < 0:
            raise BudgetExceeded("max_wall_seconds exceeded")

    def remaining_wall_seconds(self) -> float:
        elapsed = self._monotonic() - self._started
        return self.limits.max_wall_seconds - elapsed

    def snapshot(self) -> dict[str, Any]:
        elapsed = max(0.0, self._monotonic() - self._started)
        return {
            "calls_started": self.calls_started,
            "calls_completed": self.calls_completed,
            "unreconciled_calls": self.unreconciled_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "accounted_cost_usd": _money(self.accounted_cost_usd),
            "cost_basis": (
                "max(configured token-price ceilings, provider-known cost when present)"
            ),
            "elapsed_wall_seconds": round(elapsed, 6),
            "limits": _limits_dict(self.limits),
        }


class OpenAICompatibleSmokeProvider:
    """Minimal chat-completions provider with private raw persistence."""

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        api_key: str,
        budget: BudgetGate,
        store: PrivateRunStore,
        ledger: RunLedger,
        transport: Transport | None = None,
        seed: int = 7,
    ) -> None:
        if not isinstance(api_key, str):
            raise SmokeConfigurationError("PaperBypass API key must be text")
        _validate_api_key(api_key)
        self._settings = settings
        self._api_key = api_key
        self._budget = budget
        self._store = store
        self._ledger = ledger
        # Test transports remain directly injectable.  The real urllib path is
        # always isolated so DNS, connect, TLS, and response headers share one
        # parent-enforced deadline and can be forcibly stopped.
        self._transport = (
            transport if transport is not None else _process_bounded_urllib_transport
        )
        self._seed = seed

    def provider_name(self) -> str:
        return "openai-compatible"

    def chat(self, messages: list[Any], **kwargs: Any) -> SmokeLLMResponse:
        normalized_messages = [
            {
                "role": str(getattr(message, "role")),
                "content": str(getattr(message, "content")),
            }
            for message in messages
        ]
        requested_max = kwargs.get("max_tokens", kwargs.get("max_output_tokens"))
        reservation = self._budget.reserve(
            normalized_messages,
            requested_max_output_tokens=requested_max,
            request_timeout_seconds=self._settings.request_timeout_seconds,
        )
        payload = {
            "model": self._settings.model,
            "messages": normalized_messages,
            "temperature": self._settings.temperature,
            "max_tokens": reservation.max_output_tokens,
        }
        if self._settings.send_seed:
            payload["seed"] = self._seed
        request_path = self._store.write_json(
            f"raw/{reservation.call_id}.request.json",
            {
                "call_id": reservation.call_id,
                "endpoint": self._settings.endpoint,
                "authorization_persisted": False,
                "body": payload,
            },
        )
        self._ledger.call_started(reservation, request_path, self._budget)

        response_path: Path | None = None
        budget_accounted = False
        try:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            result = self._transport(
                self._settings.endpoint,
                {
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                encoded,
                reservation.timeout_seconds,
            )
            raw_text = result.body.decode("utf-8", errors="replace")
            response_path = self._store.write_json(
                f"raw/{reservation.call_id}.response.json",
                {
                    "call_id": reservation.call_id,
                    "http_status": result.status,
                    "headers": {
                        str(key): str(value) for key, value in result.headers.items()
                    },
                    "body_text": raw_text,
                },
            )
            if not 200 <= result.status < 300:
                self._budget.abandon(reservation)
                budget_accounted = True
                raise ProviderRequestError(
                    f"OpenAI-compatible provider returned HTTP {result.status}"
                )
            parsed = json.loads(raw_text)
            content, model, input_tokens, output_tokens, response_id, known_cost = (
                _parse_chat_completion(parsed, self._settings.model)
            )
            budget_accounted = True
            settled = self._budget.settle(
                reservation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                known_cost_usd=known_cost,
            )
        except Exception as exc:
            if not budget_accounted:
                self._budget.abandon(reservation)
                budget_accounted = True
            if not isinstance(exc, ProviderRequestError | BudgetExceeded):
                safe_exc: Exception = ProviderRequestError(
                    "OpenAI-compatible provider request or response failed"
                )
            else:
                safe_exc = exc
            self._ledger.call_failed(
                reservation,
                error_type=type(safe_exc).__name__,
                response_path=response_path,
                budget=self._budget,
            )
            raise safe_exc from exc

        self._ledger.call_succeeded(
            reservation,
            response_path,
            settled,
            self._budget,
        )
        return SmokeLLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=float(settled.accounted_cost_usd),
            raw_response_id=response_id,
        )


def run_single_agentcollab_smoke(
    *,
    repository_root: Path,
    agentcollab_repository: Path,
    task_file: Path,
    expected_task_id: str,
    metric: str,
    settings: SmokeSettings,
    api_key: str,
    api_key_input_method: str = "caller_memory",
    seed: int = 7,
    run_id: str | None = None,
    transport: Transport | None = None,
) -> SmokeRunResult:
    """Execute the one allowlisted native RTD task and persist a private trace."""

    _assert_api_key_not_in_environment()
    if api_key_input_method not in _API_KEY_INPUT_METHODS:
        raise SmokeConfigurationError("invalid API-key input method label")
    if not isinstance(api_key, str):
        raise SmokeConfigurationError("PaperBypass API key must be text")
    _validate_api_key(api_key)
    sys.dont_write_bytecode = True
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise SmokeConfigurationError("seed must be an integer in [0, 2^31)")
    upstream_commit = verify_agentcollab_repository(agentcollab_repository)
    task, task_bytes_sha256 = load_untouched_native_task(
        agentcollab_repository,
        task_file,
        expected_task_id=expected_task_id,
        metric=metric,
    )
    expected_calls = expected_agentcollab_calls(task, metric=metric)
    if expected_calls > settings.limits.max_calls:
        raise SmokeConfigurationError(
            f"task requires {expected_calls} calls but max_calls is "
            f"{settings.limits.max_calls}"
        )
    if settings.limits.max_output_tokens < expected_calls:
        raise SmokeConfigurationError(
            "max_output_tokens must allow at least one token per expected call"
        )

    resolved_run_id = run_id or _new_run_id(expected_task_id)
    store = PrivateRunStore.create(repository_root, resolved_run_id, api_key)
    budget = BudgetGate(settings.limits)
    ledger = RunLedger(
        store,
        run_id=resolved_run_id,
        task_id=expected_task_id,
        metric=metric,
        native_task_sha256=task_bytes_sha256,
        upstream_commit=upstream_commit,
        settings=settings,
        seed=seed,
        api_key_input_method=api_key_input_method,
    )
    ledger.mark_running(budget)
    provider = OpenAICompatibleSmokeProvider(
        settings.provider,
        api_key=api_key,
        budget=budget,
        store=store,
        ledger=ledger,
        transport=transport,
        seed=seed,
    )
    stage = "provider_execution"
    try:
        _activate_agentcollab_repository(agentcollab_repository)
        agent_ids = [
            str(agent["agent_id"])
            for agent in task["topology"]["agents"]
        ]
        metric_config: dict[str, Any] = {}
        if metric == "cpr":
            false_fact = str(task["injections"]["cpr"]["false_fact"])
            metric_config["violation_keywords"] = [false_fact]
        random_state = random.getstate()
        random.seed(seed)
        try:
            evaluation = evaluate_agentcollab_task(
                copy.deepcopy(task),
                {agent_id: provider for agent_id in agent_ids},
                metric=metric,
                metric_config=metric_config,
                run_context={
                    "run_id": resolved_run_id,
                    "purpose": PURPOSE,
                    "analysis_eligible": ANALYSIS_ELIGIBLE,
                    "protocol_kind": "agentcollab_native_observational",
                    "condition_id": "engineering-smoke-only",
                    "cluster_id": expected_task_id,
                    "review_status": "native",
                    "native_task_hash": task_bytes_sha256,
                    "upstream_commit": upstream_commit,
                    "seed": seed,
                    "provider_seed_sent": settings.provider.send_seed,
                },
            )
        finally:
            random.setstate(random_state)
        budget.assert_runtime()

        stage = "completion_reconciliation"
        provider_requests = evaluation.run_result.trace.get("provider_requests")
        if not isinstance(provider_requests, list):
            raise SmokeConfigurationError(
                "upstream result is missing provider_requests"
            )
        if not (
            budget.calls_started
            == budget.calls_completed
            == len(provider_requests)
            == expected_calls
        ):
            raise SmokeConfigurationError(
                "completed call/provider-request counts do not match expected calls"
            )

        stage = "untouched_task_verification"
        scenario = evaluation.run_result.to_dict().get("scenario")
        if _canonical_sha256(scenario) != _canonical_sha256(task):
            raise SmokeConfigurationError(
                "upstream execution changed the native task scenario"
            )

        stage = "raw_result_persistence"
        payload = evaluation.to_adapter_payload()
        raw_result_path = store.write_json("raw/agentcollab-result.json", payload)

        stage = "lifecycle_conversion"
        bundle = convert_agentcollab_result(payload)
        if bundle.manifest.purpose != PURPOSE or bundle.manifest.analysis_eligible:
            raise SmokeConfigurationError(
                "lifecycle adapter did not preserve engineering smoke eligibility gates"
            )
        trace_lines = "".join(
            json.dumps(
                record.to_dict(),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
            for record in bundle.records()
        )
        trace_path = store.write_text("lifecycle-trace.jsonl", trace_lines)
        budget.assert_runtime()
        ledger.mark_completed(
            raw_result_path=raw_result_path,
            trace_path=trace_path,
            budget=budget,
        )
    except Exception as exc:
        ledger.mark_failed(stage, type(exc).__name__, budget)
        raise SmokeExecutionError(stage, type(exc).__name__, ledger.path) from exc

    return SmokeRunResult(
        run_id=resolved_run_id,
        task_id=expected_task_id,
        metric=metric,
        diagnostic_score=evaluation.score,
        run_directory=store.run_directory,
        ledger_path=ledger.path,
        raw_result_path=raw_result_path,
        trace_path=trace_path,
    )


def verify_agentcollab_repository(repository: Path) -> str:
    """Require the exact clean upstream implementation tested by the adapter."""

    resolved = repository.resolve()
    if not (resolved / "agentcollabbench" / "harness" / "runner.py").is_file():
        raise SmokeConfigurationError(
            "agentcollab repository does not contain the expected Python package"
        )
    top_level = _git_output(resolved, ["rev-parse", "--show-toplevel"]).strip()
    if not top_level or Path(top_level).resolve() != resolved:
        raise SmokeConfigurationError(
            "AgentCollabBench git top-level does not match the requested checkout"
        )
    object_format = _git_output(
        resolved, ["rev-parse", "--show-object-format"]
    ).strip()
    if object_format != "sha1":
        raise SmokeConfigurationError(
            "AgentCollabBench checkout must use the sha1 Git object format"
        )
    head = _git_output(resolved, ["rev-parse", "HEAD"]).strip()
    if head != TESTED_AGENTCOLLAB_COMMIT:
        raise SmokeConfigurationError(
            "AgentCollabBench checkout is not the tested pinned commit "
            f"{TESTED_AGENTCOLLAB_COMMIT}"
        )
    status = _git_output(
        resolved,
        [
            "status",
            "--porcelain",
            "--ignored",
            "--untracked-files=all",
        ],
    )
    if status.strip():
        raise SmokeConfigurationError(
            "AgentCollabBench checkout contains modified, untracked, or "
            "ignored files"
        )
    tree = _run_git_bytes(
        resolved,
        ["ls-tree", "-rz", "--full-tree", "HEAD"],
    )
    if tree.returncode != 0:
        raise SmokeConfigurationError(
            "unable to read the pinned AgentCollabBench HEAD tree"
        )
    _verify_raw_head_tree(resolved, tree.stdout)
    return head


def _verify_raw_head_tree(repository: Path, listing: bytes) -> None:
    """Compare worktree bytes to HEAD blobs without index or filter semantics."""

    if not listing or not listing.endswith(b"\0"):
        raise SmokeConfigurationError(
            "AgentCollabBench HEAD tree listing is malformed"
        )
    root = os.fsencode(repository)
    seen_paths: set[bytes] = set()
    checked_directories: set[bytes] = {root}
    for record in listing[:-1].split(b"\0"):
        metadata, separator, relative_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if (
            separator != b"\t"
            or len(fields) != 3
            or not relative_path
            or relative_path in seen_paths
        ):
            raise SmokeConfigurationError(
                "AgentCollabBench HEAD tree listing is malformed"
            )
        mode, object_type, expected_oid = fields
        if (
            object_type != b"blob"
            or mode not in {b"100644", b"100755", b"120000"}
            or len(expected_oid) != 40
            or any(character not in b"0123456789abcdef" for character in expected_oid)
        ):
            raise SmokeConfigurationError(
                "AgentCollabBench HEAD tree has an unsupported entry"
            )
        components = relative_path.split(b"/")
        if (
            relative_path.startswith(b"/")
            or any(component in {b"", b".", b".."} for component in components)
        ):
            raise SmokeConfigurationError(
                "AgentCollabBench HEAD tree contains an unsafe path"
            )
        seen_paths.add(relative_path)
        candidate = root
        for component in components[:-1]:
            candidate = os.path.join(candidate, component)
            if candidate not in checked_directories:
                try:
                    directory_stat = os.lstat(candidate)
                except OSError as exc:
                    raise SmokeConfigurationError(
                        "AgentCollabBench worktree does not match pinned HEAD"
                    ) from exc
                if not stat.S_ISDIR(directory_stat.st_mode):
                    raise SmokeConfigurationError(
                        "AgentCollabBench worktree does not match pinned HEAD"
                    )
                checked_directories.add(candidate)
        candidate = os.path.join(candidate, components[-1])
        actual_oid = _raw_worktree_blob_oid(candidate, mode)
        if actual_oid != expected_oid.decode("ascii"):
            raise SmokeConfigurationError(
                "AgentCollabBench raw worktree bytes do not match pinned HEAD"
            )


def _raw_worktree_blob_oid(path: bytes, expected_mode: bytes) -> str:
    try:
        entry_stat = os.lstat(path)
    except OSError as exc:
        raise SmokeConfigurationError(
            "AgentCollabBench worktree does not match pinned HEAD"
        ) from exc

    if expected_mode == b"120000":
        if not stat.S_ISLNK(entry_stat.st_mode):
            raise SmokeConfigurationError(
                "AgentCollabBench worktree does not match pinned HEAD"
            )
        try:
            target = os.readlink(path)
        except OSError as exc:
            raise SmokeConfigurationError(
                "AgentCollabBench worktree does not match pinned HEAD"
            ) from exc
        return _git_blob_oid((target,))

    if not stat.S_ISREG(entry_stat.st_mode):
        raise SmokeConfigurationError(
            "AgentCollabBench worktree does not match pinned HEAD"
        )
    expected_executable = expected_mode == b"100755"
    actual_executable = bool(entry_stat.st_mode & 0o111)
    if actual_executable != expected_executable:
        raise SmokeConfigurationError(
            "AgentCollabBench worktree mode does not match pinned HEAD"
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SmokeConfigurationError(
            "AgentCollabBench worktree does not match pinned HEAD"
        ) from exc
    try:
        opened_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_size != entry_stat.st_size
            or opened_stat.st_ino != entry_stat.st_ino
            or opened_stat.st_dev != entry_stat.st_dev
            or bool(opened_stat.st_mode & 0o111) != expected_executable
        ):
            raise SmokeConfigurationError(
                "AgentCollabBench worktree changed during integrity verification"
            )
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            digest = _new_git_sha1()
            digest.update(
                b"blob " + str(opened_stat.st_size).encode("ascii") + b"\0"
            )
            bytes_read = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                bytes_read += len(chunk)
                digest.update(chunk)
        if bytes_read != opened_stat.st_size:
            raise SmokeConfigurationError(
                "AgentCollabBench worktree changed during integrity verification"
            )
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _git_blob_oid(chunks: Sequence[bytes]) -> str:
    size = sum(len(chunk) for chunk in chunks)
    digest = _new_git_sha1()
    digest.update(b"blob " + str(size).encode("ascii") + b"\0")
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


def _new_git_sha1() -> Any:
    try:
        return hashlib.sha1(usedforsecurity=False)
    except TypeError:  # pragma: no cover - older compatible Python fallback
        return hashlib.sha1()


def load_untouched_native_task(
    agentcollab_repository: Path,
    task_file: Path,
    *,
    expected_task_id: str,
    metric: str,
) -> tuple[dict[str, Any], str]:
    """Load the allowlisted tracked RTD task without rewriting it."""

    if metric != APPROVED_METRIC or expected_task_id != APPROVED_TASK_ID:
        raise SmokeConfigurationError(
            "task/metric is not on the approved engineering-smoke allowlist"
        )
    repository = agentcollab_repository.resolve()
    resolved_task = task_file.resolve()
    try:
        relative = resolved_task.relative_to(repository)
        resolved_task.relative_to(repository / "tasks")
    except ValueError as exc:
        raise SmokeConfigurationError(
            "task file must be inside the pinned AgentCollabBench tasks directory"
        ) from exc
    if resolved_task.name != APPROVED_TASK_FILENAME:
        raise SmokeConfigurationError(
            "task filename is not on the approved engineering-smoke allowlist"
        )
    tracked = _run_git(
        repository,
        ["ls-files", "--error-unmatch", "--", relative.as_posix()],
    )
    if tracked.returncode != 0:
        raise SmokeConfigurationError("task file must be tracked by AgentCollabBench")
    status = _git_output(
        repository,
        ["status", "--porcelain", "--untracked-files=all", "--", relative.as_posix()],
    )
    if status.strip():
        raise SmokeConfigurationError("task file has local modifications")
    raw_bytes = resolved_task.read_bytes()
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if raw_sha256 != APPROVED_TASK_SHA256:
        raise SmokeConfigurationError(
            "task bytes do not match the approved pinned SHA-256"
        )
    try:
        task = json.loads(raw_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SmokeConfigurationError("task file is not valid UTF-8 JSON") from exc
    if not isinstance(task, dict):
        raise SmokeConfigurationError("task file must contain one JSON object")
    validate_native_task(task, expected_task_id=expected_task_id, metric=metric)
    return task, raw_sha256


def validate_native_task(
    task: Mapping[str, Any],
    *,
    expected_task_id: str,
    metric: str,
) -> None:
    if task.get("task_id") != expected_task_id:
        raise SmokeConfigurationError(
            "task_id does not match the explicit --task-id gate"
        )
    metrics = task.get("metric_applicability")
    if not isinstance(metrics, list) or metric not in metrics:
        raise SmokeConfigurationError(
            f"task does not declare metric_applicability={metric!r}"
        )
    injections = task.get("injections")
    if not isinstance(injections, dict) or not isinstance(injections.get(metric), dict):
        raise SmokeConfigurationError(f"task has no injections.{metric} object")
    if "experimental_metadata" in task or "_runner_trace_overrides" in task:
        raise SmokeConfigurationError(
            "derived or runner-mutated AgentCollabBench tasks are forbidden"
        )
    topology = task.get("topology")
    if not isinstance(topology, dict):
        raise SmokeConfigurationError("task.topology must be an object")
    agents = topology.get("agents")
    speaking_order = topology.get("speaking_order")
    if not isinstance(agents, list) or len(agents) != 2:
        raise SmokeConfigurationError(
            "engineering smoke requires exactly two task agents"
        )
    if not isinstance(speaking_order, list) or not speaking_order:
        raise SmokeConfigurationError(
            "task.topology.speaking_order must be non-empty"
        )


def expected_agentcollab_calls(
    task: Mapping[str, Any],
    *,
    metric: str | None = None,
) -> int:
    topology = task.get("topology", {})
    speaking_order = topology.get("speaking_order", [])
    resolved_metric = metric
    if resolved_metric is None:
        declared_metrics = task.get("metric_applicability", [])
        if isinstance(declared_metrics, list) and len(declared_metrics) == 1:
            resolved_metric = str(declared_metrics[0])
    injections = task.get("injections", {})
    injection = (
        injections.get(resolved_metric, {})
        if isinstance(injections, dict) and resolved_metric is not None
        else {}
    )
    injection_expected = (
        injection.get("expected_turns") if isinstance(injection, dict) else None
    )
    raw_expected = injection_expected or task.get("expected_turns")
    if raw_expected is None:
        expected_turns = len(speaking_order)
    elif isinstance(raw_expected, bool) or not isinstance(raw_expected, int):
        raise SmokeConfigurationError("task.expected_turns must be an integer")
    else:
        expected_turns = raw_expected
    if expected_turns <= 0:
        raise SmokeConfigurationError("task.expected_turns must be positive")
    return max(len(speaking_order), expected_turns)


def conservative_input_token_bound(messages: Sequence[Mapping[str, str]]) -> int:
    """Return a tokenizer-independent byte upper bound plus envelope overhead."""

    total = 64
    for message in messages:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        total += 32 + len(role.encode("utf-8")) + len(content.encode("utf-8"))
    return total


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run exactly one private, analysis-ineligible AgentCollabBench "
            "engineering smoke."
        )
    )
    parser.add_argument("--agentcollab-repo", required=True, type=Path)
    parser.add_argument("--task-file", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--metric", required=True, choices=[APPROVED_METRIC])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help=(
            "read exactly one API-key line from non-TTY stdin; otherwise use "
            "hidden interactive input"
        ),
    )
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--request-timeout-seconds", type=float)
    parser.add_argument(
        "--send-seed",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "send the same seed to the provider only after gateway support is "
            "confirmed; Python injection randomness is always seeded"
        ),
    )
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--max-input-tokens", type=int)
    parser.add_argument("--max-output-tokens", type=int)
    parser.add_argument("--max-output-tokens-per-call", type=int)
    parser.add_argument("--max-wall-seconds", type=float)
    parser.add_argument("--max-cost-usd")
    parser.add_argument("--max-input-cost-usd-per-million-tokens")
    parser.add_argument("--max-output-cost-usd-per-million-tokens")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[3]
    overrides = {
        "base_url": args.base_url,
        "model": args.model,
        "temperature": args.temperature,
        "request_timeout_seconds": args.request_timeout_seconds,
        "send_seed": args.send_seed,
        "max_calls": args.max_calls,
        "max_input_tokens": args.max_input_tokens,
        "max_output_tokens": args.max_output_tokens,
        "max_output_tokens_per_call": args.max_output_tokens_per_call,
        "max_wall_seconds": args.max_wall_seconds,
        "max_cost_usd": args.max_cost_usd,
        "max_input_cost_usd_per_million_tokens": (
            args.max_input_cost_usd_per_million_tokens
        ),
        "max_output_cost_usd_per_million_tokens": (
            args.max_output_cost_usd_per_million_tokens
        ),
    }
    try:
        # Reject an unsafe initial environment before config git checks.  The
        # key is acquired only after non-secret configuration has validated.
        _assert_api_key_not_in_environment()
        settings = load_smoke_settings(
            repository_root=repository_root,
            config_path=args.config,
            overrides=overrides,
        )
        api_key, api_key_input_method = read_api_key_from_user_input(
            use_stdin=args.api_key_stdin
        )
        result = run_single_agentcollab_smoke(
            repository_root=repository_root,
            agentcollab_repository=args.agentcollab_repo,
            task_file=args.task_file,
            expected_task_id=args.task_id,
            metric=args.metric,
            settings=settings,
            api_key=api_key,
            api_key_input_method=api_key_input_method,
            seed=args.seed,
            run_id=args.run_id,
        )
    except (SmokeConfigurationError, SmokeExecutionError) as exc:
        print(
            json.dumps(
                {"ok": False, "error": str(exc)},
                ensure_ascii=False,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        "unexpected smoke-driver failure; no provider payload "
                        "or credential was printed"
                    ),
                },
                ensure_ascii=False,
                allow_nan=False,
            ),
            file=sys.stderr,
        )
        return 3
    print(
        json.dumps(
            {
                "ok": True,
                "purpose": PURPOSE,
                "analysis_eligible": ANALYSIS_ELIGIBLE,
                "run_id": result.run_id,
                "task_id": result.task_id,
                "metric": result.metric,
                "diagnostic_score": result.diagnostic_score,
                "private_run_directory": str(result.run_directory),
                "ledger": str(result.ledger_path),
                "lifecycle_trace": str(result.trace_path),
            },
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if (
        base_url != PAPERBYPASS_BASE_URL
        or parsed.scheme != "https"
        or parsed.netloc != "aigateway.paperbypass.com"
        or parsed.hostname != "aigateway.paperbypass.com"
        or parsed.path != "/api/v1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise SmokeConfigurationError(
            "provider.base_url must be exactly the approved PaperBypass API base"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise SmokeConfigurationError("provider.base_url has an invalid port") from exc
    if port is not None:
        raise SmokeConfigurationError("provider.base_url cannot specify a port")


def _assert_local_config_is_untracked(path: Path, repository_root: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SmokeConfigurationError(f"local config does not exist: {path}")
    root = repository_root.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return
    result = _run_git(
        root,
        ["check-ignore", "--quiet", "--", relative.as_posix()],
    )
    if result.returncode != 0:
        raise SmokeConfigurationError(
            "local TOML inside the repository must be git-ignored"
        )


def _process_bounded_urllib_transport(
    endpoint: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> HTTPResult:
    """Run urllib in a killable process under one absolute parent deadline."""

    _assert_api_key_not_in_environment()
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ProviderRequestError("provider timeout must be positive and finite")
    deadline = time.monotonic() + timeout_seconds
    context = multiprocessing.get_context("spawn")
    receive_connection, send_connection = context.Pipe(duplex=False)
    response_buffer = context.RawArray("B", MAX_RESPONSE_BODY_BYTES)
    process = context.Process(
        target=_urllib_transport_worker,
        args=(
            send_connection,
            response_buffer,
            endpoint,
            dict(headers),
            body,
            timeout_seconds,
        ),
        name="agentcollab-smoke-http",
        daemon=True,
    )
    started = False
    try:
        process.start()
        started = True
        send_connection.close()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_transport_worker(process)
            raise ProviderRequestError(
                "OpenAI-compatible transport exceeded its absolute deadline"
            )
        process.join(remaining)
        if process.is_alive():
            _stop_transport_worker(process)
            raise ProviderRequestError(
                "OpenAI-compatible transport exceeded its absolute deadline"
            )
        if time.monotonic() > deadline:
            raise ProviderRequestError(
                "OpenAI-compatible transport exceeded its absolute deadline"
            )
        if not receive_connection.poll(0):
            raise ProviderRequestError(
                "OpenAI-compatible transport worker exited without a result"
            )
        try:
            message = receive_connection.recv()
        except (EOFError, OSError) as exc:
            raise ProviderRequestError(
                "OpenAI-compatible transport worker result was unavailable"
            ) from exc
        result = _decode_transport_worker_result(message, response_buffer)
        if time.monotonic() > deadline:
            raise ProviderRequestError(
                "OpenAI-compatible transport exceeded its absolute deadline"
            )
        return result
    except ProviderRequestError:
        raise
    except Exception as exc:
        raise ProviderRequestError(
            "OpenAI-compatible transport worker failed"
        ) from exc
    finally:
        receive_connection.close()
        try:
            send_connection.close()
        except OSError:
            pass
        if started and process.is_alive():
            _stop_transport_worker(process)
        if started and not process.is_alive():
            process.close()


def _urllib_transport_worker(
    send_connection: Any,
    response_buffer: Any,
    endpoint: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> None:
    """Child entry point; secrets arrive in process IPC, never argv or env."""

    try:
        result = _urllib_transport(endpoint, headers, body, timeout_seconds)
        if len(result.body) > MAX_RESPONSE_BODY_BYTES:
            raise ProviderRequestError("provider response body exceeds size limit")
        response_buffer[: len(result.body)] = result.body
        send_connection.send(
            {
                "kind": "result",
                "status": result.status,
                "headers": dict(result.headers),
                "body_length": len(result.body),
            }
        )
    except BaseException as exc:
        try:
            send_connection.send(
                {"kind": "error", "error_type": type(exc).__name__}
            )
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        send_connection.close()


def _decode_transport_worker_result(message: Any, response_buffer: Any) -> HTTPResult:
    if not isinstance(message, dict):
        raise ProviderRequestError("provider transport worker returned invalid data")
    if message.get("kind") == "error":
        raise ProviderRequestError("OpenAI-compatible transport worker failed")
    status = message.get("status")
    headers = message.get("headers")
    body_length = message.get("body_length")
    if (
        message.get("kind") != "result"
        or isinstance(status, bool)
        or not isinstance(status, int)
        or not isinstance(headers, dict)
        or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in headers.items()
        )
        or isinstance(body_length, bool)
        or not isinstance(body_length, int)
        or not 0 <= body_length <= MAX_RESPONSE_BODY_BYTES
    ):
        raise ProviderRequestError("provider transport worker returned invalid data")
    return HTTPResult(
        status=status,
        headers=headers,
        body=bytes(response_buffer[:body_length]),
    )


def _stop_transport_worker(process: Any) -> None:
    """Best-effort terminate then kill, always reaping the child."""

    if not process.is_alive():
        process.join(0)
        return
    process.terminate()
    process.join(_WORKER_STOP_GRACE_SECONDS)
    if process.is_alive():
        kill = getattr(process, "kill", None)
        if callable(kill):
            kill()
        else:  # pragma: no cover - supported Python platforms expose kill()
            process.terminate()
        process.join(_WORKER_STOP_GRACE_SECONDS)


def _urllib_transport(
    endpoint: str,
    headers: Mapping[str, str],
    body: bytes,
    timeout_seconds: float,
) -> HTTPResult:
    deadline = time.monotonic() + timeout_seconds
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    opener = urllib.request.build_opener(_RejectRedirectHandler())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            return HTTPResult(
                status=int(response.status),
                headers=_selected_response_headers(response.headers),
                body=_read_response_body(response, deadline=deadline),
            )
    except urllib.error.HTTPError as exc:
        try:
            body_bytes = _read_response_body(exc, deadline=deadline)
            return HTTPResult(
                status=int(exc.code),
                headers=_selected_response_headers(exc.headers),
                body=body_bytes,
            )
        finally:
            exc.close()
    except (OSError, urllib.error.URLError) as exc:
        raise ProviderRequestError(
            "OpenAI-compatible transport failed"
        ) from exc


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Disable redirects so Authorization is never replayed to another URL."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


def _read_response_body(
    stream: Any,
    *,
    deadline: float,
    max_bytes: int = MAX_RESPONSE_BODY_BYTES,
    monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    """Read with an absolute deadline and a hard decoded-body byte ceiling."""

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ProviderRequestError("response body limit must be positive")
    content_length = None
    headers = getattr(stream, "headers", None)
    if headers is not None:
        content_length = headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except (TypeError, ValueError) as exc:
            raise ProviderRequestError(
                "provider returned an invalid Content-Length"
            ) from exc
        if declared_length < 0 or declared_length > max_bytes:
            raise ProviderRequestError("provider response body exceeds size limit")

    chunks: list[bytes] = []
    total = 0
    reader = getattr(stream, "read1", None)
    if not callable(reader):
        reader = stream.read
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ProviderRequestError(
                "provider response body exceeded absolute deadline"
            )
        _set_stream_timeout(stream, remaining)
        chunk = reader(min(64 * 1024, max_bytes + 1 - total))
        if monotonic() > deadline:
            raise ProviderRequestError(
                "provider response body exceeded absolute deadline"
            )
        if not chunk:
            break
        if not isinstance(chunk, bytes):
            raise ProviderRequestError("provider response body must be bytes")
        chunks.append(chunk)
        total += len(chunk)
        if total > max_bytes:
            raise ProviderRequestError("provider response body exceeds size limit")
    return b"".join(chunks)


def _set_stream_timeout(stream: Any, remaining_seconds: float) -> None:
    """Best-effort socket timeout tightening for each bounded read."""

    candidates = [stream]
    for attribute in ("fp", "raw", "_sock"):
        current = candidates[-1]
        next_candidate = getattr(current, attribute, None)
        if next_candidate is None:
            break
        candidates.append(next_candidate)
    for candidate in reversed(candidates):
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            setter(max(0.001, remaining_seconds))
            return


def _selected_response_headers(headers: Any) -> dict[str, str]:
    selected: dict[str, str] = {}
    for name in ("content-type", "x-request-id", "request-id"):
        value = headers.get(name) if headers is not None else None
        if value is not None:
            rendered = str(value)
            if len(rendered) > MAX_SELECTED_HEADER_CHARACTERS:
                raise ProviderRequestError(
                    "provider returned an oversized selected response header"
                )
            selected[name] = rendered
    return selected


def _parse_chat_completion(
    value: Any,
    configured_model: str,
) -> tuple[str, str, int, int, str | None, Decimal | None]:
    if not isinstance(value, dict):
        raise ProviderRequestError("provider response must be a JSON object")
    choices = value.get("choices")
    usage = value.get("usage")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderRequestError("provider response has no first choice")
    message = choices[0].get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise ProviderRequestError("provider response choice has no text content")
    if not message["content"].strip():
        raise ProviderRequestError("provider response content must be non-empty")
    if choices[0].get("finish_reason") != "stop":
        raise ProviderRequestError(
            "provider response finish_reason must be exactly 'stop'"
        )
    response_model = value.get("model")
    if not isinstance(response_model, str) or response_model != configured_model:
        raise ProviderRequestError(
            "provider response model is missing or differs from configured model"
        )
    if not isinstance(usage, dict):
        raise ProviderRequestError("provider response must include token usage")
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if (
        isinstance(input_tokens, bool)
        or not isinstance(input_tokens, int)
        or isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
    ):
        raise ProviderRequestError(
            "provider response usage must include integer prompt/completion tokens"
        )
    known_cost_raw = value.get("cost_usd", usage.get("cost_usd"))
    known_cost = (
        _decimal(known_cost_raw, "provider cost_usd")
        if known_cost_raw is not None
        else None
    )
    if known_cost is not None and known_cost < 0:
        raise ProviderRequestError("provider cost_usd cannot be negative")
    response_id = value.get("id")
    return (
        message["content"],
        response_model,
        input_tokens,
        output_tokens,
        str(response_id) if response_id is not None else None,
        known_cost,
    )


def _atomic_write_private(path: Path, value: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"private artifact already exists: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=False,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and not overwrite:
            raise FileExistsError(f"private artifact already exists: {path}")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _redact_value(value: Any, secret: str) -> Any:
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, dict):
        return {
            str(_redact_value(key, secret)): _redact_value(item, secret)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact_value(item, secret) for item in value]
    return value


def _activate_agentcollab_repository(repository: Path) -> None:
    resolved = str(repository.resolve())
    if resolved not in sys.path:
        sys.path.insert(0, resolved)
    import agentcollabbench

    package_path = Path(agentcollabbench.__file__).resolve()
    try:
        package_path.relative_to(Path(resolved))
    except ValueError as exc:
        raise SmokeConfigurationError(
            "a different AgentCollabBench package is already imported"
        ) from exc


def _git_output(repository: Path, arguments: list[str]) -> str:
    result = _run_git(repository, arguments)
    if result.returncode != 0:
        raise SmokeConfigurationError(
            "unable to verify the AgentCollabBench git checkout"
        )
    return result.stdout


def _run_git(
    repository: Path,
    arguments: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _git_command(arguments),
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        env=_git_subprocess_environment(),
    )


def _run_git_bytes(
    repository: Path,
    arguments: Sequence[str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        _git_command(arguments),
        cwd=repository,
        capture_output=True,
        text=False,
        check=False,
        env=_git_subprocess_environment(),
    )


def _git_command(arguments: Sequence[str]) -> list[str]:
    return [
        "git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        *arguments,
    ]


def _git_subprocess_environment() -> dict[str, str]:
    """Copy the environment without ever retrieving the forbidden key value."""

    environment: dict[str, str] = {}
    for name in os.environ:
        if name != "PAPERBYPASS_API_KEY" and not name.startswith("GIT_"):
            environment[name] = os.environ[name]
    return environment


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SmokeConfigurationError(f"limits.{name} must be an integer")
    return value


def _strict_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise SmokeConfigurationError(f"provider.{name} must be boolean")
    return value


def _decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except Exception as exc:
        raise SmokeConfigurationError(f"{name} must be a decimal") from exc
    if not parsed.is_finite():
        raise SmokeConfigurationError(f"{name} must be finite")
    return parsed


def _token_cost(tokens: int, price_per_million: Decimal) -> Decimal:
    return Decimal(tokens) * price_per_million / Decimal(1_000_000)


def _money(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM), "f")


def _limits_dict(limits: BudgetLimits) -> dict[str, Any]:
    return {
        "max_calls": limits.max_calls,
        "max_input_tokens": limits.max_input_tokens,
        "max_output_tokens": limits.max_output_tokens,
        "max_output_tokens_per_call": limits.max_output_tokens_per_call,
        "max_wall_seconds": limits.max_wall_seconds,
        "max_cost_usd": _money(limits.max_cost_usd),
        "max_input_cost_usd_per_million_tokens": _money(
            limits.max_input_cost_usd_per_million_tokens
        ),
        "max_output_cost_usd_per_million_tokens": _money(
            limits.max_output_cost_usd_per_million_tokens
        ),
    }


def _new_run_id(task_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", task_id).strip("-.")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"acb-smoke-{normalized[:40]}-{timestamp}-{uuid4().hex[:8]}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
