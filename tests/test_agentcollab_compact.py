from __future__ import annotations

import json
import os
import sys
import unittest
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from mas_error_lifecycle.adapters.agentcollab_compact import (
    COMPACT_PROMPT,
    CONDITION_ID,
    PROTOCOL_KIND,
    SUMMARY_PREFIX,
    expected_compaction_calls,
    run_single_agentcollab_compact,
)
from mas_error_lifecycle.adapters.agentcollab_smoke import (
    APPROVED_TASK_ID,
    PAPERBYPASS_BASE_URL,
    PAPERBYPASS_MODEL,
    BudgetLimits,
    HTTPResult,
    ProviderSettings,
    SmokeSettings,
    expected_agentcollab_calls,
    _run_git,
)
from mas_error_lifecycle.store import load_trace


def _compact_settings(*, max_calls: int = 16) -> SmokeSettings:
    return SmokeSettings(
        provider=ProviderSettings(
            base_url=PAPERBYPASS_BASE_URL,
            model=PAPERBYPASS_MODEL,
            send_seed=False,
        ),
        limits=BudgetLimits(
            max_calls=max_calls,
            max_input_tokens=1_000_000,
            max_output_tokens=200,
            max_output_tokens_per_call=50,
            max_wall_seconds=30.0,
            max_cost_usd=Decimal("1"),
            max_input_cost_usd_per_million_tokens=Decimal("0.05"),
            max_output_cost_usd_per_million_tokens=Decimal("0.20"),
        ),
    )


