from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mas_error_lifecycle.analysis import bootstrap_mean, paired_mean_difference
from mas_error_lifecycle.design import load_plan, plan_summary


class DesignAnalysisTests(unittest.TestCase):
    def test_matrix_expansion_and_budget(self) -> None:
        content = """
[experiment]
name = "tiny"
tasks = ["a", "b"]
repeats = 2
base_seed = 10
estimated_backbone_calls_per_run = 3
estimated_judge_calls_per_run = 1

[factors]
topology = ["chain", "star"]
verification = ["none", "strict"]
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.toml"
            path.write_text(content, encoding="utf-8")
            items = load_plan(path)
        summary = plan_summary(items)
        self.assertEqual(summary["runs"], 16)
        self.assertEqual(summary["conditions"], 4)
        self.assertEqual(summary["estimated_backbone_calls"], 48)
        self.assertEqual([item.seed for item in items], list(range(10, 26)))

    def test_paired_difference(self) -> None:
        estimate = paired_mean_difference(
            {"a": 0.8, "b": 0.5, "c": 0.7},
            {"a": 0.5, "b": 0.4, "c": 0.5},
            resamples=500,
            seed=5,
        )
        self.assertEqual(estimate.n, 3)
        self.assertAlmostEqual(estimate.estimate, 0.2)
        self.assertLessEqual(estimate.lower, estimate.estimate)
        self.assertGreaterEqual(estimate.upper, estimate.estimate)

    def test_bootstrap_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            bootstrap_mean([])


if __name__ == "__main__":
    unittest.main()
