# Experiment readiness v0.3

## Ready offline

- v0.2 records for origin/assignment/injection, possession, surfacing, messages,
  exact prompt exposure, authoritative integration/adoption, pre/post
  verification, evidence, containment/rollback/recovery/relapse, commitments,
  attestations, graders, model/tool calls and nullable usage.
- Cross-record and state-machine checks for time/lineage, prompt/edge identity,
  evidence, verification/recovery, commitment and outcome provenance.
- Deterministic fixtures where detection-only differs from rollback and
  injection receipt does not create false-belief contamination.
- Opportunity-aware true-information omission and false-artifact metrics,
  explicit transport coverage, truth-aware false support/reject, normalized
  turn-horizon contamination and registered-window propagation summary.
- Paired task/repeat/assignment seeds, separately randomized run order,
  missing-pair refusal, cluster-level paired bootstrap and n=1 inference guard.
- Multi-label annotation calibration utilities.
- AgentCollabBench full-result import that preserves exact requests and model
  call status. Handoffs without requests do not become exposure; exact markers
  remain surface annotations, not adoption.
- A real-provider, single-task AgentCollabBench engineering-smoke driver with
  positive hard caps, fixed Python injection seed, private atomic raw storage,
  and a durable provider-failure ledger. It always remains analysis-ineligible.
- A closed, immutable benchmark-plugin contract and one-assignment executor for
  trusted offline plugins. It pins plugin/raw versions, validates trace-manifest
  alignment and writes only to private ignored storage. Network-capable plugins
  are rejected at this stage.
- A deterministic RQ1 contract calibration with one fixture, six required facts,
  six distractors and the complete raw / length-matched reference / abstractive
  summary arm set. It checks source-to-summary-to-request-to-response lineage,
  stage-specific evidence spans, held-fixed fields and unknown denominators.
- A blocked 12-assignment untouched-native AgentCollabBench instrumentation
  preview. It may be expanded only with `--allow-unready` and is not executable.
- An explicitly paused, unvalidated derived topology-stress design.

## Completed RQ1 offline contract calibration (2026-08-14)

The offline entry point now builds and validates one complete three-arm block
without importing a provider or making an API call. Its deliberately constructed
summary preserves 3/6 required facts; the downstream output has five binary-valid
fact observations, one unknown observation and one correct reflection. These
numbers are regression-test expectations, not empirical findings.

The validator rejects incomplete arm sets, changed sources/fact manifests,
unmatched C1/T budgets, hidden arm-specific downstream instructions, producer
prompts that did not consume the declared source, evidence/hash mismatches and
attempts to relabel synthetic calibration traces as native or analysis-eligible.
Missing requests, provider/setup failures and incomplete traces remain unknown;
v1 does not yet persist those real-run failure branches.

## Completed AgentCollabBench RTD engineering smoke (2026-08-14)

The allowlisted native `TASK-DATAENG-RTD-060` path has now completed once with
`qwen/qwen3-30b-a3b-instruct-2507`, upstream commit `f016f60`, Python injection
seed `7`, temperature `0`, and no provider-side seed claim. The first attempt
failed closed after one HTTP-200 response ended with `finish_reason="length"`
at the old 1,024-token ceiling. There was no automatic retry. A fresh second
run used the reviewed 4,096-token per-call ceiling and completed all eight
expected calls:

- 5,286 input tokens and 8,419 output tokens;
- `$0.001879808850` locally accounted from the pinned price ceilings;
- 8 prompts, 8 model calls, 8 messages and 34 lifecycle events;
- 8/8 literal tracer reproductions and native RTD diagnostic score `1.0`;
- 8/8 observed handoff deliveries and literal survival opportunities;
- 4/4 applicable downstream-message prompt exposures observed; and
- 0/8 authoritative semantic-integration annotations, so semantic integration
  and adoption remain unknown rather than zero.

All persisted prompts, responses, the native result and the lifecycle trace
remain git-ignored under mode-`0700` private run directories with mode-`0600`
files. No credential or Authorization value was persisted. The run remains
`purpose="engineering_smoke"` and `analysis_eligible=false`: exact tracer
retention does not establish understanding, belief, action dependence, task
success, cross-task generalization or an intervention effect.

