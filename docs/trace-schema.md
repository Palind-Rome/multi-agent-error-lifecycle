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

Transport is reported as `P(delivered | observed attempt)` and
`P(artifact survives | delivered)`; missing transport status has separate
coverage. Required true information has possession, surfacing, exposure and
integration rates. False support and true-artifact false reject use separate
truth-aware denominators.

Primary adoption excludes provisional marker annotations. The finite-window
secondary-adoption count is null until `propagation_window_turns` is registered.
Contamination AUC is null unless a real turn horizon is registered; it is
normalized by agent count and horizon rather than raw event count.

## Privacy

Never store API keys, authorization headers, cookies, hidden tests, gold patches
or unredacted secrets. Requests/messages may be redacted while retaining their
canonical digest. Logs for containerized coding tasks must live outside agent
containers and remain unreadable to agents.
