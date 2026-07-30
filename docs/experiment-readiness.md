# Experiment readiness v0.2

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
- A 12-assignment untouched-native AgentCollabBench instrumentation plan.
- An explicitly paused, unvalidated derived topology-stress design.

## Not ready for paid or inferential runs

There is no generic `run-plan` executor yet. The plan CLI creates guarded
assignments; it does not apply model composition, governance hooks, budget caps
or benchmark execution. In particular:

- the 12 native assignments still require provider/model/API and calibrated
  judge choices before execution;
- the derived 144-cell preview is not an official benchmark replication,
  construct-valid topology experiment or executable paid pilot;
- real governance verification/containment/rollback hooks are not implemented
  in AgentCollabBench;
- HiddenBench, TeamBench, CooperBench and SWE-bench adapters/runners are not yet
  implemented;
- MAST's public human traces have not yet been vendored and mapped to the local
  annotation records;
- repeated-run variance, power/budget gate and human-audit allocation remain
  unknown.

`execution_status="ready"` in `configs/pilot.toml` means the assignment file can
be expanded and inspected offline. It does not authorize model/API calls.

## Native smoke gate

Before the first real AgentCollabBench call:

1. select tested provider/model and save full role assignment;
2. decide whether provider sampling seeds are supported; never claim stochastic
   pairing when unsupported;
3. select the actual CPR judge or human-only route and record prompt hash,
   calibration dataset/version, votes/aggregation and blind fields;
4. set positive per-call, per-run and experiment token/cost/time limits in a
   git-ignored local config;
5. define raw-prompt/provider-response storage and redaction policy;
6. run one untouched RTD and one untouched CPR task;
7. manually verify receipt→surfacing, delivery→request exposure and surface
   proxy labels against raw traces;
8. run the full offline test/adapter compatibility suite; and
9. only then authorize the remaining native smoke tasks.

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
