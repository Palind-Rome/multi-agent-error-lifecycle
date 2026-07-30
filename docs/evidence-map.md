# HTML-original evidence map

This ledger records the paper evidence that changed v0.2. It is not a
bibliography or a claim that every reported result has been reproduced. The
linked HTML originals were reviewed on 2026-07-30; paper facts and our design
responses are kept separate.

## MAST — Why Do Multi-Agent LLM Systems Fail?

HTML: <https://arxiv.org/html/2503.13657v3>

Paper evidence:

- Section 4 already organizes failures around pre-, during- and post-execution
  phases, while Appendices H and J connect failure modes to intervention and
  task outcomes. “Stages plus outcome” is therefore not enough novelty.
- The 1,642-trace corpus is largely model-annotated; the public
  triple-human-annotated subset has 21 traces. The reported model-annotator
  recall is 0.77, so label absence cannot be treated as ground truth.
- In Appendix H, the topology intervention also changes iteration, review and
  termination authority, and its effect differs between GPT-4 and GPT-4o.

v0.2 response:

- Treat MAST as a secondary multi-label taxonomy, not causal truth.
- Add offline multi-label calibration and preserve per-label confusion.
- Define novelty around identifiable artifact-level transitions, matched
  intervention estimates and same-run outcomes.
- Mark one-repeat engineering runs inference-ineligible.

## AgentCollabBench

HTML: <https://arxiv.org/html/2605.08647>

Paper evidence:

- Tasks are co-designed with a topology; the paper warns that arbitrary
  reassignment confounds topology effects with task-topology mismatch.
- RTD is exact canonical-tracer retention, not semantic retention. CPR is a
  treated-as-true response rate, not a majority-consensus rate.
- Appendix H attributes 21 of 22 upstream RTD losses to a root that received
  but did not emit its tracer. Injection receipt is not source generation.
- The paper does not establish correlation between diagnostic behavior scores
  and final task success.

v0.2 response:

- Split controlled-injection assignment/receipt, possession and surfacing.
- Require an exact recorded provider request for exposure.
- Keep exact markers as non-authoritative surface annotations; they never
  become primary adoption.
- Preserve diagnostic scores while leaving recognized task outcome null.
- Run a 12-task untouched-native instrumentation smoke first. Put rewritten
  tasks in a distinct, paused `AgentCollabBench-derived` suite with source hash
  and changed-field metadata.

## From Spark to Fire

HTML: <https://arxiv.org/html/2603.04474>

Paper evidence:

- The paper already defines atomic falsehoods, lineage, adoption, verification,
  blocking, rollback, retry and safe completion.
- Verification may occur before adoption, so one fixed linear lifecycle is
  invalid.
- Its layered example is a DAG. Every DAG adjacency matrix is nilpotent even
  though the paper observes finite-horizon cascades, limiting spectral-radius
  interpretations.
- Detection without enforceable blocking is much weaker than the complete
  defense.

v0.2 response:

- Use a branching state machine with pre/post verification, containment,
  rollback, recovery and relapse.
- Separate verification verdict from governance actuation.
- Normalize contamination by actual call/turn horizon and reserve spectral
  heuristics for recurrent graphs.
- Rename the propagation summary to a registered finite-window
  secondary-adoption count with explicit attribution coverage.

## Faulty Agents

HTML: <https://arxiv.org/html/2408.00989v4>

Paper evidence:

- Reported robustness drops pool heterogeneous task scales and bundled
  framework/topology/role/prompt choices.
- Nominal and realized corruption dose can diverge substantially.
- Some corruptions improve outcomes; contamination is not a monotone proxy for
  task failure.
- Challenger and Inspector change warning, information and budget, rather than
  representing one interchangeable verifier.

v0.2 response:

- Record nominal dose, realized dose and manipulation verdict separately.
- Require paired clean/sham/corrupt conditions for formal intervention work.
- Keep clean utility, false rejection, collateral effects, outcome and cost
  distinct.
- Model verification-only, containment and rollback as different capabilities.

