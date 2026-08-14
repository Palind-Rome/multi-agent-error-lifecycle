# Research design v0.3 — RQ1 first

## Current scope and claim

The paper keeps three high-level research questions, but the current study
implements and evaluates **RQ1 only**. RQ2 and RQ3 are deferred until the RQ1
measurement pipeline is calibrated. Communication topology and heterogeneous
model assignment are controls or later robustness checks, not research
questions in the current study.

The first contribution is narrower than a general error-lifecycle taxonomy:

> Under a fixed task, model, communication protocol and recipient context cap,
> determine where required correct information first becomes unavailable when
> a tool result is replaced by an abstractive natural-language summary, relative
> to raw forwarding and a length-matched fidelity control, and measure the
> resulting downstream task effect.

The study distinguishes observable transport from semantic judgment. Literal
presence, delivery, prompt exposure, correct semantic preservation and
downstream use are separate measurements. Missing observations and missing
annotations remain unknown rather than becoming measured failures or zeros.

## Research questions

- **RQ1 — correct-information loss (current):** Where does required correct
  information first disappear when an agent transforms a tool result into a
  natural-language summary, and how does that affect the downstream answer?
- **RQ2 — false-information propagation (deferred):** How do misunderstandings,
  sycophancy and hallucinated claims propagate and affect later agents or task
  outcomes?
- **RQ3 — governance (deferred):** How effective and costly are
  verification-only and verification-plus-containment/rollback policies?

Runtime context compaction is not part of the first RQ1 experiment. It lacks a
stable, framework-independent intervention boundary and can combine summarizing,
truncation, context overflow and vendor runtime behavior. It may become a
separate replication after the explicit summary transformation is understood.

## RQ1 estimand and experimental arms

The experimental unit is one complete `fixture x repeat x arm` run. The fixture,
not an individual fact, message, turn or agent, is the minimum analysis cluster.

Each controlled fixture contains an immutable tool result, a downstream
question and answer key. The pilot target is six pre-declared required facts and
six distractor facts per fixture, balanced across position, numbers/units,
negation and conditional qualifiers. Inputs must remain well below the context
window, and automatic context compaction or truncation must be disabled.

| Arm | Recipient input | Purpose |
| --- | --- | --- |
| `raw_passthrough` (C0) | Complete verbatim tool result | Operational baseline |
| `length_matched_reference` (C1) | Human/rule reference of the same budget that preserves every required fact | Tests whether the bandwidth target is feasible |
| `abstractive_summary` (T) | Model-generated natural-language summary under the same registered budget as C1 | Main treatment |

The primary policy contrast is T minus C0: the total effect of replacing raw
tool output with the registered summary policy. T minus C1 isolates model
summary fidelity at approximately fixed recipient bandwidth. C1 minus C0
describes the effect of the shorter representation itself. None of these is
called a runtime-compact effect.

Held fixed within a fixture:

- immutable source tool result, downstream question and answer key;
- downstream model, prompt template, temperature, context/output caps and
  stopping rule;
- two-agent linear handoff, role prompts, tool status and communication rounds;
- provider/model version and price table; and
- downstream scorer and annotation rubric.

Run order is randomized independently of any provider sampling setting. When a
provider does not honor a seed, repeats are independent realizations and must
not be described as seed-paired samples.

## Transformation and lifecycle evidence

Every intervention must have a typed transformation record with stable IDs and
lineage to the source tool-result event and consuming downstream prompt. It
records:

- source and transformed content hashes (raw text remains private);
- arm/method and derived-suite identity;
- producer type, model/version and prompt-template hash when applicable;
- source and target character/token counts and registered budget;
- required-fact IDs expected at the transformation boundary; and
- parent event, emitted message and included prompt IDs.

For each required fact, one run audits this sequence:

```text
source tool result observed
  -> transformation output observed
  -> handoff sent and delivered
  -> exact downstream provider request observed
  -> fact semantically preserved/reflected
  -> downstream structured answer correct
```

The general lifecycle vocabulary remains usable across benchmarks, but evidence
availability is benchmark-specific. AgentCollabBench RTD supplies literal
tracer evidence; it does not by itself establish semantic understanding,
belief, action dependence or recognized task success.

## Primary and secondary measures

Two run-level co-primary outcomes are registered for the measurement pilot:

1. **Summary-stage required-fact retention:** correctly preserved required
   facts divided by all initially required facts, only when the complete
   transformation output and fact annotations are observed. An observed valid
   empty or fact-omitting output is a measured loss; an unavailable response,
   incomplete trace or missing annotation is unobserved, not zero.
2. **End-to-end required-fact success (ITT):** required facts correctly
   reflected in an observed downstream structured answer divided by all
   initially required facts. The denominator is not conditioned on exposure or
   any other post-treatment mediator. Provider/setup failure or an unobserved
   answer remains missing and is reported by arm rather than imputed as failure.

