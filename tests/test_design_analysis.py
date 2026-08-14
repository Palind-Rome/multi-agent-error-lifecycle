from __future__ import annotations

import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

from mas_error_lifecycle.analysis import (
    bootstrap_mean,
    descriptive_mean,
    paired_cluster_mean_difference,
    paired_mean_difference,
)
from mas_error_lifecycle.design import load_plan, plan_summary


class DesignAnalysisTests(unittest.TestCase):
    def test_matrix_uses_paired_seed_and_separate_run_order(self) -> None:
        content = """
[experiment]
benchmark_plugin = "fake.contract"
plugin_version = "1.0.0"
raw_schema_version = "fake.raw.v1"
name = "tiny"
purpose = "engineering_smoke"
protocol_kind = "test_native"
suite_kind = "native"
execution_status = "ready"
review_status = "native"
analysis_eligible = false
tasks = ["a", "b"]
repeats = 2
base_seed = 10
run_order_seed = 99
estimated_backbone_calls_per_run = 3
estimated_judge_calls_per_run = 1

[factors]
topology = ["chain", "broadcast_star"]
verification = ["none", "strict"]

[factor_bindings]
topology = "derived_topology_rewriter"
verification = "governance_policy"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.toml"
            path.write_text(content, encoding="utf-8")
            items = load_plan(path)
        summary = plan_summary(items)
        self.assertEqual({item.plan_version for item in items}, {"0.3.0"})
        self.assertEqual(summary["runs"], 16)
        self.assertEqual(summary["conditions"], 4)
        self.assertEqual(summary["pairs"], 4)
        self.assertEqual(summary["estimated_backbone_calls"], 48)
        by_pair: dict[str, list[object]] = defaultdict(list)
        for item in items:
            by_pair[item.pair_id].append(item)
        self.assertTrue(
            all(len({item.seed for item in rows}) == 1 for rows in by_pair.values())
        )
        self.assertTrue(all(len(rows) == 4 for rows in by_pair.values()))
        self.assertEqual(
            sorted(item.run_order for item in items), list(range(len(items)))
        )
        self.assertEqual(len({item.run_id for item in items}), len(items))

    def test_native_smoke_is_12_blocked_unmodified_assignments(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = root / "configs" / "pilot.toml"
        with self.assertRaisesRegex(ValueError, "blocked"):
            load_plan(config)
        items = load_plan(config, allow_unready=True)
        self.assertEqual(len(items), 12)
        self.assertEqual({item.protocol_kind for item in items}, {"agentcollab_native"})
        self.assertEqual({item.analysis_eligible for item in items}, {False})
        self.assertEqual({item.execution_status for item in items}, {"blocked"})
        self.assertEqual(
            {item.benchmark_plugin for item in items},
            {"agentcollabbench.native"},
        )
        self.assertEqual(
            {item.factors["protocol_variant"] for item in items},
            {"native_untouched_homogeneous_no_added_verifier"},
        )

    def test_execution_contract_fields_are_required(self) -> None:
        content = """
[experiment]
name = "missing-plugin-contract"
purpose = "engineering_smoke"
protocol_kind = "test_native"
suite_kind = "native"
execution_status = "ready"
review_status = "native"
analysis_eligible = false
tasks = ["a"]

[factors]
protocol_variant = ["native"]

[factor_bindings]
protocol_variant = "native_task_passthrough"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing-plugin.toml"
            path.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "benchmark_plugin"):
                load_plan(path)

    def test_unknown_review_status_is_rejected_even_for_preview(self) -> None:
        content = """
[experiment]
benchmark_plugin = "fake.contract"
plugin_version = "1.0.0"
raw_schema_version = "fake.raw.v1"
name = "bad-review-status"
purpose = "engineering_smoke"
protocol_kind = "test_native"
suite_kind = "native"
execution_status = "ready"
review_status = "unvalidate"
analysis_eligible = false
tasks = ["a"]

[factors]
protocol_variant = ["native"]

[factor_bindings]
protocol_variant = "native_task_passthrough"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-review.toml"
            path.write_text(content, encoding="utf-8")
            for allow_unready in (False, True):
                with self.subTest(allow_unready=allow_unready):
                    with self.assertRaisesRegex(ValueError, "review_status is invalid"):
                        load_plan(path, allow_unready=allow_unready)

    def test_paused_derived_plan_is_refused_by_default(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / "configs" / "derived-topology-stress.paused.toml"
        with self.assertRaisesRegex(ValueError, "paused"):
            load_plan(path)
        preview = load_plan(path, allow_unready=True)
        self.assertEqual(len(preview), 144)
        self.assertTrue(all(item.execution_status == "paused" for item in preview))
        self.assertTrue(all(not item.analysis_eligible for item in preview))

    def test_paired_difference_refuses_missing_cell(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing cells"):
            paired_mean_difference(
                {"a": 0.8, "b": 0.5},
                {"a": 0.5},
                resamples=500,
            )

    def test_paired_cluster_bootstrap_uses_cluster_as_unit(self) -> None:
        estimate = paired_cluster_mean_difference(
            {"pool-a": [0.8] * 100, "pool-b": [0.4]},
            {"pool-a": [0.5] * 100, "pool-b": [0.2]},
            resamples=500,
            seed=5,
        )
        self.assertEqual(estimate.n, 2)
        self.assertAlmostEqual(estimate.estimate, 0.25)

    def test_singleton_is_descriptive_not_inferential(self) -> None:
        with self.assertRaisesRegex(ValueError, "two independent clusters"):
            bootstrap_mean([0.5])
        estimate = descriptive_mean([0.5])
        self.assertFalse(estimate.inference_eligible)
        self.assertEqual(estimate.estimate, 0.5)

    def test_paired_difference(self) -> None:
        estimate = paired_mean_difference(
            {"a": 0.8, "b": 0.5, "c": 0.7},
            {"a": 0.5, "b": 0.4, "c": 0.5},
            resamples=500,
            seed=5,
        )
        self.assertEqual(estimate.n, 3)
        self.assertAlmostEqual(estimate.estimate, 0.2)

    def test_bootstrap_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            bootstrap_mean([])


if __name__ == "__main__":
    unittest.main()
