from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from mas_error_lifecycle.adapters.agentcollab_smoke import (
    BudgetLimits,
    HTTPResult,
    PAPERBYPASS_BASE_URL,
    PAPERBYPASS_MODEL,
    ProviderSettings,
    SmokeSettings,
)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_rq1_real_calibration.py"
_FIXTURE = (
    Path(__file__).resolve().parents[1] / "configs" / "rq1-fixture.example.json"
)


def _load_driver():
    spec = importlib.util.spec_from_file_location("rq1_calibration_driver", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["rq1_calibration_driver"] = module
    spec.loader.exec_module(module)
    return module


_driver = _load_driver()


def _settings() -> SmokeSettings:
    return SmokeSettings(
        provider=ProviderSettings(
            base_url=PAPERBYPASS_BASE_URL,
            model=PAPERBYPASS_MODEL,
            temperature=0.0,
            send_seed=False,
        ),
        limits=BudgetLimits(
            max_calls=6,
            max_input_tokens=200_000,
            max_output_tokens=8_192,
            max_output_tokens_per_call=2_048,
            max_wall_seconds=60.0,
            max_cost_usd=Decimal("0.05"),
            max_input_cost_usd_per_million_tokens=Decimal("0.04815"),
            max_output_cost_usd_per_million_tokens=Decimal("0.19305"),
        ),
    )


def _success_result(counter: list[int]) -> HTTPResult:
    counter[0] += 1
    return HTTPResult(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(
            {
                "id": f"response-{counter[0]}",
                "model": PAPERBYPASS_MODEL,
                "choices": [
                    {
                        "message": {"content": "short deterministic answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 5},
            }
        ).encode(),
    )


class RQ1CalibrationDriverTests(unittest.TestCase):
    def test_load_fixture_parses_example_manifest(self) -> None:
        manifest, producer_prompt, model_version = _driver._load_fixture(_FIXTURE)
        self.assertEqual(len(manifest.required_facts), 6)
        self.assertEqual(len(manifest.distractors), 6)
        self.assertIn("{transformed_text}", manifest.downstream_prompt_template)
        self.assertTrue(producer_prompt.strip())
        self.assertTrue(model_version.strip())

    def test_full_driver_runs_three_arms_with_offline_transport(self) -> None:
        counter = [0]

        def transport(endpoint, headers, body, timeout):
            return _success_result(counter)

        secret = "rq1-driver-secret"
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result = _driver.run_rq1_real_calibration(
                    repository_root=root,
                    fixture_path=_FIXTURE,
                    settings=_settings(),
                    api_key=secret,
                    api_key_input_method="caller_memory",
                    run_id="rq1-driver-test",
                    transport=transport,
                )

                self.assertEqual(counter[0], 4)  # one summary + three downstream
                self.assertEqual(len(result["arms"]), 3)
                self.assertTrue(result["analysis_eligible"] is False)
                run_directory = Path(result["private_run_directory"])
                self.assertTrue(
                    (run_directory / "rq1-calibration-ledger.json").is_file()
                )
                ledger = json.loads(
                    (run_directory / "rq1-calibration-ledger.json").read_text()
                )
                self.assertEqual(ledger["status"], "completed")
                self.assertEqual(len(ledger["calls"]), 4)
                for suffix in ("c0", "c1", "t"):
                    self.assertTrue(
                        (run_directory / f"lifecycle-trace-{suffix}.jsonl").is_file()
                    )
                private_text = "\n".join(
                    path.read_text()
                    for path in run_directory.rglob("*")
                    if path.is_file()
                )
                self.assertNotIn(secret, private_text)


if __name__ == "__main__":
    unittest.main()
