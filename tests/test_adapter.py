from __future__ import annotations

import copy
import unittest
from dataclasses import dataclass

from mas_error_lifecycle.adapters import (
    AgentCollabEvaluation,
    convert_agentcollab_result,
    generate_agentcollab_derived_counterfactual,
)
from mas_error_lifecycle.metrics import compute_metrics
from mas_error_lifecycle.schema import EventType


def _base_task() -> dict:
    return {
        "task_id": "T",
        "description": "held fixed",
        "topology": {
            "type": "linear_chain",
            "speaking_order": ["A", "B", "C", "D"],
            "agents": [
                {
                    "agent_id": "A",
                    "role": "a",
                    "system_prompt": "pa",
                    "receives_from": [],
                },
                {
                    "agent_id": "B",
                    "role": "b",
                    "system_prompt": "pb",
                    "receives_from": ["A"],
                },
                {
                    "agent_id": "C",
                    "role": "c",
                    "system_prompt": "pc",
                    "receives_from": ["B"],
                },
                {
                    "agent_id": "D",
                    "role": "d",
                    "system_prompt": "pd",
                    "receives_from": ["C"],
                },
            ],
            "edges": [["A", "B"], ["B", "C"], ["C", "D"]],
        },
        "injections": {
            "cpr": {
                "seed_agent": "B",
                "false_fact": "The input is JSON.",
                "ground_truth": "The input is CSV.",
            }
        },
    }


def _cpr_payload(*, include_provider_request: bool = True) -> dict:
    false_fact = "The input is JSON."
    provider_requests = (
        [
            {
                "call_id": "call-b-1",
                "agent_id": "B",
                "provider": "mock",
                "model": "m",
                "messages": [
                    {"role": "system", "content": "sink"},
                    {"role": "user", "content": f"Parent claims: {false_fact}"},
                ],
                "response_content": f"I will use it. {false_fact}",
                "input_tokens": 12,
                "output_tokens": 6,
                "status": "success",
            }
        ]
        if include_provider_request
        else []
    )
    return {
        "task_id": "TASK-CPR-TEST",
        "scores": {"cpr": 0.5},
        "errors": {},
        "run_result": {
            "task_id": "TASK-CPR-TEST",
            "scenario": {
                "task_id": "TASK-CPR-TEST",
                "metric_applicability": ["cpr"],
                "topology": {
                    "type": "linear_chain",
                    "agents": [
                        {
                            "agent_id": "A",
                            "role": "source",
                            "system_prompt": "source",
                            "receives_from": [],
                        },
                        {
                            "agent_id": "B",
                            "role": "sink",
                            "system_prompt": "sink",
                            "receives_from": ["A"],
                        },
                    ],
                    "edges": [["A", "B"]],
                },
                "injections": {
                    "cpr": {
                        "false_fact": false_fact,
                        "ground_truth": "The input is CSV.",
                        "seed_agent": "A",
                    }
                },
            },
            "output": {"result": f"B repeats: {false_fact}"},
            "trace": {
                "turns": [
                    {"agent_id": "A", "content": false_fact},
                    {"agent_id": "B", "content": f"I will use it. {false_fact}"},
                ],
                "handoffs": [
                    {
                        "sender": "A",
                        "receiver": "B",
                        "content": false_fact,
                        "timestamp": 1.0,
                    },
                    {
                        "sender": "B",
                        "receiver": "__output__",
                        "content": f"I will use it. {false_fact}",
                        "timestamp": 2.0,
                    },
                ],
                "api_calls": [
                    {
                        "agent_id": "A",
                        "provider": "mock",
                        "model": "m",
                        "input_tokens": 10,
                        "output_tokens": 4,
                    },
                    {
                        "agent_id": "B",
                        "provider": "mock",
                        "model": "m",
                        "input_tokens": 12,
                        "output_tokens": 6,
                    },
                ],
                "provider_requests": provider_requests,
            },
        },
    }