Required supporting reports:

- first identifiable loss stage for every fact/path;
- surfacing, delivery/literal-survival and exact-request exposure opportunities;
- request-observation and semantic-annotation coverage;
- authoritative semantic preservation/integration rate and binary denominator;
- unsupported or contradicted fact rate;
- objective task score where the suite supplies one; and
- actual compression ratio, tokens, calls, latency and cost.

The repository's `RunMetrics` is a candidate superset. Metrics concerning false
adoption, governance, rollback, topology or commitments are not primary RQ1
outcomes merely because fields already exist.

## Human annotation calibration

Required facts are annotated separately in the transformation output and final
answer. Every label retains an evidence span and target event ID.

Transformation labels:

- `preserved_correctly`;
- `omitted`;
- `distorted_or_contradicted`;
- `partial`;
- `uncertain`; and
- `unobservable`.

Downstream labels:

- `correctly_reflected`;
- `mentioned_only` (not demonstrably used);
- `incorrectly_reflected`;
- `absent`;
- `uncertain`; and
- `unobservable`.

The instrumentation pilot requires 100% disposition coverage for observable
fact opportunities before aggregate semantic rates are interpreted. Two
annotators independently label the full pilot while blinded to arm, model,
benchmark score and later-stage text; disagreements are adjudicated by a third
person. Report per-label agreement/confusion and Cohen's kappa as annotation
reliability, not as a model-performance metric.

## Execution sequence and gates

### Stage 0 — offline contract calibration (current)

- implement the typed transformation lineage and three-arm contract;
- run a deterministic `1 fixture x 3 arms` calibration without an API;
- test missing/unobservable evidence, budget violations and fact-level scoring;
- implement a closed benchmark-plugin registry and one-assignment executor; and
- keep all raw tool results, summaries and prompts in git-ignored private paths.

### Stage 1 — three-run real engineering calibration

Run one approved derived fixture once in each arm with the fixed homogeneous
Qwen model. Manually audit every source result, transformation, handoff,
provider request and final answer. This stage remains
`purpose="engineering_smoke"` and `analysis_eligible=false`.

### Stage 2 — RQ1 measurement/variance pilot

Provisional size, to be frozen before calls:

- eight controlled fixtures;
- C0, C1 and T: three independent downstream repeats each; and
- `8 x 3 x 3 = 72` total runs.

The C1 reference text may be created once and held immutable, but its downstream
model run is repeated like the other arms. Because provider seeds are not
assumed, the design does not claim random-number pairing. T and C1 are matched
on transformation-output bandwidth; C0 deliberately contains more actual input
and estimates the operational raw-versus-summary policy contrast.

This pilot estimates instrumentation missingness, annotation disagreement,
within-fixture variation and cost. It does not provide a confirmatory
generalization claim. Main-study size is chosen only after the variance and
budget gate.

### Stage 3 — outcome and ecological validation

- **AgentCollabBench:** first mechanism/instrumentation bridge. Untouched native
  RTD results remain separate; inserting a summary treatment creates an
  explicitly named derived suite.
- **CooperBench:** later coding-collaboration outcome validation using objective
  tests and separate pre-merge/merge/resolver outcomes. It requires its own
  plugin and required-information annotation.
- **HiddenBench:** optional distributed-information semantic bridge with an
  equal-bandwidth control.
- **MultiAgentBench:** deferred breadth layer because environment, protocol,
  topology and tools are bundled.
- **BrowseComp/GDPval:** not native MAS benchmarks; using them would require a
  separately justified derived MAS harness.

## Readiness rule

Formal or inferential data collection must not begin until all of the following
are true:

1. fixture manifest, fact keys, arms, budgets and stopping rule are frozen and
   hashed;
2. transformation lineage and exact provider requests pass manual audit;
3. unknown/unobservable values cannot enter a binary numerator or denominator;
4. annotation protocol and blinding fields are frozen and calibrated;
5. provider/model/version, unsupported seed status and price ceilings are
   rechecked;
6. experiment-level call/token/time/cost caps are enforced;
7. every planned run has an analysis-eligibility decision made before execution;
8. full offline tests pass; and
9. planned, observed, missing and excluded counts can be reconciled by arm.

## Main validity boundaries

- Exact tracer retention is not semantic fidelity or understanding.
- A summary intervention added to AgentCollabBench is not untouched native
  AgentCollabBench.
- Shortening and abstraction differ; the three arms are required to diagnose
  them.
- Facts and turns nested in one fixture are not independent samples.
- A missing request or annotation is not a measured loss.
- `validate` establishes record integrity, not scientific validity.
- A single-run `summarize` result is not a cross-run estimate.
- Multiple Qwen models are a later robustness study, not part of the first
  measurement pilot.
