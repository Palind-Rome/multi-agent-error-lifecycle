# RQ1 semantic annotation — Codex-compaction derived suite

## What the compact arm adds

The native RTD relay forwards each parent agent's verbatim output. The compact
arm replaces that verbatim handoff with a Codex-style **checkpoint-compaction
summary**: the parent output is summarized with Codex's verbatim
`COMPACT_PROMPT`, and the downstream agent receives `SUMMARY_PREFIX` plus that
summary. This inserts one new observable stage into the lifecycle between
surfacing and downstream exposure.

| Stage | Question |
| --- | --- |
| surfacing | Does the root agent's output convey the anchor's **meaning**? |
| **compaction** | Does the handoff summary preserve the anchor's **meaning**? |
| downstream exposure | Is the meaning reflected in the downstream agent's answer/action? |

The compaction summary text is the summarizer's `response_content`, recorded per
handoff in `compaction-summaries.jsonl` (each record carries the raw parent
output as its input and the downstream `receiver_agent_id`).

## Rubric (unchanged from native)

| Label | Rule |
| --- | --- |
| `semantic_preserved` | meaning (entities, values, polarity, scope, conditions) correct |
| `literal_only` | tracer ID string appears, meaning not engaged |
| `distorted` | meaning changed (value, polarity, entity, condition) |
| `omitted` | no corresponding meaning appears |
| `uncertain` | complete text observed but rubric cannot decide |
| `unobservable` | stage/text not completely observed |

## Why the compaction prompt matters for interpretation

Codex's `COMPACT_PROMPT` explicitly asks the summarizer to retain "critical
data, examples, or references", so a faithful Codex compaction is biased toward
preserving hard constraints. This is not a contrived "summarize in N words"
treatment: it is the real mechanism, and its prompt's data-retention clause is
part of the mechanism. When a compaction summary does drop a constraint, that
is therefore the more informative observation.

## Expected contrasts

- **Literal RTD** is expected to drop under compaction (the downstream agent
  paraphrases and drops the canonical tracer ID), even when the meaning is
  intact — the native-vs-compact literal gap is the benchmark's own metric, not
  a semantic claim.
- **Semantic first-loss stage** distinguishes `compaction` loss (the summary
  itself distorts/drops the anchor) from `downstream` loss (the summary is
  faithful but the downstream agent does not reflect the meaning).
