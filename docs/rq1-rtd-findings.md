# RQ1 findings — AgentCollabBench RTD semantic layer

Human-adjudicated. The LLM-judge pass was reviewed by the user: all 9 tracer
labels confirmed (9/9 agreement, Cohen's kappa = 1.0, n = 9).

## Setup

Seven untouched AgentCollabBench RTD tasks (DATAENG/DEVOPS/SWE), one homogeneous
`qwen/qwen3-30b-a3b-instruct-2507`, temperature 0, `purpose=engineering_smoke`,
`analysis_eligible=false`. Nine tracer artifacts total (two tasks are
multi-constraint). The benchmark's own RTD diagnostic score is `1.0` for all
seven — every tracer ID string survives literally.

## Result

| First-loss stage | Tracers |
| --- | --- |
| `none` (semantic preserved end-to-end) | 7 / 9 |
| `relay` (distorted at an intermediate hop) | 2 / 9 |
| `surfacing` / `downstream` | 0 |

- Downstream status: 8 preserved, 1 unobservable (RTD-092 has no `__output__`
  message; it is diagnostic-only).

## The two relay distortions

1. `TASK-SWE-RTD-092` (`PERF-SEC-DASH-RT1`): source correct
   ("never exceed 50.00 ms" + "PII encrypted using AES-256"); mid-relay the
   hard bound relaxed to `p99 < 60ms` and AES-256 degraded to KMS; the final
   answer was never produced.
2. `TASK-DEVOPS-RTD-103` (`PERFSEC-DP89`): source correct ("max response time
   89.0 ms"); mid-relay relaxed to "mean 89.0 ms, P95 ≤ 92.0 ms, 85.0 ms
   target"; the downstream answer recovered the `>89.0 ms` threshold.

## Interpretation

- **Literal survival overstates semantic fidelity.** The benchmark reports 7/7
  perfect literal retention, but 2/7 tasks silently relaxed a strict numeric
  constraint during relay. This is the increment the semantic layer provides
  over the original RTD metric.
- **Loss concentrates at relay**, not surfacing or the final answer.
- **The recurring failure mode is numeric relaxation**: agents convert a hard
  bound ("never exceed X") into a statistical target ("mean X, P95 ≤ Y"). This
  is a candidate mechanistic claim for RQ1.

## Limits

- n = 9 tracers, one model, temperature 0; the perfect agreement is a small
  sample and should be re-checked on a larger set.
- RTD makes the tracer salient and explicitly "no rounding", so loss is rare
  (2/9). A summary-intervention derived suite is the likely next step to
  observe loss at a higher base rate.
