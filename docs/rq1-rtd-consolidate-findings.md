# RQ1 findings — Codex leader-consolidation arm + three-arm synthesis

LLM-judge annotated. The consolidation arm is a second treatment over the native
relay; the native arm (`docs/rq1-rtd-findings.md`) and the compact arm
(`docs/rq1-rtd-compact-findings.md`) are the two references.

## What the consolidation arm is

Codex multi-agent communication differs from per-hop compaction in that a
**leader consolidates the full set of subagent results into one answer at the
end**, rather than summarizing each individual handoff. This arm reproduces that:
it takes each completed native (verbatim) relay transcript, then makes **one**
leader call over the full conversation using the verbatim Codex `COMPACT_PROMPT`.
The consolidation summary is the artifact under test.

## Result (n = 9 tracers)

| Stage | Result |
| --- | --- |
| literal tracer ID | 9 / 9 survive |
| semantic label | 8 `semantic_preserved`, 1 `distorted` |

The single distortion is `TASK-DEVOPS-RTD-103` (`PERFSEC-DP89`): the summary
wrote "max response time = 89.0 ms **(P95)**" — and this relaxation was
**inherited**, i.e. already present in the native relay transcript the leader was
given. The leader did not introduce it.

## Interpretation

- **Leader consolidation is faithful, not lossy, and not corrective.** The
  leader preserved 8/9 anchors and reproduced the one distortion that already
  existed in its input. It neither created new distortion nor cleaned up prior
  distortion.
- **The three arms now localize RQ1's answer.** NL summarization — whether
  per-hop (compact arm) or whole-conversation (this arm) — is engineered to keep
  critical data and does so. The correct information is lost at the **agents**,
  not at the summarizer:
  - native relay: 2/9 agents relaxed a hard numeric bound while re-stating it;
  - compact arm: 3/9 downstream answers omitted or relaxed a constraint that the
    summary had faithfully delivered;
  - consolidation arm: 0/9 introduced at the leader, 1/9 inherited from the relay.

## Three-arm synthesis (RQ1 preliminary answer)

For the tested setup (AgentCollabBench RTD, one Qwen model, temperature 0):

> A tool result replaced by a natural-language summary is **not** where required
> correct information is lost. The compaction/consolidation prompt is designed to
> retain "critical data, examples, or references", and it does. Correct
> information first becomes unavailable when an **agent** re-phrases or adopts the
> information: relay re-statement relaxes hard numeric bounds, and downstream
> answers omit or relax constraints they were faithfully given. The recurring
> failure mode is **numeric relaxation** (a hard maximum becomes a P95/mean), and
> it originates in agents, not in summarization.

## Limits

- n = 9 tracers, one model, one realization per task; LLM-judge only (human
  review pending).
- The consolidation reuses native transcripts, so it cannot be treated as a
  full causal decomposition; it is a counterfactual "what would a leader have
  said" over the already-recorded relay.
