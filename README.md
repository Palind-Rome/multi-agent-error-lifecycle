# Multi-Agent Error Lifecycle

这是论文 **From Error Exposure to Recovery: Mechanistic Lifecycle Analysis and
Controlled Interventions in LLM Multi-Agent Collaboration** 的实验基础设施。

v0.2 的核心变化是：不再把“收到注入”当作模型生成或污染，也不再把字符串复现当作
正式 adoption。一次运行现在可以审计：

```text
assignment / injection
  -> possession
  -> surfacing
  -> send -> delivery
  -> exact prompt exposure
  -> integration / belief-or-action adoption
  -> action / commitment fulfillment or breach
  -> pre/post verification
  -> containment / rollback -> recovery -> relapse
  -> recognized outcome, safe/usable completion, cost
```

正确私有信息的 omission、verifier attestation 缺失、deterministic grader、
evidence validity、access/tool failure 和 commitment breach 都是一等记录。

## 当前可以做什么

- 离线运行 deterministic v0.2 fixtures；
- 校验版本化 JSONL 的引用、时序和状态机不变量；
- 区分消息尝试、delivery、artifact survival 与实际 provider-request exposure；
- 对 exposure request observation 与 semantic integration/adoption annotation
  分别报告 opportunity、denominator 和 coverage，缺标注不记为 0；
- 对 required true information 输出逐 message/artifact 分支的 first-loss-stage
  审计记录，并保留多父聚合的每条 `parent_message_ids` 路径；semantic
  integration 另按 prompt join 只计一次，缺少完整机会观测则标 unknown；
- 分别计算 required-true-information 与 false-artifact 指标；
- 将 verification timing/completion/verdict 与 containment/rollback 分开；
- 记录 commitment、evidence、attestation、grader、model/tool call 和 nullable
  usage；
- 生成真正共享 task/repeat seed 的 paired assignments，并单独随机化执行顺序；
- 对缺 pair 硬失败，以 task/shared-pool cluster 做 paired bootstrap；
- 离线校准 MAST 风格的 multi-label annotation；
- 导入 AgentCollabBench 完整结果，并保留 exact request 与 call provenance；
- 用硬预算、私有原子落盘和 durable failure ledger 执行一个明确的、
  `analysis_eligible=false` 的 untouched AgentCollabBench engineering smoke；
- 生成明确标为 `AgentCollabBench-derived`、默认暂停且不可作 native/causal
  汇报的 topology stress variant。

当前不能开始付费主实验或推断性实验：虽已有固定 PaperBypass/Qwen 示例配置和
单任务 engineering-smoke driver，但没有通用 `run-plan` executor、校准 judge 或
HiddenBench/TeamBench/CooperBench/SWE-bench runner。
详见 [`docs/experiment-readiness.md`](docs/experiment-readiness.md)。

## 快速开始

Python 3.11 或更高版本，无第三方运行时依赖：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v

PYTHONPATH=src python -m mas_error_lifecycle demo \
  --out outputs/demo.jsonl \
  --topology converging_dag \
  --verification evidence_required \
  --verification-timing post_adoption \
  --governance-action rollback \
  --force

PYTHONPATH=src python -m mas_error_lifecycle validate outputs/demo.jsonl
PYTHONPATH=src python -m mas_error_lifecycle summarize outputs/demo.jsonl

PYTHONPATH=src python -m mas_error_lifecycle plan \
  configs/pilot.toml \
  --out outputs/native-smoke-plan.jsonl \
  --force
```

`configs/pilot.toml` 只展开 12 个 untouched-native、homogeneous、
no-added-verifier 的 engineering assignments。它没有触发 API 调用，也没有推断资格。

旧的 144-cell 设计已移到
[`configs/derived-topology-stress.paused.toml`](configs/derived-topology-stress.paused.toml)。
默认读取会失败；`--allow-unready` 只允许预览，并不会使其可执行或可因果解释：

```bash
PYTHONPATH=src python -m mas_error_lifecycle plan \
  configs/derived-topology-stress.paused.toml \
  --allow-unready \
  --out outputs/derived-preview.jsonl \
  --force
