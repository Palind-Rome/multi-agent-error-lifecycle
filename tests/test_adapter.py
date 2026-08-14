from __future__ import annotations

import copy
import unittest
from dataclasses import dataclass, replace

from mas_error_lifecycle.adapters import (
    AgentCollabEvaluation,
    convert_agentcollab_result,
    generate_agentcollab_derived_counterfactual,
)
from mas_error_lifecycle.metrics import compute_metrics
from mas_error_lifecycle.schema import AnnotationRecord, EventType


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


def _branching_rtd_payload() -> dict:
    tracer = "TRACE_BRANCH_JOIN"
    agents = [
        {
            "agent_id": agent_id,
            "role": agent_id.lower(),
            "system_prompt": agent_id.lower(),
            "receives_from": receives_from,
        }
        for agent_id, receives_from in (
            ("A", []),
            ("B", ["A"]),
            ("C", ["A", "B"]),
        )
    ]
    return {
        "run_result": {
            "task_id": "TASK-RTD-BRANCH-JOIN",
            "scenario": {
                "task_id": "TASK-RTD-BRANCH-JOIN",
                "metric_applicability": ["rtd"],
                "topology": {
                    "type": "converging_dag",
                    "agents": agents,
                    "edges": [["A", "B"], ["A", "C"], ["B", "C"]],
                },
                "injections": {"rtd": {"tracer_id": tracer}},
            },
            "output": {"result": tracer},
            "trace": {
                "turns": [
                    {"agent_id": "A", "content": tracer},
                    {"agent_id": "B", "content": tracer},
                    {"agent_id": "C", "content": tracer},
                ],
                "handoffs": [
                    {
                        "message_id": "m-a-b",
                        "sender": "A",
                        "receiver": "B",
                        "content": tracer,
                    },
                    {
                        "message_id": "m-a-c",
                        "sender": "A",
                        "receiver": "C",
                        "content": tracer,
                    },
                    {
                        "message_id": "m-b-c",
                        "sender": "B",
                        "receiver": "C",
                        "content": tracer,
                    },
                ],
                "api_calls": [],
                "provider_requests": [
                    {
                        "call_id": "call-b",
                        "agent_id": "B",
                        "provider": "mock",
                        "model": "m",
                        "messages": [{"role": "user", "content": tracer}],
                        "status": "success",
                    },
                    {
                        "call_id": "call-c",
                        "agent_id": "C",
                        "provider": "mock",
                        "model": "m",
                        "messages": [{"role": "user", "content": tracer}],
                        "status": "success",
                    },
                ],
            },
        }
    }


