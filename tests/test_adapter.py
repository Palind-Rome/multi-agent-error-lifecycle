from __future__ import annotations

import unittest

from mas_error_lifecycle.adapters import (
    convert_agentcollab_result,
    rewire_agentcollab_task,
)
from mas_error_lifecycle.metrics import compute_metrics


class AgentCollabAdapterTests(unittest.TestCase):
    def test_matched_topology_rewrite_keeps_agent_prompts(self) -> None:
        task = {
            "task_id": "T",
            "description": "held fixed",
            "topology": {
                "type": "linear_chain",
                "agents": [
                    {"agent_id": "A", "role": "a", "system_prompt": "pa"},
                    {"agent_id": "B", "role": "b", "system_prompt": "pb"},
                    {"agent_id": "C", "role": "c", "system_prompt": "pc"},
                    {"agent_id": "D", "role": "d", "system_prompt": "pd"},
                ],
                "edges": [["A", "B"], ["B", "C"], ["C", "D"]],
            },
            "injections": {"cpr": {"seed_agent": "B", "false_fact": "false"}},
        }
        rewritten = rewire_agentcollab_task(task, "converging_dag")
        self.assertEqual(
            task["topology"]["edges"],
            [["A", "B"], ["B", "C"], ["C", "D"]],
        )
        self.assertEqual(rewritten["topology"]["speaking_order"][0], "B")
        self.assertEqual(
            rewritten["topology"]["edges"],
            [["B", "A"], ["B", "C"], ["A", "D"], ["C", "D"]],
        )
        self.assertEqual(
            [agent["system_prompt"] for agent in rewritten["topology"]["agents"]],
            ["pa", "pb", "pc", "pd"],
        )

    def test_cpr_full_result_is_preserved_without_fake_task_success(self) -> None:
        false_fact = "The input is JSON."
        payload = {
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
                    "provider_requests": [
                        {
                            "agent_id": "B",
                            "provider": "mock",
                            "model": "m",
                            "messages": [
                                {"role": "system", "content": "sink"},
                                {
                                    "role": "user",
                                    "content": f"Parent claims: {false_fact}",
                                },
                            ],
                        }
                    ],
                },
            },
        }
        bundle = convert_agentcollab_result(payload)
        metrics = compute_metrics(bundle)
        self.assertIsNone(metrics.task_success)
        self.assertIsNone(metrics.task_score)
        self.assertEqual(metrics.input_tokens, 22)
        self.assertEqual(metrics.output_tokens, 10)
        self.assertIsNone(metrics.latency_ms)
        self.assertIsNone(metrics.cost_usd)
        self.assertEqual(metrics.exposure_pair_count, 1)
        self.assertEqual(metrics.adoption_pair_count, 1)
        self.assertEqual(metrics.max_adoption_hop, 1)
        self.assertTrue(
            any(
                prompt.metadata.get("actual_full_provider_request_available")
                for prompt in bundle.prompts
            )
        )
        self.assertTrue(
            any(
                event.details.get("actual_prompt_recorded")
                for event in bundle.events
                if event.event_type.value == "artifact_exposed"
            )
        )
        self.assertTrue(
            any(
                event.details.get("provisional")
                for event in bundle.events
                if event.event_type.value == "artifact_adopted"
            )
        )


if __name__ == "__main__":
    unittest.main()
