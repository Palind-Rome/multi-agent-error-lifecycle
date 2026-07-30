from __future__ import annotations

import unittest
from dataclasses import replace

from mas_error_lifecycle.annotation import calibrate_multilabel
from mas_error_lifecycle.metrics import (
    AttestationCase,
    compute_metrics,
    summarize_attestations,
)
from mas_error_lifecycle.runner import MockRunConfig, run_mock
from mas_error_lifecycle.schema import (
    ArtifactKind,
    ArtifactOrigin,
    ArtifactRecord,
    AttestationRecord,
    AttestationStatus,
    AttestationVerdict,
    EvidenceRecord,
    EvidenceValidity,
    EventType,
    LifecycleEvent,
    ToolCallRecord,
    ToolCallStatus,
    TruthStatus,
    record_from_dict,
    text_sha256,
)


class RecordAndAnnotationTests(unittest.TestCase):
    def test_teambench_attestation_views_preserve_missingness(self) -> None:
        cases = (
            [AttestationCase(AttestationStatus.VALID, AttestationVerdict.PASS, True)]
            * 285
            + [
                AttestationCase(
                    AttestationStatus.VALID, AttestationVerdict.PASS, False
                )
            ]
            * 384
            + [
                AttestationCase(
                    AttestationStatus.VALID, AttestationVerdict.FAIL, True
                )
            ]
            * 20
            + [
                AttestationCase(
                    AttestationStatus.VALID, AttestationVerdict.FAIL, False
                )
            ]
            * 394
            + [AttestationCase(AttestationStatus.MISSING, None, False)] * 942
        )
        metrics = summarize_attestations(cases)
        self.assertEqual(metrics.total, 2025)
        self.assertEqual(metrics.valid, 1083)
        self.assertAlmostEqual(metrics.conditional_false_accept_rate or 0, 384 / 778)
        self.assertAlmostEqual(metrics.conditional_false_reject_rate or 0, 20 / 305)
        self.assertAlmostEqual(
            metrics.missing_as_fail_false_accept_rate or 0,
            384 / (778 + 942),
        )
        self.assertAlmostEqual(
            metrics.verifier_system_failure_rate or 0,
            (942 + 384 + 20) / 2025,
        )

    def test_attestation_status_round_trip(self) -> None:
        valid = AttestationRecord(
            attestation_id="a",
            run_id="r",
            verifier_agent_id="v",
            step=1,
            status=AttestationStatus.VALID,
            verdict=AttestationVerdict.PASS,
            raw_sha256=text_sha256("PASS"),
        )
        loaded = record_from_dict(valid.to_dict())
        self.assertEqual(loaded, valid)
        missing = replace(
            valid,
            status=AttestationStatus.MISSING,
            verdict=None,
            raw_sha256=None,
        )
        missing.validate()

    def test_multilabel_calibration_reports_confusion(self) -> None:
        report = calibrate_multilabel(
            {
                "t1": {"FM-3.2", "FM-1.1"},
                "t2": {"FM-3.3"},
                "t3": set(),
            },
            {
                "t1": {"FM-3.2"},
                "t2": {"FM-3.3", "FM-1.1"},
                "t3": set(),
            },
        )
        self.assertEqual(report.examples, 3)
        self.assertEqual(report.labels, 3)
        self.assertAlmostEqual(report.exact_match_accuracy, 1 / 3)
        self.assertIsNotNone(report.micro_f1)

    def test_tool_call_failures_remain_separate_from_success(self) -> None:
        bundle = run_mock(
            MockRunConfig(seed=31, verification="none", governance_action="none")
        )
        artifact_id = bundle.artifacts[0].artifact_id
        calls = (
            ToolCallRecord(
                tool_call_id="tool-1",
                run_id=bundle.manifest.run_id,
                agent_id="branch-1",
                step=3,
                tool_name="shell",
                status=ToolCallStatus.PARSE_ERROR,
                arguments_sha256=text_sha256("{bad"),
                authorized=None,
                error_type="malformed_json",
                depends_on_artifact_ids=(artifact_id,),
            ),
            ToolCallRecord(
                tool_call_id="tool-2",
                run_id=bundle.manifest.run_id,
                agent_id="branch-1",
                step=4,
                tool_name="shell",
                status=ToolCallStatus.SUCCESS,
                arguments_sha256=text_sha256("{}"),
                authorized=True,
                result_sha256=text_sha256("ok"),
                depends_on_artifact_ids=(artifact_id,),
            ),
        )
        metrics = compute_metrics(replace(bundle, tool_calls=calls))
        self.assertEqual(metrics.tool_call_count, 2)
        self.assertEqual(metrics.tool_schema_valid_rate, 0.5)
        self.assertEqual(metrics.tool_execution_success_rate, 1.0)

    def test_commitment_fulfillment_requires_typed_artifact_and_evidence(self) -> None:
        bundle = run_mock(
            MockRunConfig(seed=32, verification="none", governance_action="none")
        )
        old_final = bundle.events[-1]
        base_step = bundle.events[-2].step
        commitment = ArtifactRecord(
            artifact_id="commitment:patch-api",
            run_id=bundle.manifest.run_id,
            source_agent_id="root",
            created_step=base_step + 1,
            truth_status=TruthStatus.UNKNOWN,
            content="I will implement the API endpoint.",
            origin=ArtifactOrigin.USER_ASSERTION,
            kind=ArtifactKind.COMMITMENT,
            origin_actor_id="root",
        )
        proof = EvidenceRecord(
            evidence_id="evidence:patch",
            run_id=bundle.manifest.run_id,
            kind="patch_and_test",
            created_step=base_step + 3,
            validity=EvidenceValidity.VALID,
            artifact_id=commitment.artifact_id,
            producer_agent_id="root",
            source="git-diff-and-tests",
            stdout_sha256=text_sha256("tests passed"),
            independent=True,
        )
        possessed = LifecycleEvent(
            event_id="event-commit-possession",
            run_id=bundle.manifest.run_id,
            event_type=EventType.ARTIFACT_POSSESSED,
            step=base_step + 1,
            timestamp=old_final.timestamp,
            agent_id="root",
            artifact_id=commitment.artifact_id,
            details={"turn_index": 3, "observation": "user_commitment"},
        )
        made = LifecycleEvent(
            event_id="event-commit-made",
            run_id=bundle.manifest.run_id,
            event_type=EventType.COMMITMENT_MADE,
            step=base_step + 2,
            timestamp=old_final.timestamp,
            agent_id="root",
            artifact_id=commitment.artifact_id,
            parent_event_ids=(possessed.event_id,),
            details={"turn_index": 3, "acceptance_criterion": "tests pass"},
        )
        fulfilled = LifecycleEvent(
            event_id="event-commit-fulfilled",
            run_id=bundle.manifest.run_id,
            event_type=EventType.COMMITMENT_FULFILLED,
            step=base_step + 3,
            timestamp=old_final.timestamp,
            agent_id="root",
            artifact_id=commitment.artifact_id,
            parent_event_ids=(made.event_id,),
            details={"turn_index": 3, "evidence_ids": [proof.evidence_id]},
        )
        final = replace(
            old_final,
            step=base_step + 4,
            parent_event_ids=(fulfilled.event_id,),
        )
        extended = replace(
            bundle,
            artifacts=(*bundle.artifacts, commitment),
            evidence=(*bundle.evidence, proof),
            events=(*bundle.events[:-1], possessed, made, fulfilled, final),
            outcome=replace(bundle.outcome, final_step=final.step),
        )
        extended.validate()
        metrics = compute_metrics(extended)
        self.assertEqual(metrics.commitment_made_count, 1)
        self.assertEqual(metrics.commitment_fulfilled_count, 1)


if __name__ == "__main__":
    unittest.main()
