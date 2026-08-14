# RQ1 real three-arm calibration runner

`src/mas_error_lifecycle/rq1_runner.py` builds the *real* (provider-backed)
trace that the offline contract in `rq1.py` only calibrates. It runs one
fixture in three arms and one downstream answer call per arm:

| Arm | Transformed text | Producer |
| --- | --- | --- |
| C0 `raw_passthrough` | verbatim tool result | none (identity) |
| C1 `length_matched_reference` | pre-registered human/rule reference | none (human reference) |
| T `abstractive_summary` | model summary under the shared budget | real model call |

Every bundle is `api_called=True`, `purpose="engineering_smoke"`,
`analysis_eligible=False`, and `suite_kind="derived"`. No semantic fact
annotations are produced — those are layered on by human/judge annotators.

## Two documented compromises (calibration-only)

1. **Literal presence proxy.** `message.artifact_ids` records a required fact
   only when its registered ground-truth text appears *verbatim* in the
   transformed text. This mirrors the RTD adapter's literal tracer-survival
   proxy. Semantic preservation (`preserved_correctly` / `correctly_reflected`)
   remains unknown until the annotation pass. Do not read a low literal count
   as measured information loss.
2. **Token-count domain.** The v0.2 validator defines `target_token_count` as
   the whitespace-split proxy (`rq1_token_count`) and requires the producer
   model call's `output_tokens` to equal it. The provider reports model tokens,
   so the producer call stores the whitespace count in `output_tokens` and the
   real provider completion tokens in `metadata["provider_completion_tokens"]`.
   Input tokens and cost are stored verbatim. This is a known v0.2 limitation,
   not a billing or usage claim.

## Run Stage 1 (3-run engineering calibration)

```bash
cp configs/rq1-calibration.example.toml configs/rq1-calibration.local.toml
# edit the local copy if the budget/model changes; never put a key there

PYTHONPATH=src python scripts/run_rq1_real_calibration.py \
  --fixture configs/rq1-fixture.example.json \
  --config configs/rq1-calibration.local.toml \
  --run-id rq1-calib-001 --api-key-stdin
# enter the key on one line of stdin (non-TTY), or omit --api-key-stdin for
# hidden interactive input
```

The driver makes exactly four calls (one summary + three downstream), writes
three `lifecycle-trace-{c0,c1,t}.jsonl` files plus a durable
`rq1-calibration-ledger.json` under `outputs/private/<run-id>`, all mode `0600`
and git-ignored. The key is never written to any file or the environment.

## Remaining design decisions (before Stage 2)

- Freeze the fixture/fact manifest (this example is one draft fixture; the
  pilot targets eight).
- Freeze the annotation protocol (human-only vs judge-assisted, blind fields,
  prompt hash, calibration version) and run the two-annotator + adjudicator
  pass with Cohen's kappa.
- Freeze sample size (72-run pilot is provisional), stopping rule, and
  experiment-level call/token/cost caps.
- Re-check provider model ID and price ceilings immediately before a paid run.
