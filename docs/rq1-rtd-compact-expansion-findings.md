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

## What this suggests to check next

1. Whether `custom_graph` (a non-tree edge structure with back-and-forth hops)
   systematically loses tracers where `branching_tree` does not — needs more
   tasks per topology.
2. Whether the same "numeric relaxation" signature holds across the other two
   sizes now enabled (`235b-a22b-2507`, `30b-a3b-thinking-2507`).
