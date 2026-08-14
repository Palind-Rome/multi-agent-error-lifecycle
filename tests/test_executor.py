from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import traceback
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from mas_error_lifecycle.design import PlanItem
from mas_error_lifecycle.executor import (
    AssignmentExecutionError,
    execute_one_assignment,
)
from mas_error_lifecycle.plugins import (
    BenchmarkPluginRegistry,
    PluginExecutionContext,
    PluginRegistryError,
    RawBenchmarkRun,
)
from mas_error_lifecycle.schema import (
    AgentSpec,
    EventType,
    LifecycleEvent,
    OutcomeKind,
    RunManifest,
    RunOutcome,
    RunStatus,
)
from mas_error_lifecycle.store import TraceBundle, load_trace


class _FakePlugin:
    key = "fake.contract"
    version = "1.0.0"
    raw_schema_version = "fake.raw.v1"
    trace_benchmark = "FakeBench"
    allows_network = False
    supported_plan_versions = frozenset({"0.3.0"})
    supported_factor_bindings = frozenset({"native_task_passthrough"})

    def __init__(
        self,
        *,
        run_error: Exception | None = None,
        adapt_error: Exception | None = None,
        raw_payload: dict[str, Any] | None = None,
        returned_schema_version: str | None = None,
        manifest_run_id: str | None = None,
        side_effect_path: Path | None = None,
        mutate_result_path: Path | None = None,
        trace_config: dict[str, Any] | None = None,
    ) -> None:
        self.run_error = run_error
        self.adapt_error = adapt_error
        self.raw_payload = raw_payload or {"native": {"value": 3}}
        self.returned_schema_version = returned_schema_version
        self.manifest_run_id = manifest_run_id
        self.side_effect_path = side_effect_path
        self.mutate_result_path = mutate_result_path
        self.trace_config = trace_config
        self.calls: list[str] = []

    def validate_assignment(self, assignment: PlanItem) -> None:
        self.calls.append("validate")
        if assignment.protocol_kind != "fake_native":
            raise ValueError("unsupported fake protocol")

    def run(
        self,
        assignment: PlanItem,
        context: PluginExecutionContext,
    ) -> RawBenchmarkRun:
        self.calls.append("run")
        if not context.started_at:
            raise AssertionError("executor did not supply a start time")
        if self.side_effect_path is not None:
            self.side_effect_path.write_text("plugin-side-effect", encoding="utf-8")
        if self.mutate_result_path is not None:
            self.mutate_result_path.write_text(
                "tampered-running-result",
                encoding="utf-8",
            )
        if self.run_error is not None:
            raise self.run_error
        return RawBenchmarkRun(
            payload=self.raw_payload,
            schema_version=(
                self.returned_schema_version or self.raw_schema_version
            ),
        )

    def adapt(
        self,
        raw_run: RawBenchmarkRun,
        assignment: PlanItem,
        context: PluginExecutionContext,
    ) -> TraceBundle:
        self.calls.append("adapt")
        if self.adapt_error is not None:
            raise self.adapt_error
        return _bundle_for_assignment(
            assignment,
            started_at=context.started_at,
            run_id=self.manifest_run_id,
            raw_payload=dict(raw_run.payload),
            manifest_config=self.trace_config,
        )


def _assignment() -> PlanItem:
    return PlanItem(
        plan_version="0.3.0",
        benchmark_plugin="fake.contract",
        plugin_version="1.0.0",
        raw_schema_version="fake.raw.v1",
        experiment="executor-contract",
        purpose="engineering_smoke",
        protocol_kind="fake_native",
        suite_kind="native",
        execution_status="ready",
        review_status="native",
        analysis_eligible=False,
        task_id="TASK-FAKE-001",
        condition_id="condition-a",
        repeat=0,
        pair_id="pair-a",
        cluster_id="cluster-a",
        assignment_id="assignment-a",
        run_id="run-a",
        seed=7,
        seed_supported=True,
        run_order=0,
        factors={"protocol_variant": "native"},
        factor_bindings={"protocol_variant": "native_task_passthrough"},
        preregistration_hash=None,
        native_task_hash=None,
        estimated_backbone_calls=1,
        estimated_judge_calls=0,
    )