class AgentCollabAdapterTests(unittest.TestCase):
    def test_evaluation_payload_normalizes_upstream_dataclasses(self) -> None:
        @dataclass
        class Detail:
            score: float
            labels: tuple[str, ...]

        class Result:
            def to_dict(self) -> dict:
                return {"task_id": "T", "value": float("nan")}

        payload = AgentCollabEvaluation(
            task_id="T",
            metric="cpr",
            score=0.5,
            detailed=Detail(score=0.5, labels=("polluted",)),
            run_result=Result(),
        ).to_adapter_payload()
        self.assertEqual(
            payload["detailed"],
            {"score": 0.5, "labels": ["polluted"]},
        )
        self.assertIsNone(payload["run_result"]["value"])

    def test_derived_generator_cannot_masquerade_as_native(self) -> None:
        task = _base_task()
        original = copy.deepcopy(task)
        rewritten = generate_agentcollab_derived_counterfactual(
            task, "converging_dag"
        )
        self.assertEqual(task, original)
        self.assertEqual(rewritten["topology"]["speaking_order"][0], "B")
        self.assertEqual(
            rewritten["topology"]["edges"],
            [["B", "A"], ["B", "C"], ["A", "D"], ["C", "D"]],
        )
        metadata = rewritten["experimental_metadata"]
        self.assertEqual(
            metadata["protocol_kind"], "agentcollab_derived_counterfactual"
        )
        self.assertFalse(metadata["analysis_eligible"])
        self.assertFalse(metadata["native_score_export_allowed"])
        self.assertEqual(metadata["review_status"], "unvalidated")

    def test_exact_marker_is_surface_proxy_not_primary_adoption(self) -> None:
        bundle = convert_agentcollab_result(_cpr_payload())
        metrics = compute_metrics(bundle)
        self.assertIsNone(metrics.task_success)
        self.assertIsNone(metrics.task_score)
        self.assertEqual(metrics.input_tokens, 22)
        self.assertEqual(metrics.output_tokens, 10)
        self.assertEqual(metrics.exposure_pair_count, 1)
        self.assertEqual(metrics.adoption_pair_count, 0)
        self.assertGreaterEqual(metrics.textual_reproduction_count, 2)
        self.assertFalse(bundle.manifest.analysis_eligible)
        self.assertIsNone(bundle.manifest.seed)
        self.assertTrue(
            all(
                event.event_type != EventType.ARTIFACT_ADOPTED
                for event in bundle.events
            )
        )
        self.assertTrue(
            all(
                event.details.get("semantic_fidelity") is None
                for event in bundle.events
                if event.event_type == EventType.ARTIFACT_SURFACED
            )
        )

    def test_handoff_without_actual_request_is_not_exposure(self) -> None:
        bundle = convert_agentcollab_result(
            _cpr_payload(include_provider_request=False)
        )
        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.message_artifact_delivery_count, 2)
        self.assertEqual(metrics.message_artifact_survival_count, 2)
        self.assertEqual(metrics.exposure_opportunity_count, 0)
        self.assertEqual(metrics.adoption_pair_count, 0)

    def test_rtd_receipt_without_emission_is_an_omission(self) -> None:
        tracer = "TRACE_123"
        payload = {
            "run_result": {
                "task_id": "TASK-RTD-TEST",
                "scenario": {
                    "task_id": "TASK-RTD-TEST",
                    "metric_applicability": ["rtd"],
                    "topology": {
                        "type": "linear_chain",
                        "agents": [
                            {
                                "agent_id": "A",
                                "role": "source",
                                "system_prompt": "source",
                                "receives_from": [],
                            },
                            {
                                "agent_id": "B",
                                "role": "sink",
                                "system_prompt": "sink",
                                "receives_from": ["A"],
                            },
                        ],
                        "edges": [["A", "B"]],
                    },
                    "injections": {
                        "rtd": {
                            "tracer_id": tracer,
                            "anchor": "ordinary natural-language anchor",
                        }
                    },
                },
                "output": {"result": "ordinary answer"},
                "trace": {
                    "turns": [
                        {"agent_id": "A", "content": "ordinary answer"},
                        {"agent_id": "B", "content": "ordinary answer"},
                    ],
                    "handoffs": [
                        {
                            "sender": "A",
                            "receiver": "B",
                            "content": "ordinary answer",
                        }
                    ],
                    "api_calls": [],
                    "provider_requests": [
                        {
                            "call_id": "b",
                            "agent_id": "B",
                            "provider": "mock",
                            "model": "m",
                            "messages": [
                                {"role": "user", "content": "ordinary answer"}
                            ],
                            "status": "success",
                        }
                    ],
                },
            }
        }
        metrics = compute_metrics(convert_agentcollab_result(payload))
        self.assertEqual(metrics.true_artifact_count, 1)
        self.assertEqual(metrics.required_information_count, 1)
        self.assertEqual(metrics.required_information_surfaced_count, 0)
        self.assertEqual(metrics.required_information_surfacing_rate, 0.0)
        self.assertEqual(metrics.adoption_pair_count, 0)
        self.assertEqual(metrics.final_contaminated_agents, 0)

    def test_derived_result_has_separate_benchmark_identity(self) -> None:
        task = generate_agentcollab_derived_counterfactual(
            _base_task(), "converging_dag"
        )
        payload = _cpr_payload()
        payload["run_result"]["scenario"]["experimental_metadata"] = task[
            "experimental_metadata"
        ]
        bundle = convert_agentcollab_result(payload)
        self.assertEqual(bundle.manifest.benchmark, "AgentCollabBench-derived")
        self.assertEqual(
            bundle.manifest.protocol_kind,
            "agentcollab_derived_counterfactual",
        )
        self.assertFalse(bundle.manifest.analysis_eligible)
        self.assertEqual(bundle.manifest.execution_status, "paused")


if __name__ == "__main__":
    unittest.main()
