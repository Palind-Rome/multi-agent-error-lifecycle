# Trace schema v0.1.0

Each JSONL file contains exactly one run in this order:

1. one `run_manifest`;
2. one or more `artifact` records;
3. prompt records referenced by exposure events;
4. ordered `event` records;
5. one `outcome`.

## Manifest

The manifest fixes task, condition, seed, per-agent provider/model assignment and
directed topology. `condition_id` must be derived before execution. Runtime code
must not silently mutate the condition after seeing outputs.

## Artifact

An artifact has a stable ID, source agent, creation step, truth status and
lineage. `truth_status=unknown` is valid: uncertainty must not be coerced into
false. Raw content may be encrypted or replaced with a salted digest when a task
contains secrets, but the redaction policy belongs in `metadata`.

## Event semantics

| Event | Required interpretation |
|---|---|
| `artifact_generated` | The source first emits or receives a controlled injection. |
| `message_sent` | A sender attempts communication. `details.delivered` records transport success and `artifact_present_in_message` records artifact survival. |
| `artifact_exposed` | The artifact is demonstrated to be in the receiver's actual prompt/context. |
| `artifact_adopted` | The receiver repeats, endorses, or acts on it; evidence type is recorded. |
| `artifact_rejected` | The receiver declines it. |
| `artifact_uncertain` | The receiver explicitly defers judgment. |
| `verification_started` | A check is attempted; method and evidence policy are recorded. |
| `verification_completed` | Verdict is `supported`, `refuted`, `inconclusive`, or `error`. |
| `artifact_corrected` | A replacement artifact is produced. |
| `artifact_recovered` | The agent rolls back or stops relying on the error. |
| `action_taken` | A downstream tool/code/decision action depends on artifacts. |
| `run_finalized` | Lifecycle recording has ended. |

`message_sent`, `artifact_exposed`, and `artifact_adopted` are deliberately
different. A handoff can be delivered while omitting the artifact; an artifact
can be present in context but ignored; a model can repeat it while not acting on
it. Every adoption event therefore carries an `adoption_evidence` field.

## Prompt

Every exposure event references a prompt record containing role/content messages
or an explicitly redacted representation. Unredacted records must match their
canonical SHA-256 digest. A reconstructed upstream handoff is marked partial and
must not be described as the full provider request.

## Outcome

`success` and `score` may be `null` when the source benchmark does not provide a
real task outcome. Diagnostic scores such as RTD or CPR belong in
`outcome.details`, not in the task-score fields. Unknown latency or cost also
remain null rather than being reported as zero.

## IDs and timestamps

- IDs are immutable within a run.
- `step` is the canonical logical clock and must be non-decreasing.
- wall timestamps are ISO-8601 audit metadata; analyses should use `step` unless
  cross-process clocks are synchronized.
- parent event IDs and parent artifact IDs form explicit provenance graphs.

## Privacy

Never write API keys, authorization headers, cookies or unredacted secrets.
Provider response IDs are allowed; raw provider payloads are opt-in. For CLC
tasks, private tracer values should be salted/hashed in any public artifact.
