"""Offline tests for the allowlist-expansion helper (scripts/expand_agentcollab_allowlist.py).

The helper is a review tool, not a run-plan executor, so the tests cover its
pure introspection helpers and one end-to-end ``main()`` over a fixture tasks
directory. They never touch ``outputs/`` or the real AgentCollabBench checkout.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "expand_agentcollab_allowlist.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("expand_agentcollab_allowlist", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["expand_agentcollab_allowlist"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _task(**overrides) -> dict:
    base = {
        "task_id": "TASK-TEST-RTD-001",
        "domain": "data_engineering",
        "topology": {"type": "linear_chain", "agents": [{"id": "A1"}, {"id": "A2"}]},
        "metric_applicability": ["rtd"],
        "injections": {
            "rtd": {
                "anchor": "the pipeline must be idempotent",
                "tracer_id": "TRACER-1",
                "constraint_type": "numerical",
                "salience": "high",
            }
        },
    }
    base.update(overrides)
    return base


class AllowlistHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_script()

    def test_tracer_count_single(self):
        self.assertEqual(self.mod._tracer_count("rtd", _task()), 1)

    def test_tracer_count_multi_constraint(self):
        task = _task(injections={"rtd": {"multi_constraint": {"constraints": [
            {"tracer_id": "X", "anchor": "a"},
            {"tracer_id": "Y", "anchor": "b"},
        ]}}})
        self.assertEqual(self.mod._tracer_count("rtd", task), 2)

    def test_tracer_count_missing_anchor(self):
        task = _task(injections={"rtd": {}})
        self.assertEqual(self.mod._tracer_count("rtd", task), 0)

    def test_cpr_tracer_count(self):
        task = _task(
            metric_applicability=["cpr"],
            injections={"cpr": {"false_fact": "x", "seed_agent": "A1", "ground_truth": "y"}},
        )
        self.assertEqual(self.mod._tracer_count("cpr", task), 1)

    def test_cell(self):
        self.assertEqual(
            self.mod._cell(_task()),
            ("data_engineering", 2, "linear_chain"),
        )

    def test_sha256_is_byte_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "task.json"
            payload = b'{"task_id": "TASK-TEST-RTD-001"}\n'
            path.write_bytes(payload)
            self.assertEqual(
                self.mod._sha256(path),
                hashlib.sha256(payload).hexdigest(),
            )

    def test_existing_allowlist_reads_rtd(self):
        allowlist = self.mod._existing_allowlist(_REPO_ROOT, "rtd")
        self.assertIsInstance(allowlist, dict)
        self.assertIn("TASK-DATAENG-RTD-060", allowlist)
        self.assertEqual(len(allowlist["TASK-DATAENG-RTD-060"]), 64)  # hex sha256

    def test_main_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tasks_dir = tmp / "tasks"
            tasks_dir.mkdir()
            (tasks_dir / "TASK-DATAENG-RTD-900.json").write_text(
                json.dumps(_task(task_id="TASK-DATAENG-RTD-900")), encoding="utf-8"
            )
            (tasks_dir / "TASK-DATAENG-RTD-901.json").write_text(
                json.dumps(_task(task_id="TASK-DATAENG-RTD-901", domain="devops")),
                encoding="utf-8",
            )
            out = tmp / "proposal.json"
            code = self.mod.main([
                "--agentcollab-repo", str(tmp),
                "--metric", "rtd",
                "--min-agents", "1",
                "--out", str(out),
            ])
            self.assertEqual(code, 0)
            proposal = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(proposal["candidate_count"], 2)
            # Both fixtures are in an uncovered cell (novel task ids), so both
            # should be flagged as gap-fillers and carry a pinned sha256.
            self.assertEqual(proposal["uncovered_cell_candidates"], 2)
            ids = {c["task_id"] for c in proposal["candidates"]}
            self.assertEqual(ids, {"TASK-DATAENG-RTD-900", "TASK-DATAENG-RTD-901"})
            self.assertIn("TASK-DATAENG-RTD-900", proposal["ready_to_paste"])


if __name__ == "__main__":
    unittest.main()