class AgentCollabCompactTests(unittest.TestCase):
    def tearDown(self) -> None:
        # Each driver call imports the upstream agentcollabbench package from a
        # throwaway clone. Purge it (and any stale clone path) so later test
        # modules that activate their own clone start from a clean import state.
        for name in list(sys.modules):
            if name == "agentcollabbench" or name.startswith("agentcollabbench."):
                del sys.modules[name]
        sys.path[:] = [
            path for path in sys.path if "AgentCollabBench" not in path
        ]

    def test_compaction_call_count_matches_runner_for_dense_and_linear(self) -> None:
        workspace = Path(__file__).resolve().parents[2]
        source_upstream = workspace / "assets" / "AgentCollabBench"
        if not source_upstream.is_dir():
            self.skipTest("pinned AgentCollabBench checkout is not available")
        for task_id in ("TASK-DATAENG-RTD-060", "TASK-SWE-RTD-092"):
            task = json.loads(
                (source_upstream / "tasks" / f"{task_id}.json").read_text()
            )
            native = expected_agentcollab_calls(task, metric="rtd")
            compactions = expected_compaction_calls(task, metric="rtd")
            self.assertGreater(compactions, 0)
            self.assertLess(compactions, native)

    def test_compact_driver_runs_pinned_upstream_with_offline_transport(self) -> None:
        workspace = Path(__file__).resolve().parents[2]
        source_upstream = workspace / "assets" / "AgentCollabBench"
        if not source_upstream.is_dir():
            self.skipTest("pinned AgentCollabBench checkout is not available")
        attempts = 0
        transport_saw_process_key: list[bool] = []

        def transport(endpoint, headers, body, timeout):
            nonlocal attempts
            attempts += 1
            transport_saw_process_key.append("PAPERBYPASS_API_KEY" in os.environ)
            return HTTPResult(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps(
                    {
                        "id": f"offline-compact-{attempts}",
                        "model": PAPERBYPASS_MODEL,
                        "choices": [
                            {
                                "message": {"content": "offline deterministic response"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 3},
                    }
                ).encode(),
            )

        settings = _compact_settings(max_calls=16)
        secret = "offline-compact-secret"
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as directory:
                temporary_root = Path(directory)
                upstream = temporary_root / "AgentCollabBench"
                clone = _run_git(
                    Path(__file__).resolve().parents[1],
                    ["clone", "--quiet", "--no-hardlinks", str(source_upstream), str(upstream)],
                )
                self.assertEqual(clone.returncode, 0, clone.stderr)
                task_file = upstream / "tasks" / "TASK-DATAENG-RTD-060.json"
                result = run_single_agentcollab_compact(
                    repository_root=temporary_root / "driver-output",
                    agentcollab_repository=upstream,
                    task_file=task_file,
                    expected_task_id=APPROVED_TASK_ID,
                    metric="rtd",
                    settings=settings,
                    api_key=secret,
                    seed=7,
                    run_id="offline-compact",
                    transport=transport,
                )
                bundle = load_trace(result.trace_path)
                ledger_document = json.loads(result.ledger_path.read_text())
                raw_result = json.loads(result.raw_result_path.read_text())
                compaction_sidecar = (
                    result.run_directory / "compaction-summaries.jsonl"
                )
                compaction_records = [
                    json.loads(line)
                    for line in compaction_sidecar.read_text().splitlines()
                    if line.strip()
                ]
                private_text = "\n".join(
                    path.read_text()
                    for path in result.run_directory.rglob("*")
                    if path.is_file()
                )

        # RTD-060: A1(root)->A2, 8 effective turns -> 8 agent calls + 4 compactions.
        self.assertEqual(len(raw_result["run_result"]["trace"]["provider_requests"]), 8)
        self.assertEqual(
            len(raw_result["run_result"]["trace"]["compaction_calls"]), 4
        )
        self.assertEqual(attempts, 12)
        self.assertEqual(ledger_document["budget"]["calls_started"], 12)
        self.assertEqual(ledger_document["budget"]["calls_completed"], 12)
        self.assertEqual(len(compaction_records), 4)
        for record in compaction_records:
            self.assertEqual(record["agent_id"], "__compactor__")
            self.assertEqual(record["status"], "success")
            self.assertEqual(
                record["messages"][-1]["content"], COMPACT_PROMPT
            )
            self.assertEqual(record["receiver_agent_id"], "A2")

        provider_requests = raw_result["run_result"]["trace"]["provider_requests"]
        root_requests = [r for r in provider_requests if r["agent_id"] == "A1"]
        child_requests = [r for r in provider_requests if r["agent_id"] == "A2"]
        for request in root_requests:
            self.assertNotIn("Another language model", request["messages"][1]["content"])
        for request in child_requests:
            self.assertTrue(
                request["messages"][1]["content"].startswith(SUMMARY_PREFIX)
            )
            self.assertIn("offline deterministic response", request["messages"][1]["content"])

        routing = raw_result["run_result"]["trace"]["compaction_routing"]
        self.assertEqual(routing["mode"], "codex_handoff_summary")

        manifest = bundle.manifest
        self.assertFalse(manifest.analysis_eligible)
        self.assertEqual(manifest.condition_id, CONDITION_ID)
        self.assertEqual(manifest.protocol_kind, PROTOCOL_KIND)

        self.assertNotIn(secret, private_text)
        self.assertNotIn("PAPERBYPASS_API_KEY", os.environ)

    def test_compact_driver_rejects_when_budget_too_small(self) -> None:
        workspace = Path(__file__).resolve().parents[2]
        source_upstream = workspace / "assets" / "AgentCollabBench"
        if not source_upstream.is_dir():
            self.skipTest("pinned AgentCollabBench checkout is not available")
        from mas_error_lifecycle.adapters.agentcollab_smoke import SmokeConfigurationError

        def transport(endpoint, headers, body, timeout):
            raise AssertionError("transport must not be reached")

        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as directory:
                temporary_root = Path(directory)
                upstream = temporary_root / "AgentCollabBench"
                _run_git(
                    Path(__file__).resolve().parents[1],
                    ["clone", "--quiet", "--no-hardlinks", str(source_upstream), str(upstream)],
                )
                with self.assertRaises(SmokeConfigurationError):
                    run_single_agentcollab_compact(
                        repository_root=temporary_root / "driver-output",
                        agentcollab_repository=upstream,
                        task_file=upstream / "tasks" / "TASK-DATAENG-RTD-060.json",
                        expected_task_id=APPROVED_TASK_ID,
                        metric="rtd",
                        settings=_compact_settings(max_calls=5),
                        api_key="secret",
                        seed=7,
                        transport=transport,
                    )


if __name__ == "__main__":
    unittest.main()