def _bundle_for_assignment(
    assignment: PlanItem,
    *,
    started_at: str,
    run_id: str | None,
    raw_payload: dict[str, Any],
    manifest_config: dict[str, Any] | None = None,
) -> TraceBundle:
    resolved_run_id = run_id or assignment.run_id
    return TraceBundle(
        manifest=RunManifest(
            run_id=resolved_run_id,
            task_id=assignment.task_id,
            condition_id=assignment.condition_id,
            benchmark="FakeBench",
            seed=assignment.seed,
            started_at=started_at,
            agents=(AgentSpec(agent_id="agent-a", role="worker"),),
            topology=(),
            protocol_kind=assignment.protocol_kind,
            suite_kind=assignment.suite_kind,
            purpose=assignment.purpose,
            pair_id=assignment.pair_id,
            cluster_id=assignment.cluster_id,
            assignment_id=assignment.assignment_id,
            analysis_eligible=assignment.analysis_eligible,
            execution_status=assignment.execution_status,
            review_status=assignment.review_status,
            preregistration_hash=assignment.preregistration_hash,
            native_task_hash=assignment.native_task_hash,
            config=(
                manifest_config
                if manifest_config is not None
                else {"raw_seen": raw_payload}
            ),
        ),
        artifacts=(),
        prompts=(),
        events=(
            LifecycleEvent(
                event_id="event-finalized",
                run_id=resolved_run_id,
                event_type=EventType.RUN_FINALIZED,
                step=1,
                timestamp=started_at,
            ),
        ),
        outcome=RunOutcome(
            run_id=resolved_run_id,
            success=None,
            score=None,
            final_step=1,
            evaluator="fake-contract",
            outcome_kind=OutcomeKind.UNAVAILABLE,
            run_status=RunStatus.COMPLETED,
        ),
    )


