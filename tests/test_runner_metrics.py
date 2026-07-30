from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mas_error_lifecycle.metrics import compute_metrics
from mas_error_lifecycle.runner import MockRunConfig, run_mock
from mas_error_lifecycle.store import load_trace, write_trace


class RunnerMetricTests(unittest.TestCase):
    def test_no_verification_chain_propagates_to_leaf(self) -> None:
        bundle = run_mock(
            MockRunConfig(
                seed=1,
                topology="chain",
                verification="none",
                adoption_probability=1.0,
                transmission_probability=1.0,
            )
        )
        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.exposure_pair_count, 3)
        self.assertEqual(metrics.adoption_pair_count, 3)
        self.assertEqual(metrics.transport_delivery_rate, 1.0)
        self.assertEqual(metrics.edge_transmission_rate, 1.0)
        self.assertEqual(metrics.adoption_given_exposure, 1.0)
        self.assertEqual(metrics.verification_given_adoption, 0.0)
        self.assertIsNone(metrics.detection_given_verification)
        self.assertEqual(metrics.effective_error_reproduction_number, 1.0)
        self.assertEqual(metrics.max_adoption_hop, 3)
        self.assertFalse(metrics.task_success)
        self.assertEqual(metrics.final_contaminated_agents, 4)

    def test_correct_verification_recovers_before_next_hop(self) -> None:
        bundle = run_mock(
            MockRunConfig(
                seed=2,
                topology="chain",
                verification="evidence_required",
                adoption_probability=1.0,
                verification_probability=1.0,
                verification_accuracy=1.0,
            )
        )
        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.exposure_pair_count, 1)
        self.assertEqual(metrics.adoption_given_exposure, 1.0)
        self.assertEqual(metrics.verification_given_adoption, 1.0)
        self.assertEqual(metrics.detection_given_verification, 1.0)
        self.assertEqual(metrics.recovery_given_detection, 1.0)
        self.assertTrue(metrics.task_success)
        self.assertEqual(metrics.final_contaminated_agents, 1)

    def test_jsonl_round_trip(self) -> None:
        bundle = run_mock(MockRunConfig(seed=3))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            write_trace(path, bundle)
            loaded = load_trace(path)
        self.assertEqual(loaded.manifest, bundle.manifest)
        self.assertEqual(loaded.artifacts, bundle.artifacts)
        self.assertEqual(loaded.prompts, bundle.prompts)
        self.assertEqual(loaded.events, bundle.events)
        self.assertEqual(loaded.outcome, bundle.outcome)


if __name__ == "__main__":
    unittest.main()
