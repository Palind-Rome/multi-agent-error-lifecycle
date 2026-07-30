# Multi-Agent Error Lifecycle

这个仓库是论文 **From Error Exposure to Recovery: Causal Lifecycle Analysis of
Failures in LLM Multi-Agent Collaboration** 的实验骨架。它将一次多智能体运行拆成
六个可观测阶段：

1. generation：错误命题、约束或承诺首次产生；
2. transmission / exposure：信息沿通信边发送，并实际进入接收者上下文；
3. adoption：接收者采纳、拒绝或保持不确定；
4. verification：是否检查、用了什么证据、检查结论是否正确；
5. recovery：纠正、回滚、隔离或再次引入；
6. outcome：最终任务质量、安全完成、成本和延迟。

当前版本不依赖第三方 Python 包，可以离线运行 deterministic mock、校验 JSONL
trace、计算生命周期指标、展开 pilot 实验矩阵，并导入 AgentCollabBench 的完整
`RunResult`。真实模型调用被刻意留在 provider adapter 边界，需在确认模型、预算和
API 凭据后再接入。

## 已实现

- 版本化、逐行可审计的 JSONL trace schema；
- agent、拓扑、artifact lineage、可哈希/可脱敏的实际 prompt exposure、adoption、verification、
  recovery 与 outcome 记录；
- 跨记录完整性和生命周期语义校验；
- edge transmission、`P(adopt | exposed)`、verification、false accept、
  detection、recovery、error reproduction number、最大传播深度、
  time-to-detection/recovery、contaminated-agent-turn AUC 与任务成本；
- chain、star、converging DAG 的确定性 mock runner；
- TOML pilot factorial 展开器，支持条件/重复/seed 清单；
- AgentCollabBench `RunResult.to_dict()` adapter，保留原始 trace 和 API 统计；
- 针对上游单一 provider 限制的 per-agent router，并记录每次完整 provider request；
- 仅用标准库的单元测试和 GitHub Actions。

## 快速开始

Python 3.11 或更高版本：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m mas_error_lifecycle demo \
  --out outputs/demo.jsonl \
  --topology converging_dag \
  --verification evidence_required \
  --force
PYTHONPATH=src python -m mas_error_lifecycle validate outputs/demo.jsonl
PYTHONPATH=src python -m mas_error_lifecycle summarize outputs/demo.jsonl
PYTHONPATH=src python -m mas_error_lifecycle plan \
  configs/pilot.toml \
  --out outputs/pilot-plan.jsonl \
  --force
```

也可以安装 editable package 后使用 `masel`：

```bash
python -m pip install -e .
masel demo --out outputs/demo.jsonl --force
```

## AgentCollabBench adapter

上游 CLI 的 `EvalResult.to_dict()` 不包含 `run_result`，因此必须从 Python API 保存
完整对象：

```python
import json
from agentcollabbench.harness.evaluate import evaluate_task

result = evaluate_task(task=task_path, provider=provider, metrics=["cpr"])
payload = {
    "task_id": result.task_id,
    "scores": result.scores,
    "errors": result.errors,
    "run_result": result.run_result.to_dict() if result.run_result else None,
}
with open("full-result.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
```

然后导入：

```bash
PYTHONPATH=src python -m mas_error_lifecycle import-agentcollab \
  full-result.json \
  --out outputs/imported.jsonl
```

adapter 只把可由 exact marker 证明的内容标为 exposed/adopted；语义采纳应由独立
judge 或人工标注补全，避免把“文本中出现”误当作“基于该信息行动”。

仓库自带一个不调用 API 的端到端兼容性检查：

```bash
PYTHONPATH=src python scripts/smoke_agentcollab_adapter.py \
  /path/to/AgentCollabBench \
  --out outputs/agentcollab-offline-smoke.jsonl \
  --force
```

固定的 12 项、至少含 4 个 agent 的 RTD/CPR 分层 pilot 清单位于
[`configs/agentcollab-pilot-tasks.json`](configs/agentcollab-pilot-tasks.json)，
对应上游 commit `f016f60`。

因果比较 topology 时，不能直接比较碰巧使用不同图的不同任务。应对同一任务重接
边，同时保持角色、system prompt、注入和 ground truth 不变：

```bash
PYTHONPATH=src python -m mas_error_lifecycle rewrite-agentcollab \
  /path/to/AgentCollabBench/tasks/TASK.json \
  --topology converging_dag \
  --out outputs/TASK.converging-dag.json
```

rewriter 要求至少四个 agent 才生成真正包含两个中间分支的 converging DAG，并把
CPR `seed_agent` 放在 root。这个有意改变的 root centrality 会记录在
`experimental_metadata` 中。

异构条件应调用 `evaluate_agentcollab_task`，并显式给每个 `agent_id` 分配
provider：

```python
from mas_error_lifecycle.adapters import (
    convert_agentcollab_result,
    evaluate_agentcollab_task,
)

evaluation = evaluate_agentcollab_task(
    task,
    providers={"planner": planner_provider, "worker": worker_provider},
    default_provider=worker_provider,
    metric="cpr",
    metric_config={"judge_provider": independent_judge_provider},
)
bundle = convert_agentcollab_result(evaluation.to_adapter_payload())
```

CPR/IDR 不允许隐式选 judge：必须传独立 `judge_provider`，或提供预注册的
`violation_keywords`。

## 实验执行边界

当前能够完整验证 instrumentation，但尚不能开始付费主实验，待确认：

- 被测 backbone、provider、judge model 与 API key；
- pilot 和全量实验的 token/API 预算；
- 异构条件是跨供应商还是同供应商不同能力档位；
- 是否允许 LLM judge，以及人审抽样比例；
- Docker/x86_64/磁盘条件是否满足 SWE-bench；
- outcome benchmark 的最终优先级。

设计依据和字段说明分别见
[`docs/research-design.md`](docs/research-design.md) 与
[`docs/trace-schema.md`](docs/trace-schema.md)。
当前可运行范围和剩余阻塞见
[`docs/experiment-readiness.md`](docs/experiment-readiness.md)。
