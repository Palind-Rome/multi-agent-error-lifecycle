# RQ1 findings — Codex-compaction derived suite (compact arm)

Human-adjudicated. The LLM-judge pass was reviewed by the user: all 9 tracer
labels confirmed (9/9 agreement, Cohen's kappa = 1.0, n = 9). This arm is the
treatment; the native RTD runs (`docs/rq1-rtd-findings.md`) are the control.

## What the compact arm is

At every inter-agent handoff in the seven untouched AgentCollabBench RTD tasks,
the parent agent's verbatim output is replaced by a Codex-style
**checkpoint-compaction summary**: the parent output is summarized with Codex's
verbatim `COMPACT_PROMPT`, and the downstream agent receives `SUMMARY_PREFIX`
plus that summary instead of the raw text. The prompts are copied verbatim from
`openai/codex` (`codex-rs/prompts/templates/compact/`). This is the real
compaction mechanism, not a bespoke "summarize in N words" treatment.

Same homogeneous `qwen/qwen3-30b-a3b-instruct-2507`, temperature 0,
`purpose=engineering_smoke`, `analysis_eligible=false`.

## Result

| Stage | Label distribution (n = 9 tracers) |
| --- | --- |
| compaction | 9 / 9 `semantic_preserved` |
| downstream | 6 `semantic_preserved`, 2 `omitted`, 1 `distorted` |

First-loss stage: 6 `none`, 3 `downstream`, 0 `compaction`.

| First-loss stage | Tracers |
| --- | --- |
| `none` (preserved end-to-end) | 6 / 9 |
| `downstream` (lost in the final answer) | 3 / 9 |
| `compaction` (lost in the handoff summary) | 0 |

The three downstream losses:

1. `TASK-SWE-RTD-092` (`PERF-SEC-DASH-RT1`): compaction retained "never exceed
   50.00 ms" + "AES-256" verbatim; the leaf answer was a
   "system sealed & terminated" closure message that mentioned neither.
2. `TASK-DATAENG-RTD-108` (`TECH-BQ-99`): compaction retained "BigQuery-only";
   the final answer was a post-cutover monitoring report with no BigQuery,
   warehouse, or analytics mention.
3. `TASK-DEVOPS-RTD-103` (`PERFSEC-DP89`): compaction retained "maximum 89.0 ms"
   and even added "no relaxation … not average"; the final Security Auditor
   report re-stated it as "P95 latency ≤ 89.0 ms" (P99 = 89.2 ms) and reduced DB
   encryption to `sslmode=require`. The hard bound was relaxed to a percentile.

## Literal RTD is noisy under compaction

The benchmark's own RTD diagnostic is unstable here (no seed passthrough, so
each run is an independent realization). Repeats confirm it:

| Task | Literal RTD across realizations |
| --- | --- |
| `TASK-DATAENG-RTD-060` | 1.0, 1.0, 1.0, 0.0 |
| `TASK-DATAENG-RTD-108` | 0.667, 0.667, 1.0 |
| `TASK-DEVOPS-RTD-103` | 1.0, 1.0 (one network failure) |

So literal tracer survival is stochastic under compaction, while the semantic
layer (same first-loss stage across runs) is the stable signal. The
literal-vs-semantic gap is the point of the study, not noise to be averaged
away.

## Interpretation

- **Codex compaction is faithful, not lossy.** All 9 anchors' meanings survived
  the compaction summary. This is a direct consequence of the prompt, which
  explicitly requires "critical data, examples, or references" to be retained.
  The naive hypothesis "summarization drops information" does not hold for the
  real Codex compaction mechanism — the mechanism is engineered to preserve
  critical data.
- **Loss concentrates at downstream adoption, not at summarization.** The three
  losses are all in the final answer: two constraints were surfaced and
  delivered but not adopted (omitted), one was adopted but relaxed (distorted).
  This matches the lifecycle claim that possession → surfacing → delivery →
  exposure can all succeed while integration/adoption still fails.
- **The numeric-relaxation failure mode is reproduced and localized.** Native
  RTD-103 relaxed "89.0 ms max" to a mean/P95 at an intermediate relay hop.
  Under compaction the summary *re-emphasized* the hard bound, yet the
  downstream agent still converted it to "P95 ≤ 89.0 ms". The tendency to turn a
  hard bound into a statistical target lives in the downstream agent, not in the
  relay or the summarization step.

## One adjudicated borderline

`TASK-DATAENG-RTD-059` (`ANON-HASH-PII`): the anchor is "tokenization with a
non-reversible, salted hash function"; the summary said "salted SHA-3-512
hashing". The judge labeled this `semantic_preserved` (non-reversible + salted +
hash all retained). It was flagged for adjudication because a stricter reader
could call it `distorted` (the "tokenization" technique is dropped and a
specific algorithm SHA-3-512 is introduced); the user confirmed `semantic_preserved`.

## Limits

- n = 9 tracers, one model, temperature 0, no seed passthrough; single
  realization per task (two for RTD-060).
- The compact arm changes the downstream input (summary vs raw), so it is not a
  causal decomposition of the native relay distortion; it is a separate derived
  suite whose control is the native arm.