```

## AgentCollabBench 导入

上游 CLI summary 没有完整 `RunResult`，必须从 Python API 保存完整结果。仓库的
per-agent router 会为 request/response 分配 call ID，并在调用前记录 attempt，使
provider exception 也不会消失。

```python
evaluation = evaluate_agentcollab_task(
    task,
    providers={"planner": planner_provider, "worker": worker_provider},
    default_provider=worker_provider,
    metric="cpr",
    metric_config={"judge_provider": calibrated_judge_provider},
    run_context=plan_item.to_dict(),
    judge_provenance={
        "provider": "...",
        "model": "...",
        "prompt_sha256": "...",
        "calibration_version": "...",
    },
)
payload = evaluation.to_adapter_payload()
```

导入时可显式提供同一份 run context：

```bash
PYTHONPATH=src python -m mas_error_lifecycle import-agentcollab \
  full-result.json \
  --run-context run-context.json \
  --out outputs/imported.jsonl \
  --force
```

没有 context 的结果会被标为 observational、`analysis_eligible=false`，seed 保持
`null`，不会伪造为 0。

adapter 的证据边界：

- handoff 可以证明 send/delivery 和 literal survival；
- 只有与 message 显式链接的 exact provider request 可以产生 exposure
  observation；同一 parent 的旧 handoff 不会被后轮 prompt 回填；
- exact marker 只产生 `artifact_surfaced` 和
  `marker_surface_proxy/textual_reproduction` annotation；
- semantic/action adoption 必须由预注册、校准后的 annotation 加入；
- 没有 authoritative semantic annotation 时，adoption/integration rate 与
  无法识别的 final contamination 保持 `null`，同时报告 coverage/denominator；
- RTD 只匹配 canonical tracer ID，不把自然语言 anchor 当 tracer，也不把
  forwarding 当 belief adoption；
- AgentCollabBench diagnostic score 放在 outcome details，task success/score
  保持 null。

可运行上游兼容性 smoke：

```bash
PYTHONPATH=src python scripts/smoke_agentcollab_adapter.py \
  /path/to/AgentCollabBench \
  --out outputs/agentcollab-offline-smoke.jsonl \
  --force
```

真实 provider 的单任务 smoke 使用独立的强门禁入口；它固定
`purpose=engineering_smoke`、`analysis_eligible=false`，所有 raw request/response
和 lifecycle trace 只能落到 git-ignored `outputs/private`。当前执行范围只批准 RQ1
RTD；配置、预算、seed、失败账本和命令见
[`docs/agentcollab-real-smoke.md`](docs/agentcollab-real-smoke.md)。

## Derived topology generator

```bash
PYTHONPATH=src python -m mas_error_lifecycle derive-agentcollab \
  /path/to/AgentCollabBench/tasks/TASK.json \
  --topology converging_dag \
  --out outputs/TASK.derived-converging-dag.json
```

生成物保存 source task hash、changed/held-fixed 字段和已知未匹配项，并强制：

- `protocol_kind=agentcollab_derived_counterfactual`
- `suite_name=AgentCollabBench-derived`
- `review_status=unvalidated`
- `execution_status=paused`
- `analysis_eligible=false`
- `native_score_export_allowed=false`

即使 roles/system prompts 保持不变，重接边仍会改变 leaf contributors、context
volume、message/token/hop opportunity 和 final aggregation，因此不能称作 edges-only
causal intervention。

## 设计与 schema

- 研究顺序、estimands、controls 与统计门槛：
  [`docs/research-design.md`](docs/research-design.md)
- JSONL records、事件语义与不变量：
  [`docs/trace-schema.md`](docs/trace-schema.md)
- 当前可运行范围与阻塞：
  [`docs/experiment-readiness.md`](docs/experiment-readiness.md)
- 关键决策：
  [`docs/decisions.md`](docs/decisions.md)
- 九篇 HTML 原文的证据—设计映射：
  [`docs/evidence-map.md`](docs/evidence-map.md)

通用实验的 provider 配置应从
[`configs/models.example.toml`](configs/models.example.toml) 复制；受限的单任务
AgentCollabBench 真实烟测则应从
[`configs/agentcollab-smoke.example.toml`](configs/agentcollab-smoke.example.toml)
复制。两者的本地副本都必须保持 git-ignored。
不要把 API keys、authorization headers、hidden tests 或 gold patches 写入仓库。
