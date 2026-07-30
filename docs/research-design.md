# Research design v0.2

## Working claim

The contribution is not “a lifecycle exists.” MAST and From Spark to Fire
already provide stage/failure taxonomies and lifecycle-like defenses. The
intended contribution is narrower:

1. identify possession, surfacing, delivery, actual exposure, integration or
   action adoption, commitment execution, verification, actuation, recovery and
   relapse at artifact/opportunity level;
2. state which transitions are actually identifiable from a trace;
3. estimate controlled interventions with matched assignments and transparent
   missingness; and
4. test process measurements and final utility on the same recognized task run.

Tentative title:

> From Error Exposure to Recovery: Mechanistic Lifecycle Analysis and
> Controlled Interventions in LLM Multi-Agent Collaboration

## Research questions

- **RQ1 — omission and commission:** At which identifiable transition do
  required true information and false artifacts fail or spread?
- **RQ2 — graph/protocol:** What is the total effect of a natural
  graph/protocol bundle, and—separately—what changes after actual exposure when
  opportunities and aggregation are controlled?
- **RQ3 — model assignment:** When does heterogeneous role assignment create
  interface mismatch, and when does error diversity help correction under
  counterbalanced role/order assignments?
- **RQ4 — governance:** Which pre/post verification and
  detection-only/containment/rollback policy improves safe and usable task
  completion under matched clean/corrupt budgets?
- **RQ5 — execution:** How often do acknowledged plans and commitments become
  fulfilled, breached or contradicted by tool/patch evidence?

## Artifact/event unit

An artifact is an immutable claim, correct fact, constraint, requirement, plan,
commitment, interface contract, tracer, patch claim or test result. An
opportunity has a stable turn/call/message/action ID. Text appearance,
endorsement, plan adoption and action dependence are different evidence levels.

The state machine supports:

- possession without surfacing (HiddenBench/RTD omission);
- delivery without prompt exposure;
- exposure without integration;
- marker mention without endorsement;
- pre- or post-adoption verification;
- correct detection without governance actuation;
- containment/rollback followed by recovery or relapse; and
- correct information delivery followed by commitment breach.

## Experiment sequence

### Stage 0 — offline schema and annotation calibration

- deterministic counterexample fixtures for omission, false adoption,
  true-artifact rejection, pre/post verification, incomplete/tool-error checks,
  detection-only, containment, rollback, relapse, commitment breach and invalid
  tool calls;
- validate the actual annotation/judge pipeline against MAST's public
  triple-human subset, preserving multi-label confusion and agreement;
- do not emit inferential intervals for a single engineering realization.

### Stage 1A — native AgentCollabBench instrumentation smoke

Run the 12 pinned RTD/CPR tasks with their untouched native task/topology,
homogeneous model assignment and no added in-system verifier. This is a
deliberately difficult medium/hard instrumentation sample, not a representative
benchmark estimate. Preserve the full result and exact provider requests.

RTD measures required true-tracer surfacing/retention/omission. CPR measures
false-content exposure and provisional surface reproduction; semantic/action
adoption requires calibrated annotation. Diagnostic scores remain separate from
task outcome.

### Stage 1B — derived controlled stress suite (paused)

The old 144-cell topology/composition/verification matrix is
`AgentCollabBench-derived`, unvalidated and paused. It can resume only after:

- topology realism and metric-artifact-isolation review;
- fixed external final aggregation/output target;
- matched speaker multiset, turn/call cap, tools and stopping rule;
- recorded message/token/hop/exposure opportunities;
- clean/sham/corrupt mirrors;
- governance verification and actuation implemented as separate runtime hooks;
- homogeneous first, then a fixed heterogeneous model multiset with
  role/order/source rotation; and
- repeats chosen from observed within-task variance and budget.

Report a natural graph/protocol **total bundle effect** separately from an
exposure-standardized transition effect. Do not call either an official
AgentCollabBench topology replication.

### Stage 2A — HiddenBench omission bridge

Measure authorized private-information possession, speaking opportunities,
surfacing, communication completion, exact prompt exposure, integration, hidden
context leakage and group pre/post outcome. Include an equal-output-budget
verbose control because Reveal-All also changes communication instructions.

### Stage 2B — TeamBench verifier bridge

Separate requirement visibility, workspace/report access, write/execute
authority and shared history. Preserve missing/invalid attestations, isolated
deterministic grader results, evidence provenance, role violations and tool-call
validity. Include Solo, Restricted, No-Plan, No-Verify and Full-Team contrasts.

### Stage 3 — CooperBench primary collaboration outcome

Use Solo, Coop and no-communication plus a semantic-contract intervention.
Record feature-A/B results, branch/final patches, naive/union/resolver merge
tiers, messages, OpenHands actions and commitment fulfillment. Cluster by
feature pool/shared base PR; counterbalance heterogeneous A/B feature
assignment. Start with a four-task container smoke before any expansion.

### Stage 4 — external/ecological validation

- stratified SWE-bench Verified as the recognized external software anchor;
- MultiAgentBench as a secondary published ecological layer, prioritizing
  deterministic environments and explicitly modeling tool-call validity;
- social-adoption/BSS study only as a separate small mechanism experiment with
  user/peer pressure and random/accuracy/dummy-prior controls.

## Controls and estimands

Required controls include:

- single agent and action/cost-matched Solo;
- no-communication where meaningful;
- no-injection clean and matched sham/correct-artifact arms;
- corrupt assignment with manipulation-check failure retained in ITT;
- verification-only versus verification plus containment/rollback;
- same task, pair seed, prompt template, tool/access policy, stopping rule and
  final scorer except for the pre-registered intervention;
- model-role/source/order counterbalance;
- actual exposure-path and opportunity accounting; and
- clean utility, false rejection, collateral repair/harm, task outcome, tokens,
  calls, actions, latency and cost reported separately.

Primary rates state their denominators. Missing, invalid, inconclusive, timeout
and tool error remain separate. `finite_window_secondary_adoption_count` is a
secondary descriptive measure with a registered window and attribution rule,
not an epidemic reproduction number. DAG analysis uses time-expanded
reachability; spectral heuristics are reserved for recurrent graphs.

## Statistical plan

- `pair_id = task × repeat × assignment block`; every condition in a pair shares
  the assigned sampling seed when the provider supports it.
- Execution order is randomized with a separate schedule seed.
- Use task/question as the minimum cluster; CooperBench uses feature pool/shared
  base PR. Never treat turn, edge, agent or feature pair as automatically
  independent.
- Report planned, observed, paired and missing-by-condition counts. Default
  paired analysis fails on a missing cell; registered sensitivity/ITT views are
  shown alongside any complete-case view.
- One-repeat smokes are descriptive and inference-ineligible.
- Choose repetitions after a variance/budget gate. Confirmatory models include
  task/cluster and repeat structure, model-by-intervention interaction,
  multiplicity control and a manipulation-check ledger.
- Calibrate the actual fixed judge with blinded, stratified human audit and
  per-label/per-metric confusion—not merely a different model name.

## Main validity boundaries

- Native task/topology associations are not randomized topology effects.
- A rewired graph changes routing, leaf aggregation, context and opportunities.
- Exact tracer/false-fact survival is not semantic fidelity or belief.
- User sycophancy, horizontal peer conformity and hallucination are different.
- Attestation validity and task truth come from separate channels.
- Detection without enforceable isolation or rollback is not recovery.
- Clean utility can fall even when false propagation falls.
- AgentCollabBench diagnostic scores cannot establish practical task value.
- Learned merge/resolver output must not hide pre-resolver collaboration failure.
- Synthetic, adapted and real-repository task strata are reported separately.
