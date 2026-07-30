#!/usr/bin/env python3
"""Run one AgentCollabBench task with an offline echo provider and import it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("agentcollab_repo", type=Path)
    parser.add_argument("--task", default="TASK-DATAENG-CPR-009.json")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository = args.agentcollab_repo.resolve()
    sys.path.insert(0, str(repository))

    from agentcollabbench.harness.provider import LLMProvider, LLMResponse, Message
    from mas_error_lifecycle.adapters import (
        convert_agentcollab_result,
        evaluate_agentcollab_task,
    )
    from mas_error_lifecycle.metrics import compute_metrics
    from mas_error_lifecycle.store import write_trace

    class EchoProvider(LLMProvider):
        def chat(self, messages: list[Message], **kwargs: object) -> LLMResponse:
            request_text = "\n\n".join(
                f"[{message.role}]\n{message.content}" for message in messages
            )
            return LLMResponse(
                content=f"Offline echo for instrumentation:\n{request_text}",
                model="offline-echo-v1",
                input_tokens=len(request_text.split()),
                output_tokens=len(request_text.split()) + 4,
            )

        def provider_name(self) -> str:
            return "offline"

    task_path = repository / "tasks" / args.task
    with task_path.open(encoding="utf-8") as handle:
        task = json.load(handle)
    agent_ids = [agent["agent_id"] for agent in task["topology"]["agents"]]
    evaluation = evaluate_agentcollab_task(
        task,
        {agent_id: EchoProvider() for agent_id in agent_ids},
        metric="cpr",
        metric_config={"violation_keywords": ["JSON format", "nested structure"]},
        run_context={
            "purpose": "offline_compatibility_smoke",
            "protocol_kind": "agentcollab_native",
            "condition_id": "offline-native-smoke",
            "cluster_id": task["task_id"],
            "review_status": "native",
            "analysis_eligible": False,
            "upstream_commit": "f016f60",
        },
    )
    result = evaluation.run_result
    bundle = convert_agentcollab_result(evaluation.to_adapter_payload())
    write_trace(args.out, bundle, overwrite=args.force)
    print(
        json.dumps(
            {
                "ok": True,
                "task": result.task_id,
                "diagnostic_score": evaluation.score,
                "trace": str(args.out),
                "metrics": compute_metrics(bundle).to_dict(),
            },
            ensure_ascii=False,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