def _repeated_rtd_payload(
    *,
    first_prompt_contains: bool = True,
    second_source_contains: bool = True,
) -> dict:
    tracer = "TRACE_REPEAT"
    absent = "ordinary answer"
    first_prompt = tracer if first_prompt_contains else absent
    second_source = tracer if second_source_contains else absent
    second_prompt = second_source
    return {
        "run_result": {
            "task_id": "TASK-RTD-REPEATED",
            "scenario": {
                "task_id": "TASK-RTD-REPEATED",
                "metric_applicability": ["rtd"],
                "topology": {
                    "type": "repeated_chain",
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
                "injections": {"rtd": {"tracer_id": tracer}},
            },
            "output": {"result": second_prompt},
            "trace": {
                "turns": [
                    {"agent_id": "A", "content": tracer},
                    {"agent_id": "B", "content": first_prompt},
                    {"agent_id": "A", "content": second_source},
                    {"agent_id": "B", "content": second_prompt},
                ],
                "handoffs": [
                    {
                        "message_id": "m1",
                        "sender": "A",
                        "receiver": "B",
                        "content": tracer,
                    },
                    {
                        "message_id": "m2",
                        "sender": "A",
                        "receiver": "B",
                        "content": second_source,
                    },
                ],
                "api_calls": [],
                "provider_requests": [
                    {
                        "call_id": "p1",
                        "agent_id": "B",
                        "provider": "mock",
                        "model": "m",
                        "messages": [{"role": "user", "content": first_prompt}],
                        "status": "success",
                    },
                    {
                        "call_id": "p2",
                        "agent_id": "B",
                        "provider": "mock",
                        "model": "m",
                        "messages": [{"role": "user", "content": second_prompt}],
                        "status": "success",
                    },
                ],
            },
        }
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
        self.assertEqual(metrics.adoption_opportunity_count, 1)
        self.assertEqual(metrics.adoption_annotation_count, 0)
        self.assertEqual(metrics.adoption_rate_denominator_count, 0)
        self.assertEqual(metrics.adoption_annotation_coverage, 0.0)
        self.assertIsNone(metrics.adoption_given_exposure)
        self.assertEqual(metrics.final_contamination_opportunity_count, 1)
        self.assertEqual(metrics.final_contamination_annotation_coverage, 0.0)
        self.assertIsNone(metrics.final_contaminated_agents)
        self.assertIsNone(metrics.final_contaminated_prevalence)
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
        self.assertEqual(metrics.exposure_opportunity_count, 1)
        self.assertEqual(metrics.exposure_observation_count, 0)
        self.assertEqual(metrics.exposure_observation_coverage, 0.0)
        self.assertIsNone(metrics.exposure_given_delivered_survival)
        self.assertEqual(metrics.adoption_pair_count, 0)
        self.assertIsNone(metrics.final_contaminated_agents)

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
        self.assertEqual(metrics.required_information_possessed_count, 1)
        self.assertEqual(metrics.required_information_surfaced_count, 0)
        self.assertEqual(metrics.required_information_surfacing_rate, 0.0)
        self.assertEqual(
            metrics.required_information_first_loss_stage_counts,
            {"surfacing": 1},
        )
        self.assertEqual(
            metrics.required_information_first_loss_records[0]["first_loss_stage"],
            "surfacing",
        )
        self.assertEqual(
            metrics.required_information_first_loss_records[0][
                "semantic_integration"
            ],
            "unknown",
        )
        self.assertIsNone(metrics.required_information_integration_rate)
        self.assertEqual(metrics.adoption_pair_count, 0)
        self.assertEqual(metrics.final_contaminated_agents, 0)

    def test_missing_surface_opportunity_is_unknown_not_loss(self) -> None:
        payload = _repeated_rtd_payload()
        payload["run_result"]["trace"] = {
            "turns": [],
            "handoffs": [],
            "api_calls": [],
            "provider_requests": [],
        }
        metrics = compute_metrics(convert_agentcollab_result(payload))
        self.assertEqual(metrics.required_information_possessed_count, 1)
        self.assertEqual(
            metrics.required_information_possession_observation_coverage, 1.0
        )
        self.assertEqual(metrics.required_information_surfacing_observation_count, 0)
        self.assertEqual(
            metrics.required_information_surfacing_observation_coverage, 0.0
        )
        self.assertIsNone(metrics.required_information_surfacing_rate)
        record = metrics.required_information_first_loss_records[0]
        self.assertEqual(record["surfacing"], "unknown")
        self.assertEqual(
            record["first_loss_stage"], "surfacing_opportunity_unknown"
        )

    def test_branching_join_expands_all_parent_messages(self) -> None:
        bundle = convert_agentcollab_result(_branching_rtd_payload())
        join = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
            and event.target_agent_id == "C"
        )
        self.assertIsNone(join.details["message_id"])
        self.assertEqual(
            set(join.details["parent_message_ids"]),
            {"m-a-c", "m-b-c"},
        )

        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.exposure_event_count, 2)
        self.assertEqual(metrics.exposure_opportunity_count, 3)
        self.assertEqual(metrics.exposure_observation_count, 3)
        self.assertEqual(metrics.exposure_given_delivered_survival, 1.0)
        self.assertEqual(
            metrics.required_information_delivery_opportunity_count, 3
        )
        self.assertEqual(metrics.required_information_survived_count, 3)
        self.assertEqual(metrics.required_information_prompt_exposed_count, 3)
        self.assertEqual(
            metrics.required_information_first_loss_stage_counts,
            {
                "none_through_prompt_exposure": 3,
                "semantic_integration_unknown": 2,
            },
        )
        self.assertEqual(
            metrics.required_information_branch_first_loss_stage_counts,
            {"none_through_prompt_exposure": 3},
        )
        self.assertEqual(
            metrics.required_information_semantic_join_stage_counts,
            {"semantic_integration_unknown": 2},
        )
        c_joins = [
            record
            for record in metrics.required_information_first_loss_records
            if record["unit_type"] == "semantic_join"
            and record["target_agent_id"] == "C"
        ]
        self.assertEqual(len(c_joins), 1)
        self.assertEqual(set(c_joins[0]["parent_message_ids"]), {"m-a-c", "m-b-c"})
        self.assertEqual(
            metrics.required_information_integration_opportunity_count, 2
        )
        self.assertEqual(
            metrics.required_information_integration_annotation_coverage, 0.0
        )
        self.assertIsNone(metrics.required_information_integration_rate)

    def test_authoritative_annotation_turns_unknown_into_measured_adoption(
        self,
    ) -> None:
        bundle = convert_agentcollab_result(_cpr_payload())
        exposure = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        )
        annotation = AnnotationRecord(
            annotation_id="annotation:authoritative-adoption",
            run_id=bundle.manifest.run_id,
            taxonomy="semantic-adoption",
            taxonomy_version="test-v1",
            labels=("semantic_adoption",),
            annotator="test-adjudicator",
            identifiability="action_grounded",
            target_event_ids=(exposure.event_id,),
            artifact_id=exposure.artifact_id,
            agent_id=exposure.target_agent_id,
            metadata={
                "authoritative": True,
                "adoption_status": "positive",
            },
        )
        metrics = compute_metrics(
            replace(bundle, annotations=(*bundle.annotations, annotation))
        )
        self.assertEqual(metrics.adoption_annotation_coverage, 1.0)
        self.assertEqual(metrics.adoption_rate_denominator_count, 1)
        self.assertEqual(metrics.adoption_given_exposure, 1.0)
        self.assertIsNone(metrics.final_contaminated_agents)

    def test_unrelated_annotation_target_does_not_use_pair_fallback(self) -> None:
        bundle = convert_agentcollab_result(_cpr_payload())
        exposure = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        )
        unrelated = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_POSSESSED
        )
        annotation = AnnotationRecord(
            annotation_id="annotation:unrelated-target",
            run_id=bundle.manifest.run_id,
            taxonomy="semantic-adoption",
            taxonomy_version="test-v1",
            labels=("semantic_adoption",),
            annotator="test-adjudicator",
            identifiability="action_grounded",
            target_event_ids=(unrelated.event_id,),
            artifact_id=exposure.artifact_id,
            agent_id=exposure.target_agent_id,
            metadata={
                "authoritative": True,
                "adoption_status": "positive",
            },
        )
        metrics = compute_metrics(
            replace(bundle, annotations=(*bundle.annotations, annotation))
        )
        self.assertEqual(metrics.adoption_annotation_count, 0)
        self.assertEqual(metrics.adoption_annotation_coverage, 0.0)
        self.assertEqual(metrics.adoption_rate_denominator_count, 0)
        self.assertIsNone(metrics.adoption_given_exposure)

    def test_required_integration_rate_uses_only_annotated_denominator(
        self,
    ) -> None:
        bundle = convert_agentcollab_result(_branching_rtd_payload())
        exposure = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
            and event.target_agent_id == "B"
        )
        annotation = AnnotationRecord(
            annotation_id="annotation:partial-integration",
            run_id=bundle.manifest.run_id,
            taxonomy="semantic-integration",
            taxonomy_version="test-v1",
            labels=("semantic_integration",),
            annotator="test-adjudicator",
            identifiability="semantic",
            target_event_ids=(exposure.event_id,),
            artifact_id=exposure.artifact_id,
            agent_id=exposure.target_agent_id,
            metadata={
                "authoritative": True,
                "integration_status": "positive",
            },
        )
        metrics = compute_metrics(
            replace(bundle, annotations=(*bundle.annotations, annotation))
        )
        self.assertEqual(metrics.required_information_integration_opportunity_count, 2)
        self.assertEqual(metrics.required_information_integration_annotation_count, 1)
        self.assertEqual(
            metrics.required_information_integration_rate_denominator_count, 1
        )
        self.assertEqual(
            metrics.required_information_integration_annotation_coverage, 0.5
        )
        self.assertEqual(metrics.required_information_integration_rate, 1.0)
        self.assertEqual(
            metrics.required_information_first_loss_stage_counts,
            {
                "none_through_prompt_exposure": 3,
                "none": 1,
                "semantic_integration_unknown": 1,
            },
        )

    def test_repeated_turn_links_each_message_to_its_consuming_prompt(self) -> None:
        bundle = convert_agentcollab_result(
            _repeated_rtd_payload(first_prompt_contains=False)
        )
        message_by_id = {message.message_id: message for message in bundle.messages}
        self.assertEqual(
            message_by_id["m1"].included_prompt_id,
            "agentcollab-provider-request:p1:B",
        )
        self.assertEqual(
            message_by_id["m2"].included_prompt_id,
            "agentcollab-provider-request:p2:B",
        )
        exposure = next(
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        )
        self.assertEqual(exposure.details["parent_message_ids"], ["m2"])

        metrics = compute_metrics(bundle)
        self.assertEqual(metrics.exposure_opportunity_count, 2)
        self.assertEqual(metrics.exposure_observation_count, 2)
        self.assertEqual(metrics.exposure_given_delivered_survival, 0.5)
        branch_by_message = {
            record["message_id"]: record
            for record in metrics.required_information_first_loss_records
            if record["unit_type"] == "message_branch"
        }
        self.assertEqual(
            branch_by_message["m1"]["first_loss_stage"], "prompt_exposure"
        )
        self.assertEqual(
            branch_by_message["m2"]["first_loss_stage"],
            "none_through_prompt_exposure",
        )

    def test_prior_surface_does_not_fill_later_omission(self) -> None:
        metrics = compute_metrics(
            convert_agentcollab_result(
                _repeated_rtd_payload(second_source_contains=False)
            )
        )
        branch_by_message = {
            record["message_id"]: record
            for record in metrics.required_information_first_loss_records
            if record["unit_type"] == "message_branch"
        }
        self.assertEqual(branch_by_message["m1"]["surfacing"], "surfaced")
        self.assertEqual(branch_by_message["m2"]["surfacing"], "not_surfaced")
        self.assertEqual(branch_by_message["m2"]["survival"], "not_applicable")
        self.assertEqual(branch_by_message["m2"]["first_loss_stage"], "surfacing")

    def test_repeated_exposure_annotation_covers_only_targeted_turn(self) -> None:
        bundle = convert_agentcollab_result(_repeated_rtd_payload())
        exposures = [
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        ]
        self.assertEqual(len(exposures), 2)
        annotation = AnnotationRecord(
            annotation_id="annotation:one-of-two-integrations",
            run_id=bundle.manifest.run_id,
            taxonomy="semantic-integration",
            taxonomy_version="test-v1",
            labels=("semantic_integration",),
            annotator="test-adjudicator",
            identifiability="semantic",
            target_event_ids=(exposures[0].event_id,),
            artifact_id=exposures[0].artifact_id,
            agent_id=exposures[0].target_agent_id,
            metadata={
                "authoritative": True,
                "integration_status": "positive",
            },
        )
        metrics = compute_metrics(
            replace(bundle, annotations=(*bundle.annotations, annotation))
        )
        self.assertEqual(metrics.integration_opportunity_count, 2)
        self.assertEqual(metrics.integration_annotation_count, 1)
        self.assertEqual(metrics.integration_rate_denominator_count, 1)
        self.assertEqual(metrics.integration_annotation_coverage, 0.5)
        self.assertEqual(metrics.integration_given_exposure, 1.0)
        self.assertEqual(
            metrics.required_information_semantic_join_stage_counts,
            {"none": 1, "semantic_integration_unknown": 1},
        )

    def test_later_integration_event_does_not_fill_earlier_exposure(self) -> None:
        bundle = convert_agentcollab_result(_repeated_rtd_payload())
        exposures = [
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        ]
        finalized = bundle.events[-1]
        integrated = replace(
            exposures[1],
            event_id="event:late-integration",
            event_type=EventType.ARTIFACT_INTEGRATED,
            step=finalized.step,
            agent_id=exposures[1].target_agent_id,
            source_agent_id=None,
            target_agent_id=None,
            prompt_id=None,
            parent_event_ids=(exposures[1].event_id,),
            details={
                "turn_index": 4,
                "authoritative": True,
                "evidence_type": "test-semantic-annotation",
            },
        )
        metrics = compute_metrics(
            replace(
                bundle,
                events=(*bundle.events[:-1], integrated, finalized),
            )
        )
        self.assertEqual(metrics.integration_opportunity_count, 2)
        self.assertEqual(metrics.integration_event_count, 1)
        self.assertEqual(metrics.integration_annotation_count, 1)
        self.assertEqual(metrics.integration_annotation_coverage, 0.5)
        self.assertEqual(
            metrics.required_information_semantic_join_stage_counts,
            {"none": 1, "semantic_integration_unknown": 1},
        )

    def test_repeated_false_paths_require_path_level_final_coverage(self) -> None:
        payload = _repeated_rtd_payload()
        scenario = payload["run_result"]["scenario"]
        scenario["metric_applicability"] = ["cpr"]
        scenario["injections"] = {
            "cpr": {
                "false_fact": "TRACE_REPEAT",
                "ground_truth": "correct fact",
                "seed_agent": "A",
            }
        }
        bundle = convert_agentcollab_result(payload)
        exposures = [
            event
            for event in bundle.events
            if event.event_type == EventType.ARTIFACT_EXPOSED
        ]
        annotation = AnnotationRecord(
            annotation_id="annotation:first-path-negative",
            run_id=bundle.manifest.run_id,
            taxonomy="semantic-adoption",
            taxonomy_version="test-v1",
            labels=("not_adopted",),
            annotator="test-adjudicator",
            identifiability="semantic",
            target_event_ids=(exposures[0].event_id,),
            artifact_id=exposures[0].artifact_id,
            agent_id=exposures[0].target_agent_id,
            metadata={
                "authoritative": True,
                "adoption_status": "negative",
            },
        )
        metrics = compute_metrics(
            replace(bundle, annotations=(*bundle.annotations, annotation))
        )
        self.assertEqual(metrics.adoption_opportunity_count, 2)
        self.assertEqual(metrics.adoption_annotation_count, 1)
        self.assertEqual(metrics.adoption_annotation_coverage, 0.5)
        self.assertEqual(metrics.final_contamination_opportunity_count, 2)
        self.assertEqual(
            metrics.final_contamination_annotation_denominator_count, 1
        )
        self.assertEqual(metrics.final_contamination_annotation_coverage, 0.5)
        self.assertIsNone(metrics.final_contaminated_agents)

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
