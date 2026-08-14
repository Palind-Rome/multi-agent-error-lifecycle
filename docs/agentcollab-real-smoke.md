# Guarded AgentCollabBench real smoke

This driver is a deliberately narrow engineering tool. Its executable allowlist
contains exactly one tracked, untouched AgentCollabBench RTD JSON task and it
always records:

- `purpose="engineering_smoke"`;
- `analysis_eligible=false`;
- one explicit task file, matching explicit task ID and metric;
- the pinned clean upstream commit `f016f60`;
- Python injection seed (default `7`); and
- positive call, input-token, output-token, wall-time, and cost caps.

It is not a generic `run-plan` executor and cannot run a task list. The only
approved RQ1 route is `TASK-DATAENG-RTD-060` with metric `rtd`, two agents, and
raw-file SHA-256
`9bb822c2bc1555104fa9ae63c5ee050a1e1b35603396dddc92634e8a609ed92b`.
CPR compatibility code remains available for a
future allowlist, but the executable CPR allowlist is currently empty.

No API key belongs in TOML, CLI arguments, environment variables, logs, or
files. By default the driver uses `getpass.getpass` for hidden interactive
input. For a non-TTY caller, `--api-key-stdin` reads one line from standard
input. A process launched with `PAPERBYPASS_API_KEY` present fails closed:
removing an inherited variable in Python cannot remove its original bytes from
Linux `/proc/<pid>/environ`.

## Local configuration

Copy the tracked example to the git-ignored filename:

```bash
cp configs/agentcollab-smoke.example.toml \
  configs/agentcollab-smoke.local.toml
```

The example pins:

- base URL `https://aigateway.paperbypass.com/api/v1`;
- model `qwen/qwen3-30b-a3b-instruct-2507`;
- temperature `0`;
- eight calls, at most `4,096` output tokens per call and `32,768` in total;
- configured price ceilings of `$0.04815/M` input and `$0.19305/M` output.

The earlier `1,024`-token per-call ceiling produced a truncated
`finish_reason="length"` response in the first engineering attempt, which the
driver correctly rejected. With the tracked ceilings of `200,000` input tokens
and `32,768` output tokens, the configured worst case is
`$0.00963 + $0.0063258624 = $0.0159558624`, still below the `$0.02` hard cap.
This is a safety-bound calculation, not an expected bill or a study result.

The credential-bearing driver accepts only the exact base URL above (one
trailing slash is normalized). Alternate hosts, ports, paths, schemes,
userinfo, query strings, and fragments fail before the key is read into an HTTP
request. HTTP redirects are disabled at the urllib handler and every `3xx`
response is persisted as a provider failure; Authorization is never replayed to
a redirect target.

Re-check prices before a real call. The runtime cost gate uses configured token
price ceilings, or the provider-reported cost when present, whichever is larger.
A failed call with unknown usage is conservatively charged its entire pre-call
reservation in the ledger. These are engineering safeguards, not billing truth;
the provider account remains authoritative.

The PaperBypass public documentation does not guarantee `seed` passthrough.
Therefore Python-side AgentCollabBench injection randomness is always seeded,
while `provider.send_seed=false` is the safe example setting. After an independent
capability check, set it to `true` or pass `--send-seed`; the same integer is then
included in each provider request and recorded in the ledger.

## One-task invocation

Run one explicit task and enter the key only at the hidden prompt. The selected
native RTD task below declares exactly 8 expected calls, matching the example's
`max_calls=8` ceiling:

```bash
PYTHONPATH=src python scripts/run_agentcollab_real_smoke.py \
  --agentcollab-repo ../assets/AgentCollabBench \
  --task-file ../assets/AgentCollabBench/tasks/TASK-DATAENG-RTD-060.json \
  --task-id TASK-DATAENG-RTD-060 \
  --metric rtd \
  --seed 7 \
  --config configs/agentcollab-smoke.local.toml
```

For non-TTY automation, a trusted secret source may write exactly one line to
the driver's stdin; the key must still be absent from both environments and
argument lists:

