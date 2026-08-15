"""Offline tests for the RQ2 CPR annotation-worksheet extractor.

The extractor (scripts/extract_cpr_annotation_worksheet.py) turns a raw CPR
``lifecycle-trace.jsonl`` into a judge-ready worksheet. These tests drive its
pure ``build_worksheet`` over a minimal in-memory fixture — no ``outputs/``, no
real AgentCollabBench checkout.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "extract_cpr_annotation_worksheet.py"

_FALSE_FACT = "Snowflake needs manual B-tree indexes."
_GROUND_TRUTH = "Snowflake uses micro-partitions, not B-tree indexes."


def _load_script():
    spec = importlib.util.spec_from_file_location("extract_cpr_annotation_worksheet", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_trace(run_dir: Path) -> None:
    lines = [
        {"record_type": "run_manifest", "task_id": "TASK-DATAENG-CPR-999", "run_id": "run-x"},
        {"record_type": "injection", "corruption_type": "cpr", "target_agent_id": "A1"},
        # A1 asserts the false fact (textual reproduction -> surface-proxy note).
        {
            "record_type": "message",
            "source_agent_id": "A1",
            "target_agent_id": "A2",
            "sent_step": 1,
            "content": f"Per the spec: {_FALSE_FACT}",
        },
        {
            "record_type": "annotation",
            "taxonomy": "surface-proxy",
            "agent_id": "A1",
            "evidence_spans": [_FALSE_FACT],
        },
        # A2 quotes-then-rejects (still a textual reproduction).
        {
            "record_type": "message",
            "source_agent_id": "A2",
            "target_agent_id": "__output__",
            "sent_step": 2,
            "content": f"You wrote: {_FALSE_FACT} — that is wrong; {_GROUND_TRUTH}",
        },
        {
            "record_type": "annotation",
            "taxonomy": "surface-proxy",
            "agent_id": "A2",
            "evidence_spans": [_FALSE_FACT],
        },
        {
            "record_type": "outcome",
            "details": {
                "detailed_evaluation": {
                    "cpr_score": 1.0,
                    "turn_results": [
                        {"turn_index": 0, "agent_id": "A1", "polluted": True},
                        {"turn_index": 1, "agent_id": "A2", "polluted": False},
                    ],
                }
            },
        },
    ]
    (run_dir / "lifecycle-trace.jsonl").write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


class CprWorksheetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_script()

    def test_build_worksheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_trace(run_dir)
            task = {
                "task_id": "TASK-DATAENG-CPR-999",
                "injections": {
                    "cpr": {
                        "false_fact": _FALSE_FACT,
                        "ground_truth": _GROUND_TRUTH,
                        "seed_agent": "A1",
                    }
                },
            }
            worksheet = self.mod.build_worksheet(run_dir=run_dir, task=task)

        self.assertEqual(worksheet["task_id"], "TASK-DATAENG-CPR-999")
        self.assertEqual(worksheet["seed_agent"], "A1")
        self.assertEqual(worksheet["false_fact"], _FALSE_FACT)
        self.assertEqual(worksheet["ground_truth"], _GROUND_TRUTH)
        self.assertEqual(worksheet["keyword_cpr"], 1.0)

        self.assertEqual(len(worksheet["turns"]), 2)
        self.assertEqual(worksheet["turns"][0]["agent_id"], "A1")
        self.assertEqual(worksheet["turns"][1]["agent_id"], "A2")
        # Both agents textually surface the false fact; the semantic judgment
        # (adopted vs rejected) is left to the judge, not inferred here.
        self.assertTrue(all(t["surfaced_false_fact"] for t in worksheet["turns"]))
        self.assertTrue(all(t["semantic_stance"] is None for t in worksheet["turns"]))
        self.assertIsNone(worksheet["to_judge"]["final_outcome"])

    def test_turn_surfaced_is_literal_substring(self):
        self.assertEqual(
            self.mod._turn_surfaced(f"prefix {_FALSE_FACT} suffix", [_FALSE_FACT]),
            _FALSE_FACT,
        )
        self.assertIsNone(self.mod._turn_surfaced("nothing here", [_FALSE_FACT]))


if __name__ == "__main__":
    unittest.main()
