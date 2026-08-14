from __future__ import annotations

import unittest

from mas_error_lifecycle.rq1 import extract_rq1_transformations, validate_rq1_arm_set
from mas_error_lifecycle.rq1_runner import (
    RQ1FixtureManifest,
    RQ1_REAL_BENCHMARK_ID,
    RealCallEvidence,
    run_rq1_three_arm_calibration,
)
from mas_error_lifecycle.schema import RQ1TransformationArm


_FACTS = (
    ("fact-region", "Deployment region is eu-west-1."),
    ("fact-retention", "Retention period is 14 days."),
    ("fact-backup", "Never delete backups before validation."),
    ("fact-schema", "Required schema version is 7."),
    ("fact-owner", "Owning team is platform."),
    ("fact-port", "Service port is 8443."),
)
_DISTRACTORS = (
    ("distractor-request", "Synthetic request identifier is SYN-42."),
    ("distractor-shard", "Diagnostic log shard is alpha."),
    ("distractor-color", "Debug display color is amber."),
    ("distractor-retry", "Fixture retry counter is 2."),
    ("distractor-timezone", "Annotation timezone note is UTC."),
    ("distractor-checksum", "Checksum label is DEMO."),
)
_SOURCE_TEXT = " ".join(
    text for _, text in (*_FACTS, *_DISTRACTORS)
)
_REFERENCE_TEXT = (
    "Use eu-west-1; retain 14 days; never delete backups before validation; "
    "schema version 7; owner platform; port 8443."
)
_MODEL = "qwen/qwen3-30b-a3b-instruct-2507"
_PROVIDER = "openai-compatible"


def _manifest() -> RQ1FixtureManifest:
    return RQ1FixtureManifest(
        fixture_id="rq1-fixture-test-v1",
        task_id="apply-deployment-policy-test-v1",
        source_text=_SOURCE_TEXT,
        required_facts=_FACTS,
        distractors=_DISTRACTORS,
        reference_text=_REFERENCE_TEXT,
        downstream_prompt_template="Apply this tool result:\n{transformed_text}",
        char_budget=400,
        token_budget=80,
    )


def _stub_call(messages, max_tokens):
    if messages[0]["role"] == "system":
        return RealCallEvidence(
            content=(
                "Use the EU region with 14-day retention; owner platform; "
                "port 8443."
            ),
            provider=_PROVIDER,
            model=_MODEL,
            input_tokens=120,
            output_tokens=30,
            cost_usd=0.0001,
        )
    return RealCallEvidence(
        content="downstream structured answer",
        provider=_PROVIDER,
        model=_MODEL,
        input_tokens=60,
        output_tokens=12,
        cost_usd=0.00005,
    )


class RQ1RunnerTests(unittest.TestCase):
    def test_three_arms_build_and_validate(self) -> None:
        bundles = run_rq1_three_arm_calibration(
            manifest=_manifest(),
            call=_stub_call,
            run_id_base="rq1-real-test",
            repeat_id="repeat-001",
            block_id="block-001",
            started_at="2026-08-15T00:00:00Z",
            model=_MODEL,
            model_version="qwen3-30b-a3b-2507",
            producer_system_prompt=(
                "Summarize the tool result for a downstream teammate, "
                "preserving every factual detail."
            ),
            context_token_cap=100_000,
            downstream_output_token_cap=4_096,
            producer_output_token_cap=4_096,
        )

        self.assertEqual(len(bundles), 3)
        arms = [b.manifest.condition_id for b in bundles]
        self.assertEqual(
            set(arms),
            {arm.value for arm in RQ1TransformationArm},
        )

        rows = [
            row
            for bundle in bundles
            for row in extract_rq1_transformations(bundle)
        ]
        validate_rq1_arm_set(rows)

        for bundle in bundles:
            self.assertTrue(bundle.manifest.analysis_eligible is False)
            self.assertEqual(bundle.manifest.purpose, "engineering_smoke")
            self.assertEqual(bundle.manifest.benchmark, RQ1_REAL_BENCHMARK_ID)
            self.assertEqual(bundle.manifest.suite_kind, "derived")
            # Only the transformation contract annotation is present; no
            # semantic fact annotations may be auto-generated.
            self.assertTrue(
                all(
                    annotation.taxonomy != "rq1-required-fact"
                    for annotation in bundle.annotations
                )
            )
            self.assertTrue(
                any(
                    annotation.taxonomy == "rq1-transformation"
                    for annotation in bundle.annotations
                )
            )
            # api_called must be recorded truthfully on the contract and calls.
            for call in bundle.model_calls:
                self.assertTrue(call.metadata.get("api_called") is True)
                self.assertEqual(call.provider, _PROVIDER)

    def test_abstractive_summary_arm_has_producer_call(self) -> None:
        bundles = run_rq1_three_arm_calibration(
            manifest=_manifest(),
            call=_stub_call,
            run_id_base="rq1-real-test-t",
            repeat_id="repeat-001",
            block_id="block-001",
            started_at="2026-08-15T00:00:00Z",
            model=_MODEL,
            model_version="qwen3-30b-a3b-2507",
            producer_system_prompt="summarize",
            context_token_cap=100_000,
            downstream_output_token_cap=4_096,
            producer_output_token_cap=4_096,
        )
        by_arm = {b.manifest.condition_id: b for b in bundles}
        treatment = by_arm[RQ1TransformationArm.ABSTRACTIVE_SUMMARY.value]
        self.assertEqual(len(treatment.model_calls), 2)
        self.assertTrue(any(call.agent_id == "source" for call in treatment.model_calls))
        producer = next(c for c in treatment.model_calls if c.agent_id == "source")
        self.assertIn("provider_completion_tokens", producer.metadata)
        self.assertEqual(producer.metadata["provider_completion_tokens"], 30)

        raw = by_arm[RQ1TransformationArm.RAW_PASSTHROUGH.value]
        self.assertEqual(len(raw.model_calls), 1)

    def test_manifest_rejects_budget_violations(self) -> None:
        manifest = _manifest()
        with self.assertRaises(ValueError):
            RQ1FixtureManifest(
                fixture_id=manifest.fixture_id,
                task_id=manifest.task_id,
                source_text=manifest.source_text,
                required_facts=manifest.required_facts,
                distractors=manifest.distractors,
                reference_text="short",
                downstream_prompt_template=manifest.downstream_prompt_template,
                char_budget=4,
                token_budget=1,
            )

    def test_summary_over_budget_is_rejected(self) -> None:
        def long_summary(messages, max_tokens):
            if messages[0]["role"] == "system":
                return RealCallEvidence(
                    content=" ".join(f"word{i}" for i in range(200)),
                    provider=_PROVIDER,
                    model=_MODEL,
                    input_tokens=120,
                    output_tokens=300,
                )
            return RealCallEvidence(
                content="answer",
                provider=_PROVIDER,
                model=_MODEL,
                input_tokens=10,
                output_tokens=2,
            )

        with self.assertRaises(ValueError):
            run_rq1_three_arm_calibration(
                manifest=_manifest(),
                call=long_summary,
                run_id_base="rq1-real-overbudget",
                repeat_id="repeat-001",
                block_id="block-001",
                started_at="2026-08-15T00:00:00Z",
                model=_MODEL,
                model_version="qwen3-30b-a3b-2507",
                producer_system_prompt="summarize",
                context_token_cap=100_000,
                downstream_output_token_cap=4_096,
                producer_output_token_cap=4_096,
            )


if __name__ == "__main__":
    unittest.main()
