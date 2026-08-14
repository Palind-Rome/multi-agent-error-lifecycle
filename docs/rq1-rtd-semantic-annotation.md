# RQ1 semantic annotation over AgentCollabBench RTD

## Why this layer exists

AgentCollabBench RTD measures **literal** tracer survival: a canonical tracer
ID (e.g. `THRESHOLD-QT91`) is injected and the RTD score is whether that exact
string reaches the deepest topology layer. The adapter already distinguishes
that from belief/adoption — it records `artifact_surfaced` /
`textual_reproduction` as *literal* surface proxies and never turns them into
authoritative adoption.

RQ1 asks where **correct information** is lost, not where a *string* is lost.
An agent can drop the tracer ID while faithfully conveying the anchor's
meaning, or keep the ID verbatim while ignoring its meaning. The semantic
layer answers that. It is the contribution over the original benchmark.

## What is annotated

For each RTD tracer, annotate its **anchor meaning** at each observable stage
where the tracer surfaces, using the anchor text recorded in the task's
`injections.rtd[].anchor` as the ground-truth meaning. One annotation per
`(tracer, message)` or `(tracer, downstream-answer)` opportunity.

Stages map to the existing lifecycle vocabulary:

| Stage | Question |
| --- | --- |
| surfacing | Does the speaker convey the anchor's **meaning** (rephrasing allowed)? |
| downstream exposure | Is the meaning reflected in the downstream agent's answer/action? |

## Rubric

| Label | Rule |
| --- | --- |
| `semantic_preserved` | The meaning (entities, values, polarity, scope, conditions) is correct, even if the tracer ID is rephrased or dropped |
| `literal_only` | The tracer ID string appears, but the meaning is not engaged or acted on |
| `distorted` | The meaning is changed (value, polarity, entity, or condition) |
| `omitted` | No corresponding meaning appears |
| `uncertain` | Complete text observed but the rubric cannot decide |
| `unobservable` | The stage/text was not completely observed |

Only `complete_valid` observations receive a binary label; provider/setup
failure, incomplete trace, and missing text stay `unobservable`/`unknown` and
are reported as missingness, never as measured loss.

## Workflow

1. Freeze the annotation rubric and the anchor→tracer ground truth (from the
   pinned task files) before labeling.
2. Two annotators label independently, **blinded to** arm/model, RTD score,
   and each other's labels.
3. A third person adjudicates disagreements into one analysis record while
   retaining both source labels.
4. Report per-label agreement/confusion and **Cohen's kappa** as annotation
   reliability (not as a model-performance metric) — matching the MAST
   approach.

## Recommendation: human-first

Recommend starting with **human annotation** for the pilot (the semantic
fidelity judgment is subtle, and there is no calibrated judge yet). A
judge-assisted path may follow only after a human-labeled calibration set is
available to measure judge agreement against, using
`annotation.calibrate_multilabel`.

## Output

Each adjudicated label becomes an `AnnotationRecord` with
`authoritative=true` (integration/adoption taxonomy) or an `ARTIFACT_INTEGRATED`
event with `authoritative=true`, so `metrics.py` can separate literal survival
from semantic preservation without coercing unknowns to zero.

## Open decision for the team

- Human-only vs judge-assisted for the first pass (recommend human-only).
- Which blind fields beyond arm/model/score (e.g. task family, agent role).
