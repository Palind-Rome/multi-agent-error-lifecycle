# RQ1 compact-arm expansion — 5 new RTD tasks (preliminary)

Five additional RTD tasks run through the Codex-compaction arm, one
`qwen/qwen3-30b-a3b-instruct-2507`, temperature 0. These fill the two topology
cells absent from the original 7 (`branching_tree`, `custom_graph`) and the
`ag=3` gap; every task is `multi_constraint` (2-3 tracers each, 11 tracers
total).

**Status: literal + structural only. The semantic annotation (LLM-judge +
human review) is not yet done, so do not treat these as adjudicated findings.**

## Literal RTD score

| Task | Topology | tracers | literal RTD |
| --- | --- | --- | --- |
| TASK-DATAENG-RTD-058 | branching_tree | 2 | 1.0 |
| TASK-DEVOPS-RTD-172 | branching_tree | 2 | 1.0 |
| TASK-SWE-RTD-054 | branching_tree | 2 | 1.0 |
| TASK-DEVOPS-RTD-118 | custom_graph | 2 | **0.0** |
| TASK-SWE-RTD-047 | custom_graph | 3 | **0.0** |

The three `branching_tree` tasks keep the literal tracer; the two
`custom_graph` tasks lose it. n = 2 vs 3, so this is a signal, not a conclusion.

## Where the loss happens (RTD-118, structural trace)

`TASK-DEVOPS-RTD-118` anchors: "exactly 300.00 seconds" and "v1.0.BUILD-NUM".
Following the `300.00` fragment through the message flow:

```
CI_CD_ENG -> REL_MGR   300.00 ✓        # initiator preserves it
CI_CD_ENG -> DEV       300.00 ✓
DEV       -> CI_CD_ENG 300.00 ✓ + 300s # partial relaxation
REL_MGR   -> CI_CD_ENG 300s   ✗        # downstream drops "300.00"
...from then on, everyone writes "300s"
```

