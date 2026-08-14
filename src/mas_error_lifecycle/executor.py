"""Fail-closed execution of exactly one immutable benchmark assignment."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from .design import EXECUTABLE_REVIEW_STATUSES, PlanItem
from .plugins import (
    BenchmarkPluginRegistry,
    PluginExecutionContext,
    RawBenchmarkRun,
)
from .store import TraceBundle


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_RESULT_FILENAME = "execution-result.json"
_RAW_FILENAME = "raw-result.json"
_TRACE_FILENAME = "lifecycle-trace.jsonl"
_CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"(?i)(?:^|\s)(?:bearer|basic)\s+[^\s,;]+"),
    re.compile(r"(?i)(?:api[_ -]?key|authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(?:^|\s)sk-[a-z0-9_-]{16,}"),
)


@dataclass(frozen=True, slots=True)
class AssignmentExecutionResult:
    """Structured success or durable, redacted failure for one assignment."""

    status: str
    assignment_id: str | None
    run_id: str | None
    task_id: str | None
    benchmark_plugin: str | None
    stage: str
    started_at: str
    finished_at: str
    output_directory: Path
    result_path: Path
    raw_path: Path | None = None
    trace_path: Path | None = None
    raw_schema_version: str | None = None
    raw_sha256: str | None = None
    trace_sha256: str | None = None
    error_type: str | None = None
    private_layout_clean: bool = True


class AssignmentExecutionError(RuntimeError):
    """Safe public error carrying the path to a durable failure result."""

    def __init__(self, result: AssignmentExecutionResult):
        self.result = result
        super().__init__(
            f"assignment execution failed during {result.stage} "
            f"({result.error_type}); see {result.result_path}"
        )


class PrivateLayoutViolation(PermissionError):
    """Raised when a plugin changes executor-owned private artifacts."""


def execute_one_assignment(
    assignment: PlanItem,
    *,
    registry: BenchmarkPluginRegistry,
    repository_root: str | Path,
    output_directory: str | Path,
) -> AssignmentExecutionResult:
    """Run one explicit plugin assignment and atomically persist its evidence.

    ``output_directory`` must be one direct, new child of the repository's
    ignored, private ``outputs/private`` directory.  This first-stage executor
    has no retry, resume, overwrite, dynamic import, or multi-assignment
    behavior.  Plugin exception messages are never written to its public
    failure record.
    """

    if not isinstance(assignment, PlanItem):
        raise TypeError("assignment must be a PlanItem")
    if not isinstance(registry, BenchmarkPluginRegistry):
        raise TypeError("registry must be a BenchmarkPluginRegistry")

    private_directory = _resolve_private_output_directory(
        repository_root=Path(repository_root),
        output_directory=Path(output_directory),
    )
    store = _AtomicExecutionStore.create(private_directory)
    started_at = _utc_now()
    context = PluginExecutionContext(started_at=started_at)
    identity = _safe_identity(assignment)
    stage = "assignment_validation"
    raw_path: Path | None = None
    trace_path: Path | None = None
    raw_schema_version: str | None = None
    raw_sha256: str | None = None
    trace_sha256: str | None = None
    running_result_sha256 = store.write_result(
        _result_record(
            status="running",
            identity=identity,
            stage=stage,
            started_at=started_at,
            finished_at=None,
        )
    )

    try:
        _validate_assignment(assignment)

        stage = "plugin_resolution"
        plugin = registry.resolve(assignment.benchmark_plugin)
        if assignment.plan_version not in plugin.supported_plan_versions:
            raise ValueError(
                f"plugin {plugin.key!r} does not support plan version "
                f"{assignment.plan_version!r}"
            )
        if assignment.plugin_version != plugin.version:
            raise ValueError(
                f"assignment pins plugin version {assignment.plugin_version!r}, "
                f"but registry contains {plugin.version!r}"
            )
        if assignment.raw_schema_version != plugin.raw_schema_version:
            raise ValueError(
                "assignment raw_schema_version does not match the registered "
                "plugin contract"
            )
        unsupported_bindings = set(assignment.factor_bindings.values()).difference(
            plugin.supported_factor_bindings
        )
        if unsupported_bindings:
            raise ValueError(
                f"plugin {plugin.key!r} does not support factor binding(s): "
                + ", ".join(sorted(unsupported_bindings))
            )

        stage = "plugin_validation"
        plugin.validate_assignment(assignment)

        stage = "plugin_run"
        native_raw = plugin.run(assignment, context)
        store.assert_layout({_RESULT_FILENAME: running_result_sha256})

        stage = "raw_validation"
        raw_run, raw_bytes = _canonical_raw_run(native_raw)
        raw_schema_version = raw_run.schema_version
        if raw_schema_version != assignment.raw_schema_version:
            raise ValueError(
                "plugin returned a raw result with an unpinned schema version"
            )

        stage = "raw_persistence"
        raw_path = store.write_once(_RAW_FILENAME, raw_bytes)
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

        stage = "adaptation"
        bundle = plugin.adapt(raw_run, assignment, context)
        store.assert_layout(
            {
                _RESULT_FILENAME: running_result_sha256,
                _RAW_FILENAME: raw_sha256,
            }
        )
        if not isinstance(bundle, TraceBundle):
            raise TypeError("benchmark plugin adapt() must return a TraceBundle")
        _validate_trace_alignment(
            bundle,
            assignment,
            expected_benchmark=plugin.trace_benchmark,
        )

        stage = "trace_validation"
        bundle.validate()
        trace_bytes = _trace_bytes(bundle)

        stage = "trace_persistence"
        trace_path = store.write_once(_TRACE_FILENAME, trace_bytes)
        trace_sha256 = hashlib.sha256(trace_bytes).hexdigest()
        store.assert_layout(
            {
                _RESULT_FILENAME: running_result_sha256,
                _RAW_FILENAME: raw_sha256,
                _TRACE_FILENAME: trace_sha256,
            }
        )

        stage = "completed"
        finished_at = _utc_now()
        result = AssignmentExecutionResult(
            status="completed",
            assignment_id=identity["assignment_id"],
            run_id=identity["run_id"],
            task_id=identity["task_id"],
            benchmark_plugin=identity["benchmark_plugin"],
            stage=stage,
            started_at=started_at,
            finished_at=finished_at,
            output_directory=store.directory,
            result_path=store.result_path,
            raw_path=raw_path,
            trace_path=trace_path,
            raw_schema_version=raw_schema_version,
            raw_sha256=raw_sha256,
            trace_sha256=trace_sha256,
            private_layout_clean=True,
        )
        store.write_result(_result_from_execution(result))
        return result
    except Exception as exc:
        expected_layout = {_RESULT_FILENAME: running_result_sha256}
        if raw_path is not None:
            expected_layout[_RAW_FILENAME] = raw_sha256
        if trace_path is not None:
            expected_layout[_TRACE_FILENAME] = trace_sha256
        try:
            store.assert_layout(expected_layout)
            private_layout_clean = True
            error_type = type(exc).__name__
        except PrivateLayoutViolation:
            private_layout_clean = False
            stage = "security_layout"
            error_type = "PrivateLayoutViolation"
        finished_at = _utc_now()
        result = AssignmentExecutionResult(
            status="failed",
            assignment_id=identity["assignment_id"],
            run_id=identity["run_id"],
            task_id=identity["task_id"],
            benchmark_plugin=identity["benchmark_plugin"],
            stage=stage,
            started_at=started_at,
            finished_at=finished_at,
            output_directory=store.directory,
            result_path=store.result_path,
            raw_path=raw_path,
            trace_path=trace_path,
            raw_schema_version=raw_schema_version,
            raw_sha256=raw_sha256,
            trace_sha256=trace_sha256,
            error_type=error_type,
            private_layout_clean=private_layout_clean,
        )
        store.write_result(_result_from_execution(result))
        raise AssignmentExecutionError(result) from None


def _validate_assignment(assignment: PlanItem) -> None:
    for field_name in (
        "plan_version",
        "benchmark_plugin",
        "plugin_version",
        "raw_schema_version",
        "experiment",
        "purpose",
        "protocol_kind",
        "suite_kind",
        "execution_status",
        "review_status",
        "task_id",
        "condition_id",
        "pair_id",
        "cluster_id",
        "assignment_id",
        "run_id",
    ):
        value = getattr(assignment, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"assignment.{field_name} must be a non-empty string")
    if assignment.execution_status != "ready":
        raise ValueError("only execution_status='ready' assignments may run")
    if assignment.review_status not in EXECUTABLE_REVIEW_STATUSES:
        raise ValueError("assignment.review_status is not executable")
    if not isinstance(assignment.analysis_eligible, bool):
        raise ValueError("assignment.analysis_eligible must be boolean")
    if assignment.analysis_eligible and not _is_sha256(assignment.preregistration_hash):
        raise ValueError(
            "analysis-eligible assignment requires a SHA-256 preregistration_hash"
        )
    for field_name in ("preregistration_hash", "native_task_hash"):
        value = getattr(assignment, field_name)
        if value is not None and not _is_sha256(value):
            raise ValueError(f"assignment.{field_name} must be a SHA-256 or null")
    for field_name in ("repeat", "seed", "run_order"):
        value = getattr(assignment, field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                f"assignment.{field_name} must be a non-negative integer"
            )
    if assignment.seed_supported is not None and not isinstance(
        assignment.seed_supported, bool
    ):
        raise ValueError("assignment.seed_supported must be boolean or null")
    for field_name in ("estimated_backbone_calls", "estimated_judge_calls"):
        value = getattr(assignment, field_name)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise ValueError(
                f"assignment.{field_name} must be a non-negative integer or null"
            )
    if not isinstance(assignment.factors, dict) or not assignment.factors:
        raise ValueError("assignment.factors must be a non-empty object")
    if not isinstance(assignment.factor_bindings, dict):
        raise ValueError("assignment.factor_bindings must be an object")
    if set(assignment.factors) != set(assignment.factor_bindings):
        raise ValueError("factor_bindings keys must exactly match factors keys")
    if any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, str)
        or not value.strip()
        for key, value in assignment.factor_bindings.items()
    ):
        raise ValueError("factor_bindings must map non-empty strings to strings")


def _validate_trace_alignment(
    bundle: TraceBundle,
    assignment: PlanItem,
    *,
    expected_benchmark: str,
) -> None:
    manifest = bundle.manifest
    if manifest.benchmark != expected_benchmark:
        raise ValueError(
            "adapted trace manifest.benchmark does not match plugin identity"
        )
    expected = {
        "run_id": assignment.run_id,
        "task_id": assignment.task_id,
        "condition_id": assignment.condition_id,
        "seed": assignment.seed,
        "protocol_kind": assignment.protocol_kind,
        "suite_kind": assignment.suite_kind,
        "purpose": assignment.purpose,
        "pair_id": assignment.pair_id,
        "cluster_id": assignment.cluster_id,
        "assignment_id": assignment.assignment_id,
        "analysis_eligible": assignment.analysis_eligible,
        "execution_status": assignment.execution_status,
        "review_status": assignment.review_status,
    }
    for field_name, expected_value in expected.items():
        if getattr(manifest, field_name) != expected_value:
            raise ValueError(
                f"adapted trace manifest.{field_name} does not match assignment"
            )
    for field_name in ("preregistration_hash", "native_task_hash"):
        expected_value = getattr(assignment, field_name)
        if expected_value is not None and getattr(manifest, field_name) != expected_value:
            raise ValueError(
                f"adapted trace manifest.{field_name} does not match assignment"
            )


def _canonical_raw_run(value: Any) -> tuple[RawBenchmarkRun, bytes]:
    if not isinstance(value, RawBenchmarkRun):
        raise TypeError("benchmark plugin run() must return RawBenchmarkRun")
    try:
        encoded = json.dumps(
            dict(value.payload),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("raw benchmark payload must be strict JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("raw benchmark payload must encode one JSON object")
    _reject_sensitive_credential_fields(decoded)
    return RawBenchmarkRun(decoded, value.schema_version), encoded


def _reject_sensitive_credential_fields(value: Any) -> None:
    forbidden = {
        "authorization",
        "proxy-authorization",
        "api-key",
        "api_key",
        "x-api-key",
        "x-auth-token",
        "access_token",
        "refresh_token",
        "bearer_token",
        "client_secret",
        "cookie",
        "set-cookie",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower() in forbidden:
                raise ValueError(
                    "raw benchmark payload contains a forbidden credential field"
                )
            _reject_sensitive_credential_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_credential_fields(item)
    elif isinstance(value, str) and any(
        pattern.search(value) for pattern in _CREDENTIAL_VALUE_PATTERNS
    ):
        raise ValueError(
            "benchmark payload contains a credential-shaped string value"
        )


def _trace_bytes(bundle: TraceBundle) -> bytes:
    rows = []
    for record in bundle.records():
        value = record.to_dict()
        _reject_sensitive_credential_fields(value)
        rows.append(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
            )
        )
    return ("\n".join(rows) + "\n").encode("utf-8")


def _safe_identity(assignment: PlanItem) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for field_name in (
        "assignment_id",
        "run_id",
        "task_id",
        "benchmark_plugin",
    ):
        value = getattr(assignment, field_name)
        result[field_name] = value if isinstance(value, str) else None
    return result


def _result_record(
    *,
    status: str,
    identity: Mapping[str, str | None],
    stage: str,
    started_at: str,
    finished_at: str | None,
) -> dict[str, Any]:
    return {
        "status": status,
        **identity,
        "stage": stage,
        "started_at": started_at,
        "finished_at": finished_at,
        "raw_path": None,
        "trace_path": None,
        "raw_schema_version": None,
        "raw_sha256": None,
        "trace_sha256": None,
        "error_type": None,
        "private_layout_clean": None,
    }


def _result_from_execution(result: AssignmentExecutionResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "assignment_id": result.assignment_id,
        "run_id": result.run_id,
        "task_id": result.task_id,
        "benchmark_plugin": result.benchmark_plugin,
        "stage": result.stage,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "raw_path": result.raw_path.name if result.raw_path is not None else None,
        "trace_path": result.trace_path.name if result.trace_path is not None else None,
        "raw_schema_version": result.raw_schema_version,
        "raw_sha256": result.raw_sha256,
        "trace_sha256": result.trace_sha256,
        "error_type": result.error_type,
        "private_layout_clean": result.private_layout_clean,
    }


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(_SHA256_PATTERN.fullmatch(value))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_private_output_directory(
    *,
    repository_root: Path,
    output_directory: Path,
) -> Path:
    try:
        resolved_repository = repository_root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("repository_root must be an existing directory") from exc
    if not resolved_repository.is_dir():
        raise ValueError("repository_root must be an existing directory")
    top_level = _git_output(resolved_repository, ["rev-parse", "--show-toplevel"])
    try:
        resolved_top_level = Path(top_level).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("repository_root is not a valid Git checkout") from exc
    if resolved_top_level != resolved_repository:
        raise ValueError("repository_root must be the Git checkout top-level")

    outputs_root = resolved_repository / "outputs"
    private_root = outputs_root / "private"
    _reject_symlink(outputs_root, "repository outputs directory")
    _reject_symlink(private_root, "repository private outputs directory")
    if not private_root.exists():
        private_root.mkdir(parents=True, mode=0o700, exist_ok=False)
    _validate_private_directory(private_root, "repository private outputs directory")

    candidate = (
        output_directory
        if output_directory.is_absolute()
        else resolved_repository / output_directory
    )
    resolved_candidate = candidate.resolve(strict=False)
    if resolved_candidate.parent != private_root.resolve(strict=True):
        raise ValueError(
            "output_directory must be one direct child of repository "
            "outputs/private"
        )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", resolved_candidate.name):
        raise ValueError("private run directory name is invalid")
    if resolved_candidate.exists() or resolved_candidate.is_symlink():
        raise FileExistsError(
            f"execution output directory already exists: {resolved_candidate}"
        )
    relative = resolved_candidate.relative_to(resolved_repository).as_posix()
    tracked_prefix = f"{relative}/"
    head_entries = _git_output(
        resolved_repository,
        ["ls-tree", "-r", "--name-only", "-z", "HEAD", "--", tracked_prefix],
    )
    index_entries = _git_output(
        resolved_repository,
        ["ls-files", "-z", "--", tracked_prefix],
    )
    if head_entries or index_entries:
        raise ValueError(
            "output_directory must not overlap any tracked HEAD or index path"
        )
    ignored = _run_git(
        resolved_repository,
        ["check-ignore", "--quiet", "--no-index", "--", relative],
    )
    if ignored.returncode != 0:
        raise ValueError("output_directory must be ignored by repository Git rules")
    return resolved_candidate


def _reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")


def _validate_private_directory(path: Path, label: str) -> None:
    metadata = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{label} must be a directory")
    if metadata.st_uid != os.geteuid():
        raise PermissionError(f"{label} must be owned by the current user")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PermissionError(f"{label} must have no group/world permissions")


def _git_output(repository: Path, arguments: list[str]) -> str:
    completed = _run_git(repository, arguments)
    if completed.returncode != 0:
        raise ValueError("unable to verify repository Git metadata")
    return completed.stdout.strip()


def _run_git(
    repository: Path,
    arguments: list[str],
) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
    }
    return subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repository),
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


class _AtomicExecutionStore:
    """Private per-assignment directory with same-filesystem atomic writes."""

    __slots__ = ("directory", "result_path")

    def __init__(self, directory: Path):
        self.directory = directory
        self.result_path = directory / _RESULT_FILENAME

    @classmethod
    def create(cls, directory: Path) -> _AtomicExecutionStore:
        if directory.exists() or directory.is_symlink():
            raise FileExistsError(
                f"execution output directory already exists: {directory}"
            )
        directory.mkdir(mode=0o700, exist_ok=False)
        metadata = directory.stat(follow_symlinks=False)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise PermissionError(
                "execution output directory must be current-user owned and private"
            )
        return cls(directory.resolve())

    def write_result(self, value: Mapping[str, Any]) -> str:
        data = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        self._atomic_write(_RESULT_FILENAME, data, replace=True)
        return hashlib.sha256(data).hexdigest()

    def write_once(self, filename: str, data: bytes) -> Path:
        return self._atomic_write(filename, data, replace=False)

    def assert_layout(self, expected: Mapping[str, str | None]) -> None:
        entries = {entry.name: entry for entry in self.directory.iterdir()}
        if set(entries) != set(expected):
            raise PrivateLayoutViolation(
                "benchmark plugin changed the private execution directory layout"
            )
        for name, expected_sha256 in expected.items():
            path = entries[name]
            metadata = path.stat(follow_symlinks=False)
            if (
                path.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise PrivateLayoutViolation(
                    "private execution artifact type, owner, or mode is invalid"
                )
            if expected_sha256 is not None:
                observed = hashlib.sha256(path.read_bytes()).hexdigest()
                if observed != expected_sha256:
                    raise PrivateLayoutViolation(
                        "benchmark plugin changed a persisted execution artifact"
                    )

    def _atomic_write(self, filename: str, data: bytes, *, replace: bool) -> Path:
        destination = self.directory / filename
        if destination.exists() and not replace:
            raise FileExistsError(f"execution artifact already exists: {destination}")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.",
            dir=self.directory,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            directory_descriptor = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()
        return destination


__all__ = [
    "AssignmentExecutionError",
    "AssignmentExecutionResult",
    "execute_one_assignment",
]
