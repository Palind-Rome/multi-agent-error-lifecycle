#!/usr/bin/env python3
"""Generate the eight Stage-2 RQ1 fixture manifests.

Each fixture declares a concrete downstream task, six required facts and six
distractors, an interleaved source tool result, and a length-matched human
reference that preserves every required fact. The generator enforces the
structural invariants the runner validates at load time and reports a coarse
fact-type balance (numeric/unit, negation, conditional) per fixture.

This is a first-pass draft for review; the fact/fixture content is a research
design decision, not generated ground truth.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "configs" / "rq1-fixtures"


def _interleave(facts: list[tuple[str, str]], distractors: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for index, fact in enumerate(facts):
        parts.append(fact[1])
        if index < len(distractors):
            parts.append(distractors[index][1])
    return " ".join(parts)


def _reference(facts: list[tuple[str, str]]) -> str:
    # A compact, lossless human reference; each fact is compressed to its core.
    return " ".join(f"{fact[1]}" for fact in facts)


# Each fixture: (fixture_id, task_id, downstream task sentence, producer hint,
#                facts, distractors)
# `downstream_prompt_template` and `producer_system_prompt` are assembled below.
_FIXTURES = [
    {
        "fixture_id": "rq1-deployment-v1",
        "task_id": "write-deployment-config-v1",
        "task": "Write the deployment configuration to apply.",
        "keep": "region, retention period, backup policy, schema version, owning team, service port",
        "drop": "request IDs, log shards, display colors, retry counters, timezone notes, checksums",
        "facts": [
            ("fact-region", "Deployment region is eu-west-1."),
            ("fact-retention", "Retention period is 14 days."),
            ("fact-backup", "Never delete backups before validation."),
            ("fact-schema", "Required schema version is 7."),
            ("fact-owner", "Owning team is platform."),
            ("fact-port", "Service port is 8443."),
        ],
        "distractors": [
            ("distractor-request", "Synthetic request identifier is SYN-42."),
            ("distractor-shard", "Diagnostic log shard is alpha."),
            ("distractor-color", "Debug display color is amber."),
            ("distractor-retry", "Fixture retry counter is 2."),
            ("distractor-timezone", "Annotation timezone note is UTC."),
            ("distractor-checksum", "Checksum label is DEMO."),
        ],
    },
    {
        "fixture_id": "rq1-db-migration-v1",
        "task_id": "write-db-migration-runbook-v1",
        "task": "Write the database migration runbook to follow.",
        "keep": "target schema version, rollback threshold, lock timeout, backfill rule, snapshot rule, batch size",
        "drop": "migration ticket IDs, log level, dashboard color, sandbox name, notebook cell number, demo labels",
        "facts": [
            ("fact-schema", "Target schema version is 12."),
            ("fact-rollback", "Rollback if failure rate exceeds 5 percent."),
            ("fact-lock", "Lock timeout is 30 seconds."),
            ("fact-backfill", "Never backfill before the migration completes."),
            ("fact-snapshot", "Always snapshot before applying the migration."),
            ("fact-batch", "Batch size is 1000 rows."),
        ],
        "distractors": [
            ("distractor-ticket", "Migration ticket is MIG-991."),
            ("distractor-loglevel", "Migration log level is debug."),
            ("distractor-color", "Dashboard color is green."),
            ("distractor-sandbox", "Sandbox environment name is staging."),
            ("distractor-cell", "Notebook cell number is 14."),
            ("distractor-label", "Demo label is CANARY."),
        ],
    },
    {
        "fixture_id": "rq1-firewall-v1",
        "task_id": "write-firewall-rules-v1",
        "task": "Write the firewall rule set to apply.",
        "keep": "allowed ports, default policy, rate limit, TLS requirement, allowed CIDR, connection timeout",
        "drop": "rule comment IDs, console theme, debug verbosity, session counters, hostname, benchmark labels",
        "facts": [
            ("fact-ports", "Allow ports 443 and 22."),
            ("fact-default", "Default policy is deny all."),
            ("fact-rate", "Rate limit is 100 requests per second."),
            ("fact-tls", "Require TLS 1.2 or higher."),
            ("fact-cidr", "Allow only the 10.0.0.0/8 CIDR."),
            ("fact-timeout", "Connection timeout is 60 seconds."),
        ],
        "distractors": [
            ("distractor-comment", "Rule comment identifier is FW-77."),
            ("distractor-theme", "Console theme is dark."),
            ("distractor-verbosity", "Debug verbosity is high."),
            ("distractor-session", "Session counter is 8."),
            ("distractor-host", "Hostname is edge-03."),
            ("distractor-label", "Benchmark label is SMOKE."),
        ],
    },
    {
        "fixture_id": "rq1-secret-rotation-v1",
        "task_id": "write-secret-rotation-policy-v1",
        "task": "Write the secret rotation policy to enforce.",
        "keep": "rotation interval, minimum key length, revoke-on-compromise rule, encryption algorithm, key version, revocation window",
        "drop": "secret scan IDs, storage bucket name, UI theme, ticket priority, persona names, demo flags",
        "facts": [
            ("fact-interval", "Rotate secrets every 30 days."),
            ("fact-minlen", "Minimum key length is 256 bits."),
            ("fact-revoke", "Revoke immediately on compromise."),
            ("fact-algo", "Use AES-256-GCM for encryption."),
            ("fact-version", "Current key version is 4."),
            ("fact-window", "Revocation window is 15 minutes."),
        ],
        "distractors": [
            ("distractor-scan", "Secret scan identifier is SCAN-55."),
            ("distractor-bucket", "Storage bucket name is vault-east."),
            ("distractor-theme", "UI theme is light."),
            ("distractor-priority", "Ticket priority is P2."),
            ("distractor-persona", "Persona name is operator."),
            ("distractor-demo", "Demo flag is off."),
        ],
    },
    {
        "fixture_id": "rq1-etl-pipeline-v1",
        "task_id": "write-etl-pipeline-config-v1",
        "task": "Write the ETL pipeline configuration to run.",
        "keep": "source format, target schema, deduplication key, retry count, watermark, error threshold",
        "drop": "job run IDs, queue names, dashboard colors, notebook names, debug flags, environment aliases",
        "facts": [
            ("fact-source", "Source format is Avro."),
            ("fact-target", "Target schema is star."),
            ("fact-dedup", "Deduplicate on the user_id column."),
            ("fact-retry", "Retry up to 3 times."),
            ("fact-watermark", "Watermark is 5 minutes."),
            ("fact-error", "Fail if errors exceed 1 percent."),
        ],
        "distractors": [
            ("distractor-run", "Job run identifier is RUN-303."),
            ("distractor-queue", "Queue name is etl-low."),
            ("distractor-color", "Dashboard color is blue."),
            ("distractor-notebook", "Notebook name is explore."),
            ("distractor-debug", "Debug flag is on."),
            ("distractor-alias", "Environment alias is prod-sim."),
        ],
    },
    {
        "fixture_id": "rq1-api-contract-v1",
        "task_id": "write-api-contract-v1",
        "task": "Write the API contract to publish.",
        "keep": "rate limit, authentication method, response schema version, request timeout, retry policy, base path",
        "drop": "API key placeholders, log level, theme colors, tenant counters, environment names, demo endpoints",
        "facts": [
            ("fact-rate", "Rate limit is 500 requests per minute."),
            ("fact-auth", "Authentication uses OAuth 2.0."),
            ("fact-schema", "Response schema version is 3."),
            ("fact-timeout", "Request timeout is 10 seconds."),
            ("fact-retry", "Clients retry only idempotent calls."),
            ("fact-base", "Base path is /api/v2."),
        ],
        "distractors": [
            ("distractor-key", "API key placeholder is sk-test."),
            ("distractor-loglevel", "Log level is info."),
            ("distractor-color", "Theme color is teal."),
            ("distractor-tenant", "Tenant counter is 9."),
            ("distractor-env", "Environment name is sandbox."),
            ("distractor-endpoint", "Demo endpoint is /ping."),
        ],
    },
    {
        "fixture_id": "rq1-storage-lifecycle-v1",
        "task_id": "write-storage-lifecycle-policy-v1",
        "task": "Write the storage lifecycle policy to apply.",
        "keep": "hot storage days, archive tier, delete-after rule, encryption-at-rest, replication count, object size cap",
        "drop": "bucket labels, monitor colors, access log shards, tenant IDs, region nicknames, benchmark tags",
        "facts": [
            ("fact-hot", "Keep objects in hot storage for 30 days."),
            ("fact-archive", "Archive to the glacier tier after."),
            ("fact-delete", "Never delete before 90 days."),
            ("fact-encrypt", "Encrypt at rest with KMS."),
            ("fact-replica", "Replication count is 3."),
            ("fact-size", "Object size cap is 5 GiB."),
        ],
        "distractors": [
            ("distractor-bucket", "Bucket label is media-east."),
            ("distractor-color", "Monitor color is orange."),
            ("distractor-shard", "Access log shard is beta."),
            ("distractor-tenant", "Tenant identifier is T-12."),
            ("distractor-region", "Region nickname is east1."),
            ("distractor-tag", "Benchmark tag is COLD."),
        ],
    },
    {
        "fixture_id": "rq1-incident-runbook-v1",
        "task_id": "write-incident-runbook-v1",
        "task": "Write the incident response runbook to follow.",
        "keep": "paging threshold, rollback command, on-call rotation, SLA, severity mapping, escalation timeout",
        "drop": "incident IDs, chat channel names, theme colors, meeting counters, reporter names, demo labels",
        "facts": [
            ("fact-page", "Page after 3 failed health checks."),
            ("fact-rollback", "Rollback command is deploy prev."),
            ("fact-oncall", "On-call rotation is weekly."),
            ("fact-sla", "SLA is 99.9 percent."),
            ("fact-severity", "Severity 1 maps to page."),
            ("fact-escalate", "Escalate after 10 minutes."),
        ],
        "distractors": [
            ("distractor-incident", "Incident identifier is INC-44."),
            ("distractor-channel", "Chat channel is oncall-room."),
            ("distractor-color", "Theme color is red."),
            ("distractor-meeting", "Meeting counter is 2."),
            ("distractor-reporter", "Reporter name is ops-bot."),
            ("distractor-label", "Demo label is DRILL."),
        ],
    },
]

_NUMERIC_KEYS = {"rate", "timeout", "interval", "minlen", "version", "window",
                 "retry", "watermark", "error", "batch", "lock", "schema",
                 "hot", "replica", "size", "page", "sla", "escalate", "rollback",
                 "retention", "port"}
_NEGATION = ("never", "do not", "deny", "require", "revoke", "fail if", "only")


def _coarse_balance(facts: list[tuple[str, str]]) -> dict[str, int]:
    texts = [text.lower() for _, text in facts]
    numeric = sum(
        1 for key, text in facts
        if key in _NUMERIC_KEYS or any(char.isdigit() for char in text)
    )
    negated = sum(1 for text in texts if any(marker in text for marker in _NEGATION))
    return {"numeric_or_unit": numeric, "negated_or_conditional": negated, "total": len(facts)}


def build_manifest(spec: dict) -> dict:
    facts = spec["facts"]
    distractors = spec["distractors"]
    source_text = _interleave(facts, distractors)
    reference_text = _reference(facts)
    downstream_prompt_template = (
        f"{spec['task']} Use only the teammate summary below.\n\n{{transformed_text}}\n\n"
        "Answer concisely in one paragraph."
    )
    producer_system_prompt = (
        f"Summarize the tool result in at most 40 words for a teammate who will "
        f"complete this task: {spec['task']} Keep only: {spec['keep']}. Drop: "
        f"{spec['drop']}. Do not add information that is not present."
    )
    return {
        "fixture_id": spec["fixture_id"],
        "task_id": spec["task_id"],
        "source_text": source_text,
        "required_facts": [list(fact) for fact in facts],
        "distractors": [list(item) for item in distractors],
        "reference_text": reference_text,
        "downstream_prompt_template": downstream_prompt_template,
        "char_budget": 600,
        "token_budget": 80,
        "producer_system_prompt": producer_system_prompt,
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for spec in _FIXTURES:
        manifest = build_manifest(spec)
        source = manifest["source_text"]
        reference = manifest["reference_text"]
        assert len(source) > len(reference), spec["fixture_id"]
        assert len(source.split()) > len(reference.split()), spec["fixture_id"]
        assert len(reference) <= manifest["char_budget"], spec["fixture_id"]
        assert len(reference.split()) <= manifest["token_budget"], spec["fixture_id"]
        balance = _coarse_balance(spec["facts"])
        path = OUT_DIR / f"{spec['fixture_id']}.json"
        path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(
            f"{spec['fixture_id']}: facts={len(spec['facts'])} "
            f"numeric/unit={balance['numeric_or_unit']} "
            f"negated/conditional={balance['negated_or_conditional']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