The compaction summaries are **faithful**: the early summaries (compacting the
initiator's still-correct output) keep `300.00`, and the later summaries only
say `300s` because their *input* already said `300s`. So:

- the loss is **in the relay/downstream adoption**, not in the compaction step —
  consistent with the original 7-task finding (compression faithful, loss moved
  downstream);
- the new part is that these anchors are *precise numerical strings*, so the
  relaxation (`300.00` → `300s`, `v1.0.BUILD-NUM` → `v1.0`) is now caught by the
  **literal** RTD metric as 0.0, whereas the original 7 tasks' subtler
  relaxations slipped through the literal metric as 1.0.

## Per-tracer survival (deterministic fragment tracking)

`scripts/analyze_rtd_survival.py` checks each tracer's key numeric fragment
across the compaction summaries, the relay messages, and the final answer:

| Task (topology) | Tracer | summary | relay | final |
| --- | --- | --- | --- | --- |
| RTD-058 (branch) | 367D retention | ✓ | ✓ | ✓ |
| RTD-058 (branch) | 97ms latency | ✓ | ✓ | ✓ |
| RTD-172 (branch) | 10.75 GB | ✓ | ✓ | ✓ |
| RTD-172 (branch) | TLS 1.3 | ✓ | ✓ | ✓ |
| RTD-054 (branch) | Argon2id 65536 KB | ✓ | ✓ | **65536 dropped** |
| RTD-054 (branch) | 1440 min | ✓ | ✓ | ✓ |
| RTD-118 (custom) | 300.00 s | ✓ | ✓ | **relaxed to 300s** |
| RTD-118 (custom) | v1.0.BUILD-NUM | ✗ | ✗ | ✗ |
| RTD-047 (custom) | MongoDB Atlas 6.0 | ✓ | ✓ | ✓ |
| RTD-047 (custom) | no-local-cache | ✗ | ✗ | ✗ |
| RTD-047 (custom) | OAuth 2.0 | ✓ | ✓ | **2.0 dropped** |

Notes:

- The `branching_tree` tasks keep their tracers, with **one partial loss**
  (RTD-054 drops `65536 KB` while keeping "Argon2id + 4 iterations") that the
  literal 1.0 score hides.
- The `custom_graph` tasks lose or relax multiple tracers: `300.00 → 300s`,
  `v1.0.BUILD-NUM` gone, `no-local-cache` gone, `OAuth 2.0 → OAuth`.
- The `no-local-cache` tracer in RTD-047 is absent **even from the summaries**
  (`summary=✗`), i.e. it never survives the first compaction — the only tracer
  so far where the loss can be attributed to the compaction stage rather than
  the relay.

## Semantic layer (draft LLM-judge, revises the above)

`scripts/run_rtd_semantic_judge.py` classifies each tracer at two stages
(transformation = compaction summary, downstream = final answer). Judge model is
the **same** `qwen3-30b-a3b` (self-judging — see caveat below). Result for the
baseline 11 tracers: **all 11 = `preserved_correctly` + `correctly_reflected`**,
including the two `custom_graph` tasks whose literal RTD is 0.0.

So the literal 0.0 is **reformatting, not loss**: the downstream agents normalize
the precision (`exactly 300.00 seconds` → `within 300s`,
`v1.0.BUILD-NUM` → `v1.0.${BUILD-NUM}`, `must not be cached` → "no local caching
observed"). The value is unchanged; the exact string is not. This is the
*opposite* half of the same "literal RTD misleads" finding as the original 7
tasks — there the literal 1.0 hid a real value change (`50ms→60ms`); here the
literal 0.0 flags a benign reformatting.

**Caveat**: the judge is the same model family it is judging (leniency risk) and
has not been human-reviewed. Treat the "all preserved" verdict as a draft; a
cross-check with a *different* judge model (e.g. `235b-a22b`) or human review is
the next step before this is adjudicated.

## Cross-model comparison (literal RTD, same 5 tasks)

| Task | topology | 30b-a3b | 235b-a22b | thinking |
| --- | --- | --- | --- | --- |
| RTD-058 | branching_tree | 1.0 | 1.0 | **0.0** |
| RTD-172 | branching_tree | 1.0 | 1.0 | 1.0 |
| RTD-054 | branching_tree | 1.0 | 1.0 | 1.0 |
| RTD-118 | custom_graph | 0.0 | **1.0** | 0.0 |
| RTD-047 | custom_graph | 0.0 | **0.5** | **1.0** |

Observations (n = 5, one realization per cell — signal, not conclusion):

- **Size**: the bigger `235b-a22b-2507` preserves tracers that the baseline
  drops — both `custom_graph` tasks improve (0.0 → 1.0 and 0.0 → 0.5). The
  custom_graph loss is therefore *not* purely topological; a stronger model
  overcomes it.
- **Reasoning style**: `thinking-2507` keeps `RTD-047` (custom, which the
  baseline lost) but drops `RTD-058` (branching, which both others kept). Its
  failure points do not line up with topology — a different failure mode than
  the non-reasoning models.
- The `thinking` model also needed a larger per-call output budget
  (`max_output_tokens_per_call` 4096 → 16384) or it failed with `BudgetExceeded`
  on two tasks; its reasoning is longer.

## Batch 3 (topology balance, baseline 30b-a3b)

Five more tasks to balance `custom_graph` vs `branching_tree` across domains.
`RTD-055` is excluded: its first agent emits a full Grafana dashboard that
exceeds even a 64k output budget (and 64k triggers a provider 502), so it is a
pathological-output outlier, not a topology signal.

| Task | topology | literal RTD |
| --- | --- | --- |
| RTD-058/172/054/146/067 | branching_tree | 1.0 × 5 |
| RTD-118/047/129 | custom_graph | 0.0 × 3 |
| RTD-052 | custom_graph | 1.0 |

Combined with batch 1-2: **branching_tree 5/5 = 1.0, custom_graph 3/4 = 0.0**.
The topology split is stable, but recall the semantic judge: the custom_graph
0.0 is precision reformatting (`300.00`→`300s`), not semantic loss.

## What this suggests to check next

1. Whether `custom_graph` (a non-tree edge structure with back-and-forth hops)
   systematically loses tracers where `branching_tree` does not — needs more
   tasks per topology.
2. Whether the same "numeric relaxation" signature holds across the other two
   sizes now enabled (`235b-a22b-2507`, `30b-a3b-thinking-2507`).
