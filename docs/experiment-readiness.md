# Experiment readiness

## Ready now

- Versioned lifecycle schema and cross-record validation.
- Full prompt hashing/redaction boundary.
- Deterministic instrumentation runner and cost/outcome metrics.
- Paired bootstrap utilities.
- AgentCollabBench full-result importer.
- AgentCollabBench per-agent provider routing and exact provider-request capture,
  tested against upstream commit `f016f60`.
- Matched task topology rewriter validated by the upstream task validator.
- A deterministic 12-task, minimum-four-agent RTD/CPR pilot selection.
- Factorial plan generation and offline unit/integration smoke tests.

## Proposed first paid pilot

`configs/pilot.toml` expands:

- 12 AgentCollabBench task seeds;
- 3 matched topologies;
- homogeneous and heterogeneous composition;
- no verification and evidence-required verification;
- one initial repeat.

This is 144 paired runs. The provisional budget estimator gives 1,728 backbone
calls and 432 judge calls. These are planning numbers, not a quote: actual calls
depend on task turn budgets, retries, judge policy and provider behavior. Run one
task across all 12 conditions first, inspect traces, then authorize the remaining
132 runs. Repeats should be chosen after observing variance, not silently added.

## Blocking decisions

No paid or real-model run should start until all are resolved:

1. homogeneous backbone and provider;
2. heterogeneous role-to-model assignment;
3. independent judge model or a decision to use human-only annotation;
4. API budget, per-run cap, timeout, retry and rate-limit policy;
5. temperature/sampling policy and whether providers support deterministic seeds;
6. acceptable storage policy for raw prompts and provider response IDs;
7. human audit sample size and annotator availability;
8. Docker/x86_64/storage capacity before SWE-bench;
9. outcome benchmark order after the diagnostic pilot.

## Local infrastructure snapshot

On 2026-07-30 the current machine reported x86_64, 28 CPUs, 15.33 GiB RAM,
815.88 GiB free workspace storage, Docker Engine 29.6.2 and a responding daemon
when checked outside the workspace sandbox. This is enough for a serialized
SWE-bench smoke run, but memory is close to the published 16 GB floor; keep
container concurrency at one until peak usage is measured. The repository's
environment checker may report Docker socket permission failure inside a sandbox
even when the host daemon is healthy.

## Known engineering caveats

- The per-agent AgentCollabBench router depends on the upstream synchronous call
  order and `_system_prompt_for_metric` hook. Re-run
  `scripts/smoke_agentcollab_adapter.py` after any upstream upgrade.
- AgentCollabBench does not expose recognized final task success. Imported
  outcomes remain null by design.
- Exact-marker reproduction is only provisional adoption evidence. Primary CPR
  analyses require a pre-registered semantic/action-grounded rubric.
- A topology rewrite changes root centrality and speaking order. Those are part
  of the intervention and are recorded, but interpretation must not call the
  effect “edges only.”
- Evidence-required verification needs a real evidence source/tool definition
  per benchmark; a generic “double-check” prompt is not sufficient.
