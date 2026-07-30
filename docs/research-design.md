# Research design v0.1

## Core claim

Existing work establishes that LLM multi-agent systems fail, lose information,
and can amplify a planted falsehood. The intended contribution here is narrower:
identify which conditional transition in an error lifecycle causes the final
failure, and test whether the same process measurements predict outcome on
recognized tasks.

The error-bearing observational unit is an immutable atomic artifact: a claim,
constraint, requirement, commitment, or derived result. A run may contain many
artifacts linked through `parent_artifact_ids`.

## Research questions

- **RQ1:** Which transition—generation, transmission, adoption, verification, or
  recovery—dominates failure under each task family?
- **RQ2:** Does topology change only exposure opportunity, or does it also change
  adoption and correction after exposure?
- **RQ3:** When do heterogeneous models increase interface mismatch, and when do
  less-correlated errors improve correction?
- **RQ4:** Which verification policy minimizes false adoption while preserving
  task success under a matched token budget?

## Minimum viable sequence

### Stage 0: instrumentation

Use the deterministic runner and hand-constructed traces to verify that every
metric has the intended denominator. If artifacts were adopted but no check was
attempted, `P(verify | adopted)=0`; rates conditioned on a completed check remain
undefined rather than receiving an artificial perfect score.

### Stage 1: controlled mechanism identification

Select a balanced RTD/CPR subset from AgentCollabBench. Pair every task and seed
across linear chain, converging DAG, and fully connected source conditions;
rewire matched task prompts into star conditions in our own harness. Compare homogeneous versus
heterogeneous teams and no verification versus evidence-required verification.
Store the complete upstream `RunResult`, actual provider request, and lifecycle
trace; never rely on the upstream CLI summary alone.

### Stage 2: context asymmetry and verifier behavior

Use HiddenBench or TeamBench to distinguish:

- information unavailable to the agent;
- information present in the prompt but omitted from its response;
- information repeated but not used in an action;
- information adopted, checked, falsely accepted, or corrected.

### Stage 3: recognized outcome anchors

Use CooperBench for paired coding collaboration and a stratified SWE-bench
Verified subset for deterministic task outcome. Do not claim practical value
unless lifecycle changes co-occur with final task improvement. Add Terminal-Bench
only after the coding pipeline is stable.

## Required controls

- single-agent under the same model and maximum token budget;
- independent best-of-N or majority aggregation;
- multi-agent with the same aggregate token budget;
- no-injection clean control;
- injection without downstream exposure;
- identical task, seed, prompt templates, stopping rule, judge and tool access;
- explicit ordering counterbalance when roles use different models.

## Primary endpoints

Mechanism endpoints:

- transport delivery rate and artifact edge-survival rate;
- semantic fidelity conditional on exposure;
- `P(adopt | exposed)`;
- `P(verify | adopted or disputed)`;
- false-accept and false-reject rates;
- `P(recover | detected)`;
- error reproduction number;
- maximum adoption hop;
- time to detection and time to recovery;
- contaminated-agent-turn AUC.

Outcome endpoints:

- deterministic task pass/score;
- safe completion;
- input/output tokens, API cost, wall latency;
- blocked-correct-information rate.

The lifecycle, task, and cost axes remain separate. They are not collapsed into
a single leaderboard score.

## Statistical plan

Pair task and seed across all conditions. Report bootstrap confidence intervals
for descriptive effects, then use hierarchical regression with task and seed
random effects and topology/model/policy fixed effects. Mediation claims require
the topology intervention to precede exposure/adoption measurements and must be
phrased cautiously unless sequential ignorability is defensible.

Pre-register:

- primary metric and direction for each RQ;
- semantic adoption rubric and judge prompt;
- judge-human audit size and agreement statistic;
- exclusion, retry, timeout, malformed-output and missing-data rules;
- maximum tokens, turns and dollar cost;
- multiplicity correction for secondary analyses.

## Threats to validity

- Exact tracer survival is not semantic fidelity.
- Textual repetition is not adoption; action dependence is stronger evidence.
- A single LLM judge may share the tested model's blind spots.
- Fixed topologies can confound topology with prompt and agent count.
- More agents usually means more tokens and chances to solve the task.
- Synthetic enterprise scenarios do not establish real repository performance.
- Homogeneous model results do not generalize to heterogeneous teams.
- Planted falsehood behavior can differ from naturally generated errors.
- Spectral-radius asymptotics do not describe finite-horizon propagation in a
  directed acyclic chain, whose adjacency spectral radius is zero.