```bash
trusted-secret-command | PYTHONPATH=src \
  python scripts/run_agentcollab_real_smoke.py \
  --api-key-stdin \
  --agentcollab-repo ../assets/AgentCollabBench \
  --task-file ../assets/AgentCollabBench/tasks/TASK-DATAENG-RTD-060.json \
  --task-id TASK-DATAENG-RTD-060 --metric rtd --seed 7 \
  --config configs/agentcollab-smoke.local.toml
```

Every hard limit may instead be supplied through the corresponding CLI option.
Base URL and model must still come from the git-ignored TOML or explicit CLI
arguments. Zero, missing, non-finite, or negative caps are rejected before a
provider call.

## Private artifacts and failure behavior

The command has no general `--out` option. It creates one fresh directory under:

```text
outputs/private/<run-id>/
├── failure-ledger.json
├── lifecycle-trace.jsonl
└── raw/
    ├── agentcollab-result.json
    ├── openai-compatible-00001.request.json
    └── openai-compatible-00001.response.json
```

`outputs/private` and `configs/*.local.toml` are git-ignored. Files are mode
`0600`, directories are mode `0700`, and each file is written through a flushed,
fsynced temporary file followed by an atomic replace. Because the lifecycle
trace itself contains exact prompts and intermediate model text, it also stays
inside this private directory.

Before network I/O, the raw request (without authorization headers) and a
`status="started"` ledger entry are durable. HTTP failures, transport failures,
malformed/missing usage, and post-response budget violations update the ledger
before the exception escapes. There are no automatic retries. A provider failure
therefore cannot silently disappear or create an unaccounted second call.

The initial Python environment must not contain the key. Every git subprocess
receives a separately sanitized environment with all inherited `GIT_*`
overrides removed, disables replacement objects, and is invoked with
`core.fsmonitor=false` and `core.hooksPath=/dev/null`. The reported Git
top-level must equal the requested checkout and its object format must be
`sha1`. One full-checkout
`git status --porcelain --ignored --untracked-files=all` gate rejects every
modified, untracked, or ignored item anywhere in the upstream repository. This
includes package caches and root-level shadow candidates such as `logging.pyc`
or `sitecustomize.pyc`. Use a completely clean checkout. The driver sets
`sys.dont_write_bytecode` before verifying or importing upstream code.

Status/index metadata is not accepted as proof that tracked bytes are clean.
The driver reads every recursive blob entry from the pinned HEAD tree, hashes
ordinary worktree file bytes and symlink targets with Git's raw SHA-1 blob
encoding, verifies executable modes and entry types, and compares each result
to the HEAD object ID. Missing files, submodules, special files, index
`assume-unchanged`/`skip-worktree` masking, and clean-filter masking all fail
before upstream import.

The input gate uses a tokenizer-independent, conservative UTF-8 byte bound plus
message-envelope overhead before each request, then reconciles exact provider
usage. Output `max_tokens` is reduced to the remaining output and cost allowance.
If the provider reports usage beyond a reservation, or elapsed wall time reaches
the cap, the run terminates and remains an engineering failure.
The default real HTTP transport runs in a dedicated multiprocessing worker. The
parent enforces one absolute per-call deadline across worker startup, DNS,
connect, TLS, response headers, and body transfer, then terminates/kills and
reaps an overdue child. The key reaches that worker only through in-memory
process arguments/IPC, never its environment or command line. Response bodies
additionally have a 4 MiB ceiling. Successful chat responses must name the exact
configured model, contain non-empty text, report `finish_reason="stop"`, and
include integer usage.

## Untouched-task and interpretation gates

The driver refuses:

- a checkout other than the tested upstream commit;
- any modified, untracked, or ignored file anywhere in the upstream checkout;
- an untracked or modified task JSON;
- a task outside upstream `tasks/`;
- derived/rewired tasks or `_runner_trace_overrides`;
- a task-ID or metric mismatch; and
- a task whose expected calls exceed `max_calls`.

Completion also requires `calls_started == calls_completed == expected_calls`
and the same number of upstream `provider_requests`; the approved task must end
with exactly eight reconciled calls.

After execution it hashes the returned scenario against the original JSON object
and fails if upstream mutated it. A successful run is converted with the existing
AgentCollabBench lifecycle adapter. RTD/CPR scores remain diagnostic-only: no
task success is inferred, exact textual reproduction is not authoritative
adoption, and no smoke output may enter inferential analysis.
