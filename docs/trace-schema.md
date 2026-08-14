# Trace schema v0.2.0

Each JSONL file contains exactly one run. Records are immutable, versioned, and
validated both individually and across the trace.

## Why v0.2 is not a field-only migration

v0.1 treated “a controlled injection reached the source” as
`artifact_generated` and counted generation as contamination. It also allowed a
partial handoff to become prompt exposure and allowed marker reproduction to
enter primary adoption. Those semantics are not backward compatible. Old traces
must be re-imported from their raw benchmark result; changing only the version
string is invalid.

## Record families

- `run_manifest`: protocol/native-derived identity, task, condition, paired seed,
  assignment, cluster, analysis eligibility, model/role/access policy, topology,
  judge provenance and code/upstream pins.
- `information_assignment`: initial and authorized holders, visibility, and
  whether a fact is required for the solution.
- `injection`: target, corruption kind, sham status, nominal/realized dose,
  ground-truth reference and manipulation-check verdict.
- `artifact`: typed claim, fact, requirement, plan, commitment, interface
  contract, tracer, patch claim, test evidence or tool output, with origin,
  truth status and lineage.
- `prompt`, `message`, `model_call`, `tool_call`: exact request/transport/action
  observations with stable IDs, hashes, status and nullable usage.
- `evidence`: evidence source, producer, command/tool outcome, snapshot/digests,
  independence/replay and validity.
- `annotation`: versioned multi-label/proxy/judge output with target/evidence
  spans, blindness, model/prompt hash, confidence and identifiability.
- `event`: ordered lifecycle state transitions.
- `attestation`: valid/missing/invalid/timeout/error verifier output, separate
  from task truth.
- `grader_run`: isolated grader provenance and execution status.
- `outcome`: recognized, diagnostic-only, synthetic-smoke or unavailable task
  result plus termination, safe/usable completion, infection and resources.

## Lifecycle state machine

The main paths are branching, not one fixed chain:

```text
assignment/injection -> possession -> surfacing -> message sent -> delivered
    -> exact prompt exposure -> integration/adoption -> action/commitment
                                  |                    |
                                  +-> pre/post verify -+
                                          |
                                 detect -> contain/rollback
                                          -> recover -> relapse
```

Important semantics:

- `artifact_generated` means the model/environment newly produced the artifact.
  A user assertion, benchmark tracer, private fact or controlled injection uses
  `artifact_possessed`.
- `artifact_surfaced` means observable output/message content contains the
  artifact. It is not belief or action adoption.
- `message_sent` is an attempt and requires explicit
  `details.artifact_present`; `message_delivered` is a separate observation.
- `artifact_exposed` requires an observed full provider request whose target
  agent and `artifact_ids` match. Reconstructed/partial handoffs cannot produce
  it.
- `artifact_adopted` and `artifact_integrated` require
  `authoritative=true` and a pre-registered evidence level. Marker mentions live
  in annotation/surfacing records.
- Verification records timing, completion status, verdict, evidence validity,
  requirement coverage and evidence IDs. Verification does not itself imply
  containment or rollback.
- Recovery requires prior refutation and an explicit actuation event. Natural
  correction is recorded separately as `artifact_corrected`.
- Commitment fulfillment/breach requires a commitment/interface-contract
  artifact and evidence. Acknowledgement alone is not execution.

## Validation invariants

The validator rejects:

- unknown/duplicate agents, edges, artifacts, prompts, messages, calls, evidence
  or event references;
- future parent events, cross-artifact event parents, artifact lineage cycles or
  parents created later than children;
- edge endpoint mismatch;
- exposure whose prompt belongs to another agent, omits the artifact, or is not
  an observed full request;
- authoritative adoption/integration without prior exposure/possession;
- post-adoption verification before adoption, completion without matching start,
  or “valid evidence” without valid evidence records;
- rollback completion without start, recovery without detection/actuation, or
  relapse without prior containment/recovery;
- commitment outcome without a prior typed commitment;
- diagnostic/unavailable scores masquerading as task outcome;
- recognized completed outcomes without a successful, matching grader.

Every trace contains exactly one `run_finalized` event and one outcome.

## Metrics and missingness