## HiddenBench

HTML: <https://arxiv.org/html/2505.11556>

Paper evidence:

- Agents initially possess different facts and often fail before transmission
  because they do not surface or request them.
- Reveal-All mechanically appends held facts and changes bandwidth; it is an
  oracle intervention, not just a communication reminder.
- The benchmark records pre/post votes but does not itself identify fact-level
  surfacing or integration.

v0.2 response:

- Add authorized information assignment, possession, required-to-surface,
  omission and unauthorized-exposure records.
- Report surfacing given possession, transport completion, exposure given
  delivery and integration given exposure with opportunity denominators.
- Require an equal-bandwidth control in a future HiddenBench adapter.

## TeamBench

HTML: <https://arxiv.org/html/2605.07073>

Paper evidence:

- Its 49.4% false-accept estimate is conditional on valid attestations; many
  role-mixing runs have no valid attestation, materially changing an
  end-to-end interpretation.
- The verifier cannot execute commands, while final outcomes come from a
  deterministic grader.
- Tool-call malformation, exhaustion and missing attestations are material
  system failures.
- Showing the deterministic verdict to a plausibility judge sharply increases
  agreement, demonstrating outcome leakage.

v0.2 response:

- Add typed attestation status, isolated grader runs, evidence validity, access
  policy, role-violation and tool-call records.
- Preserve missing, invalid, timeout and error states instead of coercing them
  to pass or fail.
- Keep verifier evidence and hidden-grader evidence on separate channels.
- Report coverage and verdict-conditional/system-level views separately.

## CooperBench

HTML: <https://arxiv.org/html/2601.13295>

Paper evidence:

- The 652 items are feature pairs from shared feature pools/base repositories,
  not 652 automatically independent issues.
- Two agents use independent workspaces and asynchronous messages; a message is
  included in the receiver's next prompt.
- Official outcome can include naive, union and learned-resolver merge stages,
  so post-resolver success can hide pre-resolver collaboration failure.
- The expectation/commitment/communication breakdown comes from human review
  of 50 failures rather than the full failed population.

v0.2 response:

- Add commitment/interface artifacts and evidence-backed fulfillment or breach.
- Preserve call, message, delivery, next-prompt and action identities.
- Define feature-pool/shared-base clusters and bidirectional heterogeneous
  assignment blocks.
- A future adapter must retain pre-resolver and final outcomes, merge policy,
  repository hashes, action caps and failure-audit provenance.

## Too Polite to Disagree

HTML: <https://arxiv.org/html/2604.02668>

Paper evidence:

- User sycophancy and horizontal peer conformity are different pressure
  mechanisms; adoption requires an initial disagreement and a later stance
  change, not mere mention.
- Belief-strengthening signals require their own controls and calibration.

v0.2 response:

- Distinguish environment/user/agent/controlled-injection origins and origin
  actor.
- Keep mention, stance alignment, endorsement and action dependence at
  different evidence levels.
- Defer belief-strengthening to a separate registered social-adoption study
  with user/peer/mixed/none and accuracy/random/dummy-prior controls.

## MultiAgentBench

HTML: <https://arxiv.org/html/2503.01935>

Paper evidence:

- The benchmark jointly varies graph, coordination protocol, environment and
  milestone behavior. A topology label is therefore normally a bundle.
- Tool use and environment progress are central to final performance.
- Raw total milestones and communication counts scale with opportunity.

v0.2 response:

- Separate the total effect of a natural protocol bundle from an
  exposure-standardized transition effect.
- Record opportunity counts, tool validity/execution and recognized outcome
  separately.
- Use task/repeat/assignment pairing, condition-independent sampling seeds,
  separately randomized run order, cluster-level resampling and a missing-pair
  hard failure.

## What the evidence does not authorize

The review does not authorize paid API calls, claim that the derived topology
suite is causal, validate a model judge, or make the absent external benchmark
runners executable. Those remain explicit gates in
[`experiment-readiness.md`](experiment-readiness.md).
