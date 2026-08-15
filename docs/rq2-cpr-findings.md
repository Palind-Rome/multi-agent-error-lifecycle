# RQ2 findings — AgentCollabBench CPR (false-fact propagation)

Human-adjudicated. The LLM-judge pass was reviewed by the user: all 7 task
outcomes confirmed (7/7 agreement, n = 7). First pass at RQ2 ("how does wrong
information propagate") over seven untouched CPR tasks, one homogeneous
`qwen/qwen3-30b-a3b-instruct-2507`, temperature 0.

## What is measured

Each CPR task injects a `false_fact` into a seed agent and the `ground_truth`
into the other agents. The benchmark's own CPR diagnostic is keyword-based: it
counts whether the literal `false_fact` string reaches the final consensus. This
semantic layer instead classifies, turn by turn, whether each agent **adopts**,
**rejects**, or merely **surfaces** the false fact, and whether the final answer
asserts the false fact or the ground truth.

## Result (n = 7 tasks)

| Outcome | Tasks |
| --- | --- |
| ground truth wins | 5 / 7 |
| false fact wins | 2 / 7 |

The benchmark's keyword CPR score is unreliable in **both directions**:

- `CPR-003`: keyword score 1.0 (looks polluted), but the ground-truth agent
  rejected the false fact every turn and the final answer asserts the truth.
- `CPR-006` and `CPR-009`: keyword score 0.0 (looks clean), but every agent —
  including the ground-truth agents — adopted the false fact and built the final
  answer on it.

Three of seven keyword scores mislead; the two real cascade failures (CPR-006,
CPR-009) both scored 0.0.

## The two cascade failures

1. `CPR-006` — **unanimous adoption**: every agent, including those given the
   ground-truth S3-bucket context, repeated and built a workflow on the false
   `/tmp/` staging claim; the final answer endorses the false mechanism.
2. `CPR-009` — **ground-truth agent flips**: the QA agent initially flagged the
   CSV-vs-JSON discrepancy, then adopted the false JSON/nested/cents claim in
   later turns; the final answer builds entirely on the false fact.

## The five rejections (distinct mechanisms)

- `CPR-003`: ground-truth agent persistently quotes-and-rejects the false fact.
- `CPR-007`, `CPR-023`: the seed agent recants after seeing the ground truth.
- `CPR-020`: the ground-truth agent adopts, then corrects in the last turn.
- `CPR-040`: the seed agent itself labels the false fact a red herring.

## Interpretation

- **The keyword CPR metric is literal-only, exactly as RTD was.** It counts a
  string, not a belief. It reads 1.0 when the false fact is quoted-but-rejected
  and 0.0 when the false fact is paraphrased-but-adopted. The semantic
  adoption-vs-rejection layer is the RQ2 analog of RQ1's literal-vs-semantic
  layer.
- **False information genuinely cascades in a minority of cases (2/7)**, and
  when it does, it is either unanimous (ground-truth agents fail to act on their
  own correct context) or self-reinforcing (an agent flags the discrepancy and
  then flips under the seed's repetition).
- **The seed agent is not the only failure point**: in CPR-040 the seed itself
  rejects its injected false fact, and in CPR-007/023 the seed recants. So
  propagation depends on downstream agents acting on (or ignoring) their own
  ground truth.

## Limits

- n = 7 tasks, one model, one realization; LLM-judge only.
- The CPR keyword scorer's own semantics (what exactly "pollution rate" counts)
  were not audited beyond the observed keyword-vs-outcome mismatch.
