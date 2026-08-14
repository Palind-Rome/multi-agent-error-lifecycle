#!/usr/bin/env python3
"""Guarded real-provider RQ1 three-arm engineering calibration driver.

Runs one fixture in all three arms (C0 raw / C1 length-matched reference /
T abstractive summary) against the pinned PaperBypass Qwen model, then the
downstream answer call.  Output is analysis-ineligible and kept under the
git-ignored ``outputs/private`` directory.  The API key is read only from
hidden interactive input or one non-TTY stdin line, never from the environment
or the command line.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

sys.dont_write_bytecode = True

from mas_error_lifecycle.adapters.agentcollab_smoke import (
    ANALYSIS_ELIGIBLE,
    PURPOSE,
    BudgetGate,
    CallReservation,
    OpenAICompatibleSmokeProvider,
    PrivateRunStore,
    SettledCall,
    SmokeConfigurationError,
    SmokeExecutionError,
    load_smoke_settings,
    read_api_key_from_user_input,
)
from mas_error_lifecycle.rq1_runner import (
    RQ1FixtureManifest,
    RealCallEvidence,
    run_rq1_three_arm_calibration,
)

_ARM_TRACE_FILENAME = "lifecycle-trace-{suffix}.jsonl"
_LEDGER_FILENAME = "rq1-calibration-ledger.json"
_ARM_TO_SUFFIX = {
    "raw_passthrough": "c0",
    "length_matched_reference": "c1",
    "abstractive_summary": "t",
}
_MODEL_VERSION = "qwen3-30b-a3b-2507"
_PRODUCER_OUTPUT_TOKEN_CAP = 2_048
_DOWNSTREAM_OUTPUT_TOKEN_CAP = 2_048
_CONTEXT_TOKEN_CAP = 200_000


class RQ1CalibrationError(RuntimeError):
    """Safe public error pointing to a durable private ledger."""

    def __init__(self, stage: str, error_type: str, ledger_path: Path | None):
        self.stage = stage
        self.error_type = error_type
        self.ledger_path = ledger_path
        super().__init__(
            f"RQ1 calibration failed during {stage} ({error_type})"
            + (f"; see private ledger {ledger_path}" if ledger_path else "")
        )


@dataclass(frozen=True, slots=True)
class _ChatMessage:
    role: str
    content: str


class _RQ1Ledger:
    """Durable, redacted per-call ledger duck-typed for the smoke provider."""

    def __init__(self, store: PrivateRunStore, run_id: str, model: str):
        self.store = store
        self.path = store.run_directory / _LEDGER_FILENAME
        self.document: dict[str, Any] = {
            "schema_version": "rq1-calibration-ledger/1",
            "run_id": run_id,
            "purpose": PURPOSE,
            "analysis_eligible": ANALYSIS_ELIGIBLE,
            "provider": {"kind": "openai-compatible", "model": model},
            "status": "running",
            "calls": [],
            "budget": {},
            "failure": None,
        }
        self._flush()

    def call_started(self, reservation: CallReservation, request_path: Path, budget: BudgetGate) -> None:
        self.document["calls"].append(
            {
                "call_index": reservation.call_index,
                "call_id": reservation.call_id,
                "status": "started",
                "request_path": str(request_path.relative_to(self.store.run_directory)),
                "estimated_input_tokens": reservation.estimated_input_tokens,
                "max_output_tokens": reservation.max_output_tokens,
            }
        )
        self.document["budget"] = budget.snapshot()
        self._flush()

    def call_succeeded(self, reservation: CallReservation, response_path: Path, settled: SettledCall, budget: BudgetGate) -> None:
        call = self._call(reservation.call_index)
        call.update(
            {
                "status": "success",
                "response_path": str(response_path.relative_to(self.store.run_directory)),
                "input_tokens": settled.input_tokens,
                "output_tokens": settled.output_tokens,
                "accounted_cost_usd": str(settled.accounted_cost_usd),
            }
        )
        self.document["budget"] = budget.snapshot()
        self._flush()

    def call_failed(self, reservation: CallReservation, *, error_type: str, response_path: Path | None, budget: BudgetGate) -> None:
        call = self._call(reservation.call_index)
        call.update({"status": "failed", "error_type": error_type})
        self.document["status"] = "provider_failed"
        self.document["failure"] = {"error_type": error_type}
        self.document["budget"] = budget.snapshot()
        self._flush()

    def mark_completed(self, *, trace_paths: Mapping[str, str], budget: BudgetGate) -> None:
        self.document["status"] = "completed"
        self.document["budget"] = budget.snapshot()
        self.document["failure"] = None
        self.document["artifacts"] = trace_paths
        self._flush()

    def mark_failed(self, stage: str, error_type: str, budget: BudgetGate) -> None:
        self.document["status"] = "failed"
        self.document["stage"] = stage
        self.document["budget"] = budget.snapshot()
        self.document["failure"] = {"stage": stage, "error_type": error_type}
        self._flush()

    def _call(self, call_index: int) -> dict[str, Any]:
        for call in self.document["calls"]:
            if call["call_index"] == call_index:
                return call
        raise RuntimeError(f"ledger is missing call index {call_index}")

    def _flush(self) -> None:
        self.document["updated_at"] = _utc_now()
        self.store.write_json(_LEDGER_FILENAME, self.document, overwrite=True)


def _make_call_fn(provider: OpenAICompatibleSmokeProvider) -> Callable:
    def call(messages: tuple[dict[str, str], ...], max_tokens: int | None) -> RealCallEvidence:
        chat_messages = [_ChatMessage(m["role"], m["content"]) for m in messages]
        kwargs: dict[str, Any] = {}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        response = provider.chat(chat_messages, **kwargs)
        return RealCallEvidence(
            content=response.content,
            provider="openai-compatible",
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            raw_response_id=response.raw_response_id,
        )

    return call


def _load_fixture(path: Path) -> tuple[RQ1FixtureManifest, str, str]:
    """Load a fixture manifest JSON and its prompt/model extras."""

    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise RQ1CalibrationError("fixture_load", "manifest is not an object", None)
    manifest = RQ1FixtureManifest(
        fixture_id=str(raw["fixture_id"]),
        task_id=str(raw["task_id"]),
        source_text=str(raw["source_text"]),
        required_facts=tuple(
            (str(item[0]), str(item[1])) for item in raw["required_facts"]
        ),
        distractors=tuple(
            (str(item[0]), str(item[1])) for item in raw["distractors"]
        ),
        reference_text=str(raw["reference_text"]),
        downstream_prompt_template=str(raw["downstream_prompt_template"]),
        char_budget=int(raw["char_budget"]),
        token_budget=int(raw["token_budget"]),
    )
    producer_system_prompt = str(raw["producer_system_prompt"])
    model_version = str(raw.get("model_version", _MODEL_VERSION))
    return manifest, producer_system_prompt, model_version


def run_rq1_real_calibration(
    *,
    repository_root: Path,
    fixture_path: Path,
    settings: Any,
    api_key: str,
    api_key_input_method: str,
    run_id: str,
    model_version: str | None = None,
    transport: Any | None = None,
) -> dict[str, Any]:
    manifest, producer_system_prompt, resolved_model_version = _load_fixture(fixture_path)
    if model_version is not None:
        resolved_model_version = model_version

    store = PrivateRunStore.create(repository_root, run_id, api_key)
    budget = BudgetGate(settings.limits)
    ledger = _RQ1Ledger(store, run_id, settings.provider.model)
    provider = OpenAICompatibleSmokeProvider(
        settings.provider,
        api_key=api_key,
        budget=budget,
        store=store,
        ledger=ledger,
        transport=transport,
        seed=7,
    )

    stage = "provider_execution"
    try:
        bundles = run_rq1_three_arm_calibration(
            manifest=manifest,
            call=_make_call_fn(provider),
            run_id_base=run_id,
            repeat_id="repeat-001",
            block_id="block-001",
            started_at=_utc_now(),
            model=settings.provider.model,
            model_version=resolved_model_version,
            producer_system_prompt=producer_system_prompt,
            context_token_cap=_CONTEXT_TOKEN_CAP,
            downstream_output_token_cap=_DOWNSTREAM_OUTPUT_TOKEN_CAP,
            producer_output_token_cap=_PRODUCER_OUTPUT_TOKEN_CAP,
        )
        stage = "trace_persistence"
        trace_paths: dict[str, str] = {}
        for bundle in bundles:
            suffix = _ARM_TO_SUFFIX[bundle.manifest.condition_id]
            filename = _ARM_TRACE_FILENAME.format(suffix=suffix)
            lines = "".join(
                json.dumps(record.to_dict(), ensure_ascii=False, allow_nan=False)
                + "\n"
                for record in bundle.records()
            )
            store.write_text(filename, lines)
            trace_paths[f"arm:{bundle.manifest.condition_id}"] = filename
        budget.assert_runtime()
        ledger.mark_completed(trace_paths=trace_paths, budget=budget)
    except (SmokeConfigurationError, RQ1CalibrationError, ValueError) as exc:
        ledger.mark_failed(stage, type(exc).__name__, budget)
        raise RQ1CalibrationError(stage, type(exc).__name__, ledger.path) from exc
    except Exception as exc:
        ledger.mark_failed(stage, type(exc).__name__, budget)
        raise RQ1CalibrationError(stage, type(exc).__name__, ledger.path) from exc

    return {
        "run_id": run_id,
        "fixture_id": manifest.fixture_id,
        "purpose": PURPOSE,
        "analysis_eligible": ANALYSIS_ELIGIBLE,
        "arms": [bundle.manifest.condition_id for bundle in bundles],
        "private_run_directory": str(store.run_directory),
        "ledger": str(ledger.path),
        "traces": trace_paths,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one private, analysis-ineligible RQ1 three-arm calibration."
    )
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--model-version")
    parser.add_argument(
        "--api-key-stdin",
        action="store_true",
        help="read exactly one API-key line from non-TTY stdin",
    )
    return parser


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.dont_write_bytecode = True
    repository_root = Path(__file__).resolve().parents[1]
    run_id = args.run_id or f"rq1-calib-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    try:
        settings = load_smoke_settings(
            repository_root=repository_root,
            config_path=args.config,
            overrides={},
        )
        api_key, api_key_input_method = read_api_key_from_user_input(
            use_stdin=args.api_key_stdin
        )
        result = run_rq1_real_calibration(
            repository_root=repository_root,
            fixture_path=args.fixture,
            settings=settings,
            api_key=api_key,
            api_key_input_method=api_key_input_method,
            run_id=run_id,
            model_version=args.model_version,
        )
    except (SmokeConfigurationError, RQ1CalibrationError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "unexpected RQ1 calibration failure; no credential was printed",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