Metric-output compatibility note: record schema v0.2 is unchanged, but two
previously misnamed metric fields now use their literal opportunity semantics.
`exposure_opportunity_count` changed from exposure-event count to eligible
delivered/surviving message units, and `adoption_opportunity_count` changed from
adoption-event count to exposure-event opportunities. Consumers that depended on the old
values should use the new `exposure_event_count` and `adoption_event_count`.
All prior metric keys remain present; added keys are additive, except that
`final_contaminated_agents` is now nullable when semantic coverage is
insufficient.

Transport is reported as `P(delivered | observed attempt)` and
`P(artifact survives | delivered)`; missing transport status has separate
coverage. `exposure_opportunity_count` is the number of delivered-and-surviving
message/artifact units addressed to a real agent, not the number of observed
exposure events. `exposure_event_count` preserves the latter count.
`exposure_observation_count` is the subset for which an exact downstream
provider request was captured **and explicitly linked** by
`message.included_prompt_id` or exposure parent provenance. An arbitrary later
prompt for the same target is not evidence that it consumed an older message.
Each message is consumed by at most one prompt; an explicitly converging prompt
may consume the latest unconsumed message from each distinct parent.
`exposure_given_delivered_survival` is
conditional on that observed subset. Messages to `__output__` are transport
units but are not prompt-exposure opportunities.

Likewise, `adoption_opportunity_count` and `integration_opportunity_count` are
exposure-event opportunities, so repeated prompts for one artifact/agent remain
separate denominator rows. Positive event counts remain available as
`adoption_event_count` / `integration_event_count` and pair counts. Semantic
rates use only binary authoritative dispositions. The metrics report the
binary rate denominator, the number of annotated (including explicitly
unknown) opportunities, and annotation coverage against all exposure events.
No authoritative disposition therefore yields a null rate, not zero.

Typed `artifact_adopted` / `artifact_integrated` events are authoritative
positives; explicit rejection and pre-adoption containment are measured
negatives, while `artifact_uncertain` is annotated but non-binary. An
`annotation` record can contribute only when it identifies an artifact/agent
pair and either uses `metadata.authoritative=true` with
`metadata.adoption_status` / `metadata.integration_status`, or an explicit
`metadata.authoritative_adoption`, `metadata.authoritative_non_adoption`,
`metadata.authoritative_integration`, or
`metadata.authoritative_non_integration` flag. The adapter's
`authoritative_adoption=false` surface proxy is missing semantic evidence, not
a negative label. An annotation targets the exposure event named in
`target_event_ids`; a pair-only annotation is accepted only when that pair has
exactly one exposure. Typed semantic events are joined through parent lineage,
with the uniquely latest preceding exposure as a conservative fallback.

Required true information reports possession, surfacing, message delivery,
literal survival, prompt exposure, and semantic-integration counts with their
opportunities. `required_information_first_loss_records` contains separate
`message_branch` and `semantic_join` rows. Branches are audited only through
prompt exposure; one semantic-join row represents integration for the whole
prompt even when it has several parents. Repeated prompts create separate join
rows. The split stage summaries prevent one join annotation from being counted
once per parent. Missing possession/surfacing telemetry uses `_unknown` stages;
surfacing becomes a measured loss only when the corresponding complete output
opportunity was observed and the artifact was absent. Missing
transport/request observations use
`delivery_unknown` or `prompt_exposure_unknown`; exposure without an
authoritative semantic disposition uses `semantic_integration_unknown`. A
holder with no observed message opportunity is retained as a holder-level
record rather than silently dropped. Possession and surfacing observation
counts/coverage are reported separately. The combined and branch/join stage
summaries are audit counts, not independent-sample estimators. False
support and true-artifact false reject use separate truth-aware denominators.

Primary adoption excludes provisional marker annotations. The finite-window
secondary-adoption count is null until `propagation_window_turns` is registered
and semantic dispositions cover its exposure opportunities. Final false
contamination and its prevalence are null when a false-artifact prompt path has
missing transport/request observation or lacks a binary authoritative adoption
disposition; the associated opportunity count, binary denominator, and
coverage are path/opportunity-level and reported explicitly. A positive
event-targeted annotation is not by itself a terminal state transition, so
final prevalence remains null without timed lifecycle state evidence.
Contamination AUC is additionally null
unless a real turn horizon is registered; it is normalized by agent count and
horizon rather than raw event count.

## Privacy

Never store API keys, authorization headers, cookies, hidden tests, gold patches
or unredacted secrets. Requests/messages may be redacted while retaining their
canonical digest. Logs for containerized coding tasks must live outside agent
containers and remain unreadable to agents.