## Not ready for paid pilot/main or inferential runs

The only real-provider path is one explicitly selected RTD instrumentation
smoke. It does not implement the new summary treatment. The generic executor
currently accepts trusted offline plugins only, and there is no resumable/batch
`run-plan` executor. The plan CLI creates guarded assignments; it does not apply
model composition, provider credentials, budget caps or benchmark execution. In
particular:

- the blocked 12 native assignments have no registered executable plugin and
  still require a separately reviewed task allowlist, provider/model/API and
  experiment-level budget before execution;
- the derived 144-cell preview is not an official benchmark replication,
  construct-valid topology experiment or executable paid pilot;
- real governance verification/containment/rollback hooks are not implemented
  in AgentCollabBench;
- HiddenBench, TeamBench, CooperBench and SWE-bench adapters/runners are not yet
  implemented;
- MAST's public human traces have not yet been vendored and mapped to the local
  annotation records;
- the RQ1 three-arm contract is calibrated offline, but the real transformation
  runner, durable provider/setup-failure traces and blind human calibration are
  still absent; and
- repeated-run variance, power/budget gate and human-audit allocation remain
  unknown.

`configs/pilot.toml` now has `execution_status="blocked"`. It is an offline
preview only and requires `--allow-unready`; it does not authorize model/API
calls.

## Native expansion gate

The completed one-task run does not authorize a larger paid sample. Before any
additional AgentCollabBench task:

1. freeze the exact RQ1 fixture/fact manifest and the already selected
   transformation/downstream estimands;
2. fix the human-only or judge-assisted semantic-label protocol
   and record prompt hash, calibration dataset/version, votes/aggregation and
   blind fields;
3. decide whether provider sampling seeds are supported; never claim stochastic
   pairing when unsupported;
4. freeze task selection, repetitions, stopping rule and experiment-level
   token/call/time/cost cap rather than reusing a per-run smoke limit;
5. re-check the provider model ID and price ceilings immediately before the
   run, while retaining raw artifacts only under `outputs/private`;
6. repeat the completed manual receipt→surfacing→delivery→request-exposure
   audit after any adapter or upstream revision;
7. rerun the full offline test/adapter compatibility suite; and
8. explicitly authorize the resulting task list and budget.

Even after all 12 tasks, results remain instrumentation diagnostics with no
inferential CI and no recognized task outcome.

## Derived-suite unlock gate

The paused design requires:

- independent topology-realism and metric-artifact-isolation review;
- fixed external aggregation/output target and matched speaker/call/tool budget;
- opportunity/message/token/hop balance report;
- clean/sham/corrupt task variants and manipulation checks;
- implemented verification-only and verification+rollback runtime policies;
- source/role/order counterbalance;
- actual-prompt call alignment under repeated turns;
- registered attribution window and cluster analysis; and
- a variance/cost-based repeat decision.

Only after these checks may `review_status` and `execution_status` change. The
suite must retain the name `AgentCollabBench-derived`.

## External benchmark blockers

- **HiddenBench:** task release/profile mapping, equal-bandwidth control and
  same-run pre/post group scorer.
- **TeamBench:** workspace images, typed access policy enforcement,
  attestation/grader/evidence adapter and missingness sensitivity.
- **CooperBench:** released manifest reconciliation, OpenHands/container
  adapter, hidden-boundary audit, action/cost cap, merge/resolver pin and
  feature-pool/base-PR clusters.
- **SWE-bench Verified:** serialized Docker smoke, image/cache budget and
  deterministic scorer provenance.

## Local infrastructure snapshot

The earlier 2026-07-30 inspection reported x86_64, 28 CPUs, 15.33 GiB RAM,
815.88 GiB free workspace storage, Docker Engine 29.6.2 and a responding host
daemon. This can support serialized container smokes, but memory is close to the
published SWE-bench floor; keep container concurrency at one until measured.
Sandboxed checks may not see the host Docker socket.
