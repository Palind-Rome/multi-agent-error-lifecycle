# RQ1 — running multiple Qwen sizes (robustness)

The compact-arm result (compression is faithful 9/9, loss moved downstream 3/9)
was observed on a single model, `qwen/qwen3-30b-a3b-instruct-2507`. To check that
the finding is not an artifact of one model, run the same compact arm across a
few Qwen sizes on PaperBypass.

## What blocks "just change the model"

The guarded smoke driver pins two things for safety, both of which a model
change must touch deliberately:

1. **Model allowlist** — `APPROVED_PAPERBYPASS_MODELS` (a `frozenset`) in
   `src/mas_error_lifecycle/adapters/agentcollab_smoke.py`. A run is rejected
   unless its `provider.model` is on this list. It currently contains only the
   pinned 30b-a3b model.
2. **Cost ceilings** — `[limits]` in the local config, plus the price *floors*
   `MIN_INPUT_PRICE_USD_PER_MILLION` / `MIN_OUTPUT_PRICE_USD_PER_MILLION`. The
   configured per-million-token ceiling must be ≥ the floor, so the driver's
   cost estimate never under-shoots the real spend.

## How to add a size (reviewed, source-controlled)

1. Verify the model id exists on PaperBypass (e.g. list models at the gateway)
   and note its real per-million-token input/output price.
2. Add the id to the allowlist:
   ```python
   APPROVED_PAPERBYPASS_MODELS = frozenset({
       PAPERBYPASS_MODEL,
       "qwen/qwen3-8b-instruct-2507",      # example — verify before adding
   })
   ```
3. Give the run its own config (copy `configs/agentcollab-compact-batch.local.toml`)
   and set `model`, plus `max_input_cost_usd_per_million_tokens` and
   `max_output_cost_usd_per_million_tokens` to that model's real ceilings.

   **Cheaper size**: leave the ceilings at (or above) the 30b-a3b floors — the
   cost estimate over-shoots, which is the *safe* direction (it only makes the
   budget gate more conservative). **More expensive size**: the floors are
   minima, not maxima, so raise the configured ceilings above the floor; you do
   *not* need to change the floor constant unless the model is so expensive that
   the floor itself would under-price it.

## Running it

The batch CLIs now accept a repeatable `--override KEY=VALUE` so a size variant
does not require hand-editing a config file:

```bash
python -B scripts/run_agentcollab_compact.py \
  --agentcollab-repo /path/to/AgentCollabBench \
  --config configs/agentcollab-compact-batch.local.toml \
  --override model=qwen/qwen3-8b-instruct-2507 \
  --override max_input_cost_usd_per_million_tokens=0.01 \
  --override max_output_cost_usd_per_million_tokens=0.04 \
  --api-key-stdin
```

Valid override keys are the flat `provider.*` / `limits.*` names
(`model`, `base_url`, `temperature`, `send_seed`, `max_calls`,
`max_input_tokens`, `max_output_tokens`, `max_output_tokens_per_call`,
`max_wall_seconds`, `max_cost_usd`, and the two per-million cost ceilings).
Values are coerced to the correct type (`max_calls=90` → int, `send_seed=false`
→ bool); unknown keys or non-`KEY=VALUE` strings fail fast.

## What to compare

For each size, run the same approved RTD allowlist through the compact arm and
record the semantic annotation (`outputs/rtd-compact-annotations.json`-style),
not just the literal RTD score. The question to answer per size: does the
"faithful compression, loss downstream" pattern hold, or does a smaller model
lose information *inside* the compression step itself (a different failure mode)?
