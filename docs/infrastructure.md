# Infrastructure map

This document separates what the repository can execute from what it can only
describe. It is intentionally narrower than the research roadmap.

## Short version

The repository has a shared evidence format and a working, guarded
AgentCollabBench engineering-smoke path. It does **not** yet have production
implementations for every benchmark or a paid batch runner.

Think of the layers as:

```text
study config
  -> immutable PlanItem assignments
  -> closed BenchmarkPlugin registry
  -> one-assignment executor
  -> benchmark-specific raw run
  -> benchmark-specific adapter
  -> shared TraceBundle
  -> structural validation
  -> single-run metrics
  -> later cross-run analysis
```

A config can select only a plugin that has already been implemented, registered
and tested. Changing a string cannot synthesize the task loader, container,
provider bridge, message protocol, raw parser or scorer of a new benchmark.

## Layer responsibilities

### 1. Design and planning

`design.py` expands a TOML matrix into immutable `PlanItem` rows. Planning
creates IDs, paired condition blocks, run order and declared provenance. It does
not call a model.

`execution_status="ready"` is necessary but not sufficient for execution. The
selected plugin, plugin version, raw schema version and requested factors must
also be recognized exactly. Unknown or paused combinations fail closed.

### 2. Benchmark plugin

Every benchmark has different execution semantics. A plugin resolves and pins a
task, validates supported factors and budgets, invokes its upstream runner, and
adapts the resulting raw evidence to a `TraceBundle`.

The registry is closed: there is no default plugin and no fallback from an
unknown benchmark name. CooperBench and MultiAgentBench are not executable just
because they are discussed in research documents.

### 3. Shared one-assignment executor

The shared executor checks that the assignment and plugin agree, calls exactly
one registered plugin, validates the returned trace, and persists only through
an explicitly provided artifact store. It is the first reusable harness layer;
it is not yet a resumable `run-plan` batch scheduler.

Provider credentials and transport remain outside the generic plugin interface.
The existing PaperBypass/AgentCollab smoke retains its stricter URL, model,
task/hash, upstream revision, call/token/time/cost and private-storage gates.

### 4. Raw evidence and adapter

Raw provider requests, replies, tool results and benchmark outputs are
benchmark-specific and may contain secrets or unpublished material. Real-run
raw evidence belongs only under git-ignored `outputs/private` storage.

An adapter converts benchmark evidence into the shared lifecycle records. An
adapter cannot infer semantic understanding merely from string appearance.

### 5. Trace schema and validator

`schema.py` defines typed records. `store.py` checks reference integrity,
ordering and state-machine invariants. A successful validation means the trace
is internally well formed; it does not mean the experimental design is causal,
the annotation is correct or the result generalizes.

### 6. Metrics and analysis

`metrics.py` computes a candidate superset of single-run measurements.
`RunMetrics` is not the paper's final metric table. The active RQ1 study selects
only fact retention, end-to-end fact success, first-loss stages, evidence
coverage and resource use.

Cross-run estimates must operate at the fixture/task cluster level and account
for missing cells. A `summarize` call on one trace is descriptive only.

## Current executable paths

| Path | Status | Scientific meaning |
| --- | --- | --- |
| Deterministic mock trace | Implemented | Schema/metric counterexamples only |
| AgentCollabBench RTD-060 real smoke | Implemented and guarded | Provider and literal-tracer instrumentation only |
| Generic one-assignment plugin contract | Implemented for trusted offline plugins | Reusable dispatch boundary; no batch or paid authorization |
| RQ1 three-arm offline calibration | Implemented and validated | Transformation/lineage and scoring contract; synthetic, not evidence |
| CooperBench | Not implemented | Later objective coding-outcome plugin |
| MultiAgentBench | Not implemented | Deferred ecological plugin |
| Paid RQ1 measurement pilot | Blocked by calibration gates | No paper result yet |

The existing plan files declare their intended plugin identity, but no real
network-capable plugin is registered in the stage-1 registry. In particular,
the blocked 12-task AgentCollab plan cannot be executed through the generic
executor; the separately guarded RTD-060 smoke remains the only real-provider
entry point.

## AgentCollab terminology

- RTD (Radioactive Tracer Durability) measures exact tagged correct-information
  survival across the communication path. It is not semantic fidelity.
- CPR (Consensus Pollution Rate) measures spread of a seeded false claim. It is
  an RQ2 mechanism and is not on the current real RQ1 execution allowlist.

The lifecycle stages—possession, surfacing, delivery, prompt exposure,
integration and downstream use—describe evidence inside one run. They are
general concepts, but a benchmark supplies only the stages its trace makes
identifiable.

## What must happen before a real RQ1 pilot

1. Freeze the fixture/fact manifest, transformation budgets and scorer; the
   deterministic three-arm contract and executor tests already pass.
2. Implement the real transformation runner and a durable provider/setup-failure
   trace path without weakening the current key, model, task and budget gates.
3. Complete a manually audited one-fixture, three-arm engineering calibration.
4. Demonstrate on that real trace that missing requests/annotations remain
   unknown and that every
   observed fact score links to source, transformation and final-answer evidence.
5. Recheck the fixed model, provider prices and experiment-level hard caps.
6. Only then mark a measurement plan analysis-eligible and execute additional
   paid runs.
