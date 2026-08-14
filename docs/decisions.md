# Decision log

## 2026-07-30

- Use a lifecycle decomposition instead of a single infected-agent score.
- Treat prompt exposure as distinct from message delivery.
- Treat textual reproduction as provisional adoption evidence, not definitive
  action-grounded adoption.
- Allow null final outcome because AgentCollabBench exposes diagnostic metrics,
  not a recognized task-success grader.
- Keep all primary conditional rates undefined when the denominator is zero.
- Support a provider router keyed by agent ID so heterogeneous-team experiments
  do not require one provider for all roles.
- Start with a standard-library-only implementation to make schema and mock
  validation independent of API and package availability.
- Defer paid provider adapters until model choices, budget and credentials are
  confirmed.

## 2026-07-30 — HTML-original review revision

- Treat the v0.1 144-run matrix as a paused derived design, not a paid pilot.
- Run untouched AgentCollabBench tasks first as an inference-ineligible
  instrumentation smoke.
- Distinguish controlled-injection receipt/possession from generation,
  surfacing, belief/action adoption, and false-belief contamination.
- Keep exact markers as surface proxies; only a pre-registered semantic or
  action-grounded label may become authoritative adoption.
- Require exact provider requests for exposure. Handoffs establish
  send/delivery/content survival but cannot establish prompt inclusion.
- Separate verification timing/completion/verdict/evidence from quarantine and
  rollback. Detection without actuation does not imply recovery.
- Add omission/private-information, commitment execution, attestation/grader,
  access/tool, and missingness records so non-falsehood collaboration failures
  are measurable.
- Rename the propagation summary to a finite-window secondary-adoption count;
  reserve it for registered windows with actual exposure-path attribution.
- Use task/repeat/assignment pairing keys, condition-independent sampling seeds,
  separately randomized run order, task/shared-pool clusters, and an n=1
  inference guard.
- Label rewired tasks `AgentCollabBench-derived`; native and derived results
  cannot share benchmark identity or reporting paths.

## 2026-08-14 — RQ1 scope freeze for engineering calibration

- Keep three paper-level questions—correct-information loss, false-information
  propagation and governance—but implement RQ1 only until its measurements are
  calibrated. Topology and heterogeneous model assignment are not current RQs.
- Study explicit natural-language summarization before runtime context
  compaction. Compaction is framework-specific and can mix summarization,
  truncation, overflow and vendor behavior.
- Use three RQ1 arms: verbatim raw forwarding, a length-matched fidelity
  reference, and an abstractive model summary. Keep the task, downstream model,
  recipient budget and scorer fixed.
- Treat the run/fixture as the experimental/cluster unit. Facts, turns, messages
  and agents within one run are nested observations, not independent samples.
- Register summary-stage fact retention and end-to-end required-fact success as
  the pilot co-primary measures. Keep missing requests, unobservable output and
  absent semantic annotations explicitly unknown.
- Any summary intervention layered onto an AgentCollabBench task is a derived
  suite, not an untouched native benchmark run. Native RTD remains an
  instrumentation bridge only.
- Use one homogeneous Qwen model for engineering calibration. Multi-model
  comparisons are deferred robustness checks.
- Implement a closed benchmark-plugin registry and one-assignment executor
  before claiming that a config can switch harnesses. A config may select only
  plugins whose execution and evidence contracts already exist and pass tests.