class ExecutorContractTests(unittest.TestCase):
    def _repository(self, root: Path, *, ignored: bool = True) -> Path:
        repository = root / "repository"
        repository.mkdir()
        subprocess.run(
            ["git", "init", "--quiet", str(repository)],
            check=True,
            capture_output=True,
        )
        if ignored:
            (repository / ".gitignore").write_text(
                "outputs/\noutputs/private/\n",
                encoding="utf-8",
            )
        (repository / ".repo-marker").write_text("test repository\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repository), "add", ".repo-marker"],
            check=True,
            capture_output=True,
        )
        if ignored:
            subprocess.run(
                ["git", "-C", str(repository), "add", ".gitignore"],
                check=True,
                capture_output=True,
            )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "-c",
                "user.name=Executor Contract",
                "-c",
                "user.email=executor-contract.invalid",
                "commit",
                "--quiet",
                "-m",
                "test fixture",
            ],
            check=True,
            capture_output=True,
        )
        private = repository / "outputs" / "private"
        private.mkdir(parents=True, mode=0o700)
        os.chmod(private, 0o700)
        return repository

    def _execute(
        self,
        repository: Path,
        plugin: _FakePlugin,
        *,
        assignment: PlanItem | None = None,
        directory_name: str = "contract-run",
        registry: BenchmarkPluginRegistry | None = None,
    ):
        return execute_one_assignment(
            assignment or _assignment(),
            registry=registry or BenchmarkPluginRegistry((plugin,)),
            repository_root=repository,
            output_directory=repository / "outputs" / "private" / directory_name,
        )

    def test_success_routes_explicit_plugin_and_persists_valid_trace(self) -> None:
        plugin = _FakePlugin()
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            result = self._execute(repository, plugin)

            self.assertEqual(result.status, "completed")
            self.assertEqual(plugin.calls, ["validate", "run", "adapt"])
            self.assertIsNotNone(result.raw_path)
            self.assertIsNotNone(result.trace_path)
            raw = json.loads(result.raw_path.read_text(encoding="utf-8"))
            self.assertEqual(raw, plugin.raw_payload)
            bundle = load_trace(result.trace_path)
            self.assertEqual(bundle.manifest.assignment_id, "assignment-a")
            record = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["benchmark_plugin"], "fake.contract")
            self.assertEqual(record["raw_schema_version"], "fake.raw.v1")
            self.assertRegex(record["raw_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(record["trace_sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(
                stat.S_IMODE(result.output_directory.stat().st_mode), 0o700
            )
            for path in (result.result_path, result.raw_path, result.trace_path):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertFalse(
                any(path.name.startswith(".") for path in result.output_directory.iterdir())
            )

    def test_unknown_plugin_fails_durably_without_fallback(self) -> None:
        plugin = _FakePlugin()
        assignment = replace(_assignment(), benchmark_plugin="missing.plugin")
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin, assignment=assignment)
            result = raised.exception.result
            self.assertEqual(result.stage, "plugin_resolution")
            self.assertEqual(result.error_type, "UnknownBenchmarkPlugin")
            self.assertEqual(plugin.calls, [])
            record = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "failed")

    def test_pinned_plugin_and_raw_versions_must_match_registry(self) -> None:
        for assignment in (
            replace(_assignment(), plugin_version="2.0.0"),
            replace(_assignment(), raw_schema_version="fake.raw.v2"),
        ):
            with self.subTest(assignment=assignment):
                plugin = _FakePlugin()
                with tempfile.TemporaryDirectory() as directory:
                    repository = self._repository(Path(directory))
                    with self.assertRaises(AssignmentExecutionError) as raised:
                        self._execute(repository, plugin, assignment=assignment)
                    self.assertEqual(raised.exception.result.stage, "plugin_resolution")
                    self.assertEqual(plugin.calls, [])

    def test_plugin_returned_schema_must_match_assignment(self) -> None:
        plugin = _FakePlugin(returned_schema_version="fake.raw.v2")
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            self.assertEqual(raised.exception.result.stage, "raw_validation")
            self.assertFalse(
                (raised.exception.result.output_directory / "raw-result.json").exists()
            )

    def test_paused_unvalidated_and_unsupported_binding_never_run(self) -> None:
        assignments = (
            replace(_assignment(), execution_status="paused"),
            replace(_assignment(), review_status="unvalidated"),
            replace(_assignment(), review_status="unvalidate"),
            replace(
                _assignment(),
                factor_bindings={"protocol_variant": "governance_policy"},
            ),
        )
        for index, assignment in enumerate(assignments):
            with self.subTest(assignment=assignment):
                plugin = _FakePlugin()
                with tempfile.TemporaryDirectory() as directory:
                    repository = self._repository(Path(directory))
                    with self.assertRaises(AssignmentExecutionError):
                        self._execute(
                            repository,
                            plugin,
                            assignment=assignment,
                            directory_name=f"rejected-{index}",
                        )
                    self.assertNotIn("run", plugin.calls)

    def test_direct_plan_item_unknown_review_status_fails_before_plugin(self) -> None:
        plugin = _FakePlugin()
        assignment = replace(_assignment(), review_status="typo")
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin, assignment=assignment)
            self.assertEqual(raised.exception.result.stage, "assignment_validation")
            self.assertEqual(plugin.calls, [])

    def test_run_failure_is_redacted_and_durable(self) -> None:
        secret = "super-secret-provider-payload"
        plugin = _FakePlugin(run_error=RuntimeError(secret))
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            result = raised.exception.result
            self.assertEqual(result.stage, "plugin_run")
            self.assertEqual(result.error_type, "RuntimeError")
            self.assertIsNone(result.raw_path)
            persisted = b"".join(
                path.read_bytes() for path in result.output_directory.iterdir()
            )
            self.assertNotIn(secret.encode("utf-8"), persisted)
            rendered_traceback = "".join(
                traceback.format_exception(raised.exception)
            )
            self.assertNotIn(secret, rendered_traceback)
            self.assertTrue(raised.exception.__suppress_context__)

    def test_adaptation_failure_retains_raw_and_no_trace(self) -> None:
        plugin = _FakePlugin(adapt_error=ValueError("private-response-text"))
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            result = raised.exception.result
            self.assertEqual(result.stage, "adaptation")
            self.assertTrue(result.raw_path.is_file())
            self.assertIsNone(result.trace_path)
            self.assertFalse((result.output_directory / "lifecycle-trace.jsonl").exists())

    def test_invalid_raw_json_and_misaligned_trace_fail_closed(self) -> None:
        cases = (
            (_FakePlugin(raw_payload={"value": float("nan")}), "raw_validation"),
            (_FakePlugin(manifest_run_id="different-run"), "adaptation"),
        )
        for index, (plugin, expected_stage) in enumerate(cases):
            with self.subTest(expected_stage=expected_stage):
                with tempfile.TemporaryDirectory() as directory:
                    repository = self._repository(Path(directory))
                    with self.assertRaises(AssignmentExecutionError) as raised:
                        self._execute(
                            repository,
                            plugin,
                            directory_name=f"invalid-{index}",
                        )
                    self.assertEqual(raised.exception.result.stage, expected_stage)

    def test_output_must_be_direct_ignored_private_child(self) -> None:
        plugin = _FakePlugin()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._repository(root)
            public = repository / "docs" / "leaky-run"
            with self.assertRaisesRegex(ValueError, "outputs/private"):
                execute_one_assignment(
                    _assignment(),
                    registry=BenchmarkPluginRegistry((plugin,)),
                    repository_root=repository,
                    output_directory=public,
                )
            self.assertFalse(public.exists())

        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory), ignored=False)
            with self.assertRaisesRegex(ValueError, "ignored"):
                self._execute(repository, _FakePlugin())

    def test_deleted_tracked_private_artifact_cannot_be_recreated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            run_directory = repository / "outputs" / "private" / "contract-run"
            run_directory.mkdir(mode=0o700)
            tracked_raw = run_directory / "raw-result.json"
            tracked_raw.write_text("{}\n", encoding="utf-8")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "add",
                    "--force",
                    "outputs/private/contract-run/raw-result.json",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=Executor Contract",
                    "-c",
                    "user.email=executor-contract.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "tracked private trap",
                ],
                check=True,
                capture_output=True,
            )
            tracked_raw.unlink()
            run_directory.rmdir()

            with self.assertRaisesRegex(ValueError, "tracked HEAD or index"):
                self._execute(repository, _FakePlugin())
            self.assertFalse(run_directory.exists())

    def test_private_parent_permissions_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            private = repository / "outputs" / "private"
            os.chmod(private, 0o755)
            with self.assertRaises(PermissionError):
                self._execute(repository, _FakePlugin())

    def test_private_parent_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._repository(root)
            private = repository / "outputs" / "private"
            private.rmdir()
            outside = root / "outside-private"
            outside.mkdir(mode=0o700)
            private.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                self._execute(repository, _FakePlugin())

    def test_plugin_cannot_add_files_to_executor_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            run_directory = repository / "outputs" / "private" / "contract-run"
            plugin = _FakePlugin(side_effect_path=run_directory / "unmanaged.txt")
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            self.assertEqual(raised.exception.result.stage, "security_layout")
            self.assertEqual(
                raised.exception.result.error_type,
                "PrivateLayoutViolation",
            )
            self.assertFalse(raised.exception.result.private_layout_clean)

    def test_plugin_cannot_modify_running_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            run_directory = repository / "outputs" / "private" / "contract-run"
            plugin = _FakePlugin(
                mutate_result_path=run_directory / "execution-result.json"
            )
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            result = raised.exception.result
            self.assertEqual(result.stage, "security_layout")
            self.assertFalse(result.private_layout_clean)
            record = json.loads(result.result_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["error_type"], "PrivateLayoutViolation")

    def test_raw_authorization_field_is_never_persisted(self) -> None:
        plugin = _FakePlugin(
            raw_payload={
                "request": {
                    "headers": {"Authorization": "Bearer do-not-write"}
                }
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            result = raised.exception.result
            self.assertEqual(result.stage, "raw_validation")
            self.assertFalse((result.output_directory / "raw-result.json").exists())

    def test_keyless_credential_shaped_value_is_never_persisted(self) -> None:
        secret = "VALUE-GATE-CREDENTIAL"
        plugin = _FakePlugin(
            raw_payload={"opaque_metadata": [f"Bearer {secret}"]}
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            result = raised.exception.result
            self.assertEqual(result.stage, "raw_validation")
            persisted = b"".join(
                path.read_bytes() for path in result.output_directory.iterdir()
            )
            self.assertNotIn(secret.encode("utf-8"), persisted)

    def test_trace_authorization_field_is_never_persisted(self) -> None:
        secret = "TRACE-CREDENTIAL-MUST-NOT-PERSIST"
        plugin = _FakePlugin(
            trace_config={
                "provider_metadata": {
                    "headers": {"Authorization": f"Bearer {secret}"}
                }
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            result = raised.exception.result
            self.assertEqual(result.stage, "trace_validation")
            self.assertFalse(
                (result.output_directory / "lifecycle-trace.jsonl").exists()
            )
            persisted = b"".join(
                path.read_bytes() for path in result.output_directory.iterdir()
            )
            self.assertNotIn(secret.encode("utf-8"), persisted)

    def test_trace_benchmark_must_match_registered_plugin(self) -> None:
        plugin = _FakePlugin()
        plugin.trace_benchmark = "DifferentBench"
        with tempfile.TemporaryDirectory() as directory:
            repository = self._repository(Path(directory))
            with self.assertRaises(AssignmentExecutionError) as raised:
                self._execute(repository, plugin)
            self.assertEqual(raised.exception.result.stage, "adaptation")

    def test_registry_is_closed_and_rejects_duplicate_keys(self) -> None:
        plugin = _FakePlugin()
        registry = BenchmarkPluginRegistry((plugin,))
        self.assertEqual(registry.keys, ("fake.contract",))
        self.assertFalse(hasattr(registry, "register"))
        with self.assertRaisesRegex(PluginRegistryError, "duplicate"):
            BenchmarkPluginRegistry((plugin, _FakePlugin()))

        plugin.allows_network = True
        with self.assertRaisesRegex(PluginRegistryError, "network-capable"):
            BenchmarkPluginRegistry((plugin,))


if __name__ == "__main__":
    unittest.main()
