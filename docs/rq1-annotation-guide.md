# RQ1 required-fact annotation guide

This guide is for the RQ1 summary-loss calibration. It does not label false
belief, persuasion, governance or general answer quality.

## Unit and material shown to annotators

Annotate one pre-declared required fact at one stage of one run. The annotation
interface supplies the fact key and only the text needed for that stage:

- transformation stage: the complete summary/reference/raw output;
- downstream stage: the complete structured downstream answer.

Hide the arm, model/provider, benchmark score, other annotators' labels and all
later-stage text. Do not infer a missing piece from the source answer key or from
another arm.

## Observation status comes first

Choose an observation status before a semantic label:

| Observation status | Use when |
| --- | --- |
| `complete_valid` | The complete expected text is available and structurally valid |
| `missing` | No expected output was produced or retained |
| `invalid` | An output exists but cannot be parsed under the registered format |
| `provider_error` | The provider call failed or timed out before an observable output |
| `setup_error` | The task/environment did not reach the measurement opportunity |
| `trace_incomplete` | The output may have existed, but the audit trail is incomplete |

Only `complete_valid` can receive a binary success/loss label. The other rows
remain `unknown` or `unobservable`; they are reported as missingness and never
silently scored zero.

A valid, fully observed empty output is different from a missing output. It may
receive `omitted`/`absent` for every required fact.

## Transformation-output labels

| Label | Rule |
| --- | --- |
| `preserved_correctly` | Entity, relation, value/unit, polarity, scope and condition needed by the fact key are all correct |
| `omitted` | No corresponding information occurs anywhere in the complete output |
| `distorted_or_contradicted` | The output changes the entity, value, polarity, condition or relation |
| `partial` | A corresponding statement exists, but at least one pre-declared necessary slot is absent |
| `uncertain` | Complete text exists, but the rubric cannot reliably distinguish the semantic labels |
| `unknown` | No adjudicated semantic disposition is available |
| `unobservable` | The stage itself was not completely observed |

Every positive, distorted or partial judgment includes the smallest supporting
evidence span. `omitted` is an absence judgment over the complete output and
therefore need not invent a span.

## Downstream-output labels

| Label | Rule |
| --- | --- |
| `correctly_reflected` | The structured answer correctly applies or states the required fact in the scored answer field |
| `mentioned_only` | The fact is stated but is not reflected in the scored decision/calculation required by the answer key |
| `incorrectly_reflected` | The answer uses or states an incorrect value, polarity, entity, condition or relation |
| `absent` | The complete answer has no corresponding information |
| `uncertain` | Complete answer exists, but the rubric cannot reliably distinguish the semantic labels |
| `unknown` | No adjudicated semantic disposition is available |
| `unobservable` | The downstream answer was not completely observed |

Do not label latent understanding or belief. The downstream label concerns only
what is demonstrably reflected in the registered output.

## Annotation workflow

1. Confirm fixture ID, fact ID, stage and target event ID.
2. Determine observation status.
3. If `complete_valid`, apply the stage-specific semantic label and record the
   minimal evidence span where required.
4. Record confidence as optional supporting metadata; confidence never converts
   an uncertain row into a binary row.
5. Two annotators work independently. A third person adjudicates disagreements
   into one analysis record while retaining both source labels separately.

## Calibration pass gate

Before interpreting semantic rates:

- every planned fact opportunity must have an annotation or an explicit missing
  record;
- every binary annotation must point to a complete observed target event;
- transformation records must link source tool call, output event, handoff
  message and consuming prompt;
- the C0/C1/T block must share the same source hash and required-fact set;
- C1 and T must share the registered bandwidth/counting method; and
- disagreements and per-label confusion must be reported alongside Cohen's
  kappa.

Exact tracer matching may assist navigation but is not an authoritative
semantic annotation.
