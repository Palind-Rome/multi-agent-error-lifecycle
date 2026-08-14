from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mas_error_lifecycle.metrics import compute_metrics
from mas_error_lifecycle.runner import MockRunConfig, run_mock
from mas_error_lifecycle.store import load_trace, write_trace


class RunnerMetricTests(unittest.TestCase):
    def test_no_verification_propagates_without_contaminating_source(self) -> None:
        bundle = run_mock(
            MockRunConfig(
                seed=1,
                topology="chain",
                verification="none",
                governance_action="none",
                adoption_probability=1.0,
                transmission_probability=1.0,
            )
        )
        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.possession_pair_count, 1)
        self.assertEqual(metrics.exposure_pair_count, 3)
        self.assertEqual(metrics.adoption_pair_count, 3)
        self.assertEqual(metrics.transport_delivery_rate, 1.0)
        self.assertEqual(metrics.artifact_survival_given_delivery, 1.0)
        self.assertEqual(metrics.adoption_given_exposure, 1.0)
        self.assertEqual(metrics.post_verification_given_adoption, 0.0)
        self.assertIsNone(metrics.detection_given_completed_verification)
        self.assertEqual(metrics.finite_window_secondary_adoption_count, 3.0)
        self.assertEqual(metrics.max_adoption_hop, 3)
        self.assertFalse(metrics.task_success)
        self.assertEqual(metrics.final_contaminated_agents, 3)

    def test_correct_post_verification_and_rollback_recovers(self) -> None:
        bundle = run_mock(
            MockRunConfig(
                seed=2,
                topology="chain",
                verification="evidence_required",
                verification_timing="post_adoption",
                governance_action="rollback",
                adoption_probability=1.0,
                verification_probability=1.0,
                verification_accuracy=1.0,
            )
        )
        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.exposure_pair_count, 1)
        self.assertEqual(metrics.adoption_given_exposure, 1.0)
        self.assertEqual(metrics.post_verification_given_adoption, 1.0)
        self.assertEqual(metrics.detection_given_completed_verification, 1.0)
        self.assertEqual(metrics.recovery_given_detection, 1.0)
        self.assertEqual(metrics.rollback_pair_count, 1)
        self.assertTrue(metrics.task_success)
        self.assertEqual(metrics.final_contaminated_agents, 0)

    def test_detection_only_does_not_silently_block_propagation(self) -> None:
        metrics = compute_metrics(
            run_mock(
                MockRunConfig(
                    seed=3,
                    topology="chain",
                    verification="evidence_required",
                    verification_timing="post_adoption",
                    governance_action="none",
                    adoption_probability=1.0,
                    verification_probability=1.0,
                    verification_accuracy=1.0,
                )
            )
        )
        self.assertEqual(metrics.detection_pair_count, 3)
        self.assertEqual(metrics.recovery_pair_count, 0)
        self.assertEqual(metrics.final_contaminated_agents, 3)
        self.assertFalse(metrics.task_success)

    def test_possession_without_source_surfacing_is_not_contamination(self) -> None:
        metrics = compute_metrics(
            run_mock(
                MockRunConfig(
                    seed=4,
                    topology="chain",
                    verification="none",
                    governance_action="none",
                    source_surfacing_probability=0.0,
                    adoption_probability=1.0,
                )
            )
        )
        self.assertEqual(metrics.possession_pair_count, 1)
        self.assertEqual(metrics.surfacing_pair_count, 0)
        self.assertEqual(metrics.message_artifact_attempt_count, 0)
        self.assertEqual(metrics.adoption_pair_count, 0)
        self.assertEqual(metrics.final_contaminated_agents, 0)

    def test_pre_verification_containment_prevents_adoption(self) -> None:
        metrics = compute_metrics(
            run_mock(
                MockRunConfig(
                    seed=5,
                    topology="chain",
                    verification="evidence_required",
                    verification_timing="pre_adoption",
                    governance_action="contain",
                    adoption_probability=1.0,
                    verification_probability=1.0,
                    verification_accuracy=1.0,
                )
            )
        )
        self.assertEqual(metrics.exposure_pair_count, 1)
        self.assertEqual(metrics.pre_verification_given_exposure, 1.0)
        self.assertEqual(metrics.adoption_pair_count, 0)
        self.assertEqual(metrics.containment_pair_count, 1)
        self.assertEqual(metrics.final_contaminated_agents, 0)

    def test_explicit_rejection_is_measured_zero_not_missing_annotation(self) -> None:
        metrics = compute_metrics(
            run_mock(
                MockRunConfig(
                    seed=15,
                    topology="chain",
                    verification="none",
                    governance_action="none",
                    adoption_probability=0.0,
                    transmission_probability=1.0,
                )
            )
        )
        self.assertEqual(metrics.exposure_pair_count, 1)
        self.assertEqual(metrics.adoption_event_count, 0)
        self.assertEqual(metrics.adoption_annotation_count, 1)
        self.assertEqual(metrics.adoption_rate_denominator_count, 1)
        self.assertEqual(metrics.adoption_annotation_coverage, 1.0)
        self.assertEqual(metrics.adoption_given_exposure, 0.0)
        self.assertEqual(metrics.final_contamination_annotation_coverage, 1.0)
        self.assertEqual(metrics.final_contaminated_agents, 0)

    def test_relapse_is_distinct_from_recovery(self) -> None:
        metrics = compute_metrics(
            run_mock(
                MockRunConfig(
                    seed=6,
                    topology="chain",
                    verification="evidence_required",
                    governance_action="rollback",
                    adoption_probability=1.0,
                    verification_probability=1.0,
                    verification_accuracy=1.0,
                    relapse_probability=1.0,
                )
            )
        )
        self.assertEqual(metrics.recovery_pair_count, 3)
        self.assertEqual(metrics.relapse_pair_count, 3)
        self.assertEqual(metrics.final_contaminated_agents, 3)

    def test_jsonl_round_trip(self) -> None:
        bundle = run_mock(MockRunConfig(seed=7))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            write_trace(path, bundle)
            loaded = load_trace(path)
        self.assertEqual(loaded, bundle)


if __name__ == "__main__":
    unittest.main()
