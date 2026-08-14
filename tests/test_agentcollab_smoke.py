from __future__ import annotations

import contextlib
import email.message
import io
import json
import multiprocessing
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.response
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from mas_error_lifecycle.adapters.agentcollab_smoke import (
    ANALYSIS_ELIGIBLE,
    APPROVED_TASK_ID,
    PURPOSE,
    BudgetExceeded,
    BudgetGate,
    BudgetLimits,
    HTTPResult,
    OpenAICompatibleSmokeProvider,
    PAPERBYPASS_BASE_URL,
    PAPERBYPASS_MODEL,
    PrivateRunStore,
    ProviderRequestError,
    ProviderSettings,
    RunLedger,
    SmokeConfigurationError,
    SmokeSettings,
    expected_agentcollab_calls,
    load_smoke_settings,
    read_api_key_from_user_input,
    run_single_agentcollab_smoke,
    validate_native_task,
    _urllib_transport,
    _process_bounded_urllib_transport,
    _git_subprocess_environment,
    _read_response_body,
    _run_git,
    main,
    verify_agentcollab_repository,
)
from mas_error_lifecycle.store import load_trace


@dataclass
class _Message:
    role: str
    content: str


def _settings(
    *,
    max_calls: int = 2,
    max_wall_seconds: float = 60.0,
    send_seed: bool = True,
) -> SmokeSettings:
    return SmokeSettings(
        provider=ProviderSettings(
            base_url=PAPERBYPASS_BASE_URL,
            model=PAPERBYPASS_MODEL,
            temperature=0.0,
            request_timeout_seconds=10.0,
            send_seed=send_seed,
        ),
        limits=BudgetLimits(
            max_calls=max_calls,
            max_input_tokens=10_000,
            max_output_tokens=100,
            max_output_tokens_per_call=50,
            max_wall_seconds=max_wall_seconds,
            max_cost_usd=Decimal("0.10"),
            max_input_cost_usd_per_million_tokens=Decimal("0.05"),
            max_output_cost_usd_per_million_tokens=Decimal("0.20"),
        ),
    )


def _ledger_and_provider(
    repository: Path,
    secret: str,
    transport,
    *,
    max_calls: int = 2,
    send_seed: bool = True,
):
    settings = _settings(max_calls=max_calls, send_seed=send_seed)
    store = PrivateRunStore.create(repository, "test-run", secret)
    budget = BudgetGate(settings.limits)
    ledger = RunLedger(
        store,
        run_id="test-run",
        task_id="TASK-RTD-TEST",
        metric="rtd",
        native_task_sha256="a" * 64,
        upstream_commit="b" * 40,
        settings=settings,
        seed=7,
    )
    ledger.mark_running(budget)
    provider = OpenAICompatibleSmokeProvider(
        settings.provider,
        api_key=secret,
        budget=budget,
        store=store,
        ledger=ledger,
        transport=transport,
        seed=7,
    )
    return settings, store, budget, ledger, provider


def _success_result(content: str = "safe result") -> HTTPResult:
    return HTTPResult(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(
            {
                "id": "response-1",
                "model": PAPERBYPASS_MODEL,
                "choices": [
                    {
                        "message": {"content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }
        ).encode(),
    )


def _create_integrity_test_repository(
    root: Path,
    *,
    clean_filter: bool = False,
) -> tuple[Path, str]:
    repository = root / "upstream"
    runner = repository / "agentcollabbench" / "harness" / "runner.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# pinned runner fixture\n")
    (repository / "tracked.py").write_text("canonical\n")
    if clean_filter:
        (repository / ".gitattributes").write_text(
            "tracked.py filter=normalize\n"
        )
    for arguments in (
        ["init", "--quiet", "--object-format=sha1"],
        (
            ["config", "filter.normalize.clean", "sed 's/.*/canonical/'"]
            if clean_filter
            else None
        ),
        ["add", "--all"],
        [
            "-c",
            "user.name=Smoke Test",
            "-c",
            "user.email=smoke@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "integrity fixture",
        ],
    ):
        if arguments is None:
            continue
        result = _run_git(repository, arguments)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
    head = _run_git(repository, ["rev-parse", "HEAD"])
    if head.returncode != 0:
        raise AssertionError(head.stderr)
    return repository, head.stdout.strip()


class AgentCollabSmokeTests(unittest.TestCase):
    def test_api_key_uses_hidden_input_or_one_non_tty_stdin_line(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.getpass.getpass",
            return_value="top-secret",
        ) as hidden_input, contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            key, input_method = read_api_key_from_user_input(use_stdin=False)
        self.assertEqual((key, input_method), ("top-secret", "interactive_getpass"))
        hidden_input.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

        with patch.dict(os.environ, {}, clear=True), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.getpass.getpass"
        ) as hidden_input:
            key, input_method = read_api_key_from_user_input(
                use_stdin=True,
                stdin=io.StringIO("stdin-secret\n"),
            )
        self.assertEqual((key, input_method), ("stdin-secret", "stdin_single_line"))
        hidden_input.assert_not_called()

        with patch.dict(
            os.environ, {"PAPERBYPASS_API_KEY": "unsafe"}, clear=True
        ), self.assertRaises(SmokeConfigurationError):
            read_api_key_from_user_input(use_stdin=False)

    def test_success_persists_request_response_and_ledger_without_key(self) -> None:
        captured: dict[str, object] = {}
        secret = "paperbypass-super-secret"

        def transport(endpoint, headers, body, timeout):
            captured.update(
                endpoint=endpoint,
                headers=dict(headers),
                body=json.loads(body),
                timeout=timeout,
            )
            return _success_result()

        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            _, store, budget, ledger, provider = _ledger_and_provider(
                repository, secret, transport, max_calls=1
            )
            response = provider.chat([_Message("user", "hello")])

            self.assertEqual(response.content, "safe result")
            self.assertEqual(response.input_tokens, 12)
            self.assertEqual(response.output_tokens, 3)
            self.assertEqual(
                captured["headers"]["Authorization"], f"Bearer {secret}"
            )
            self.assertEqual(captured["body"]["seed"], 7)
            self.assertLessEqual(captured["body"]["max_tokens"], 50)
            self.assertEqual(budget.calls_completed, 1)

            ledger_document = json.loads(ledger.path.read_text())
            self.assertEqual(ledger_document["status"], "running")
            self.assertEqual(ledger_document["purpose"], PURPOSE)
            self.assertIs(
                ledger_document["analysis_eligible"], ANALYSIS_ELIGIBLE
            )
            self.assertEqual(ledger_document["python_injection_seed"], 7)
            self.assertTrue(ledger_document["provider_seed_sent"])
            self.assertEqual(
                ledger_document["provider"]["api_key_input_method"],
                "caller_memory",
            )
            self.assertNotIn("api_key_source", ledger_document["provider"])
            self.assertEqual(ledger_document["calls"][0]["status"], "success")

            all_private_text = "\n".join(
                path.read_text()
                for path in store.run_directory.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret, all_private_text)
            request_document = json.loads(
                (store.run_directory / "raw/openai-compatible-00001.request.json")
                .read_text()
            )
            self.assertFalse(request_document["authorization_persisted"])
            self.assertNotIn("Authorization", request_document)
            for path in store.run_directory.rglob("*"):
                if path.is_file():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_call_cap_stops_before_a_second_http_request(self) -> None:
        attempts = 0

        def transport(endpoint, headers, body, timeout):
            nonlocal attempts
            attempts += 1
            return _success_result()

        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, provider = _ledger_and_provider(
                Path(directory), "secret", transport, max_calls=1
            )
            provider.chat([_Message("user", "first")])
            with self.assertRaises(BudgetExceeded):
                provider.chat([_Message("user", "second")])
        self.assertEqual(attempts, 1)

    def test_http_failure_has_durable_redacted_failure_ledger(self) -> None:
        secret = "do-not-persist-me"

        def transport(endpoint, headers, body, timeout):
            return HTTPResult(
                status=503,
                headers={"x-debug": secret},
                body=json.dumps({"error": f"reflected {secret}"}).encode(),
            )

        with tempfile.TemporaryDirectory() as directory:
            _, store, _, ledger, provider = _ledger_and_provider(
                Path(directory), secret, transport
            )
            with self.assertRaises(ProviderRequestError):
                provider.chat([_Message("user", "hello")])

            ledger_document = json.loads(ledger.path.read_text())
            self.assertEqual(ledger_document["status"], "provider_failed")
            self.assertEqual(
                ledger_document["failure"]["error_type"], "ProviderRequestError"
            )
            self.assertEqual(ledger_document["calls"][0]["status"], "failed")
            self.assertGreater(
                Decimal(ledger_document["budget"]["accounted_cost_usd"]),
                Decimal("0"),
            )
            private_text = "\n".join(
                path.read_text()
                for path in store.run_directory.rglob("*")
                if path.is_file()
            )
            self.assertNotIn(secret, private_text)
            self.assertIn("[REDACTED]", private_text)

    def test_malformed_success_response_is_a_durable_provider_failure(self) -> None:
        def transport(endpoint, headers, body, timeout):
            return HTTPResult(
                status=200,
                headers={},
                body=b'{"choices": [{"message": {"content": "x"}}]}',
            )

        with tempfile.TemporaryDirectory() as directory:
            _, _, budget, ledger, provider = _ledger_and_provider(
                Path(directory), "secret", transport
            )
            with self.assertRaises(ProviderRequestError):
                provider.chat([_Message("user", "hello")])
            self.assertEqual(
                json.loads(ledger.path.read_text())["status"], "provider_failed"
            )
            self.assertEqual(budget.unreconciled_calls, 1)

    def test_response_contract_failures_are_durable(self) -> None:
        base = {
            "id": "response-1",
            "model": PAPERBYPASS_MODEL,
            "choices": [
                {
                    "message": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
        cases = {
            "missing_model": lambda value: value.pop("model"),
            "wrong_model": lambda value: value.update(model="wrong/model"),
            "empty_content": lambda value: value["choices"][0]["message"].update(
                content="   "
            ),
            "null_finish_reason": lambda value: value["choices"][0].update(
                finish_reason=None
            ),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                response_value = json.loads(json.dumps(base))
                mutate(response_value)

                def transport(endpoint, headers, body, timeout):
                    return HTTPResult(
                        status=200,
                        headers={},
                        body=json.dumps(response_value).encode(),
                    )

                _, _, _, ledger, provider = _ledger_and_provider(
                    Path(directory), "secret", transport
                )
                with self.assertRaises(ProviderRequestError):
                    provider.chat([_Message("user", "hello")])
                ledger_document = json.loads(ledger.path.read_text())
                self.assertEqual(ledger_document["status"], "provider_failed")
                self.assertEqual(ledger_document["calls"][0]["status"], "failed")

    def test_redirect_response_is_a_durable_provider_failure(self) -> None:
        attempts = 0

        def transport(endpoint, headers, body, timeout):
            nonlocal attempts
            attempts += 1
            return HTTPResult(
                status=302,
                headers={"location": "https://evil.example/steal"},
                body=b"redirect forbidden",
            )

        with tempfile.TemporaryDirectory() as directory:
            _, _, _, ledger, provider = _ledger_and_provider(
                Path(directory), "secret", transport
            )
            with self.assertRaises(ProviderRequestError):
                provider.chat([_Message("user", "hello")])
            ledger_document = json.loads(ledger.path.read_text())

        self.assertEqual(attempts, 1)
        self.assertEqual(ledger_document["status"], "provider_failed")
        self.assertEqual(ledger_document["calls"][0]["status"], "failed")

    def test_wall_gate_stops_before_transport(self) -> None:
        now = [0.0]
        limits = _settings(max_wall_seconds=1.0).limits
        budget = BudgetGate(
            limits,
            started_monotonic=0.0,
            monotonic=lambda: now[0],
        )
        now[0] = 1.1
        with self.assertRaises(BudgetExceeded):
            budget.reserve(
                [{"role": "user", "content": "x"}],
                requested_max_output_tokens=None,
                request_timeout_seconds=10.0,
            )

    def test_settings_require_all_positive_caps_and_safe_url(self) -> None:
        malicious_urls = [
            "http://localhost/api/v1",
            "https://evil.example/api/v1",
            "https://aigateway.paperbypass.com:443/api/v1",
            "https://aigateway.paperbypass.com/api/v2",
            "https://aigateway.paperbypass.com/api/v1/extra",
            "https://user:password@aigateway.paperbypass.com/api/v1",
            "https://aigateway.paperbypass.com/api/v1?target=evil",
            "https://aigateway.paperbypass.com/api/v1#fragment",
            "https://AIGATEWAY.PAPERBYPASS.COM/api/v1",
        ]
        for base_url in malicious_urls:
            with self.subTest(base_url=base_url):
                with self.assertRaises(SmokeConfigurationError):
                    ProviderSettings(base_url=base_url, model=PAPERBYPASS_MODEL)
        self.assertEqual(
            ProviderSettings(
                base_url=f"{PAPERBYPASS_BASE_URL}/",
                model=PAPERBYPASS_MODEL,
            ).base_url,
            PAPERBYPASS_BASE_URL,
        )
        with self.assertRaises(SmokeConfigurationError):
            ProviderSettings(
                base_url=PAPERBYPASS_BASE_URL,
                model="qwen/not-approved",
            )
        with self.assertRaises(SmokeConfigurationError):
            BudgetLimits(
                max_calls=0,
                max_input_tokens=1,
                max_output_tokens=1,
                max_output_tokens_per_call=1,
                max_wall_seconds=1.0,
                max_cost_usd=Decimal("1"),
                max_input_cost_usd_per_million_tokens=Decimal("1"),
                max_output_cost_usd_per_million_tokens=Decimal("1"),
            )

        settings = load_smoke_settings(
            repository_root=Path.cwd(),
            config_path=None,
            overrides={
                "base_url": "https://aigateway.paperbypass.com/api/v1",
                "model": PAPERBYPASS_MODEL,
                "max_calls": 2,
                "max_input_tokens": 1000,
                "max_output_tokens": 100,
                "max_output_tokens_per_call": 50,
                "max_wall_seconds": 30,
                "max_cost_usd": "0.01",
                "max_input_cost_usd_per_million_tokens": "0.04815",
                "max_output_cost_usd_per_million_tokens": "0.19305",
            },
        )
        self.assertEqual(
            settings.provider.model, PAPERBYPASS_MODEL
        )
        with self.assertRaises(SmokeConfigurationError):
            BudgetLimits(
                max_calls=1,
                max_input_tokens=1,
                max_output_tokens=1,
                max_output_tokens_per_call=1,
                max_wall_seconds=1.0,
                max_cost_usd=Decimal("1"),
                max_input_cost_usd_per_million_tokens=Decimal("0.04814"),
                max_output_cost_usd_per_million_tokens=Decimal("0.19305"),
            )
        with self.assertRaises(SmokeConfigurationError):
            BudgetLimits(
                max_calls=1,
                max_input_tokens=1,
                max_output_tokens=1,
                max_output_tokens_per_call=1,
                max_wall_seconds=1.0,
                max_cost_usd=Decimal("1"),
                max_input_cost_usd_per_million_tokens=Decimal("0.04815"),
                max_output_cost_usd_per_million_tokens=Decimal("0.19304"),
            )

    def test_native_task_gate_rejects_derived_and_counts_one_task(self) -> None:
        task = {
            "task_id": "TASK-RTD-TEST",
            "metric_applicability": ["rtd"],
            "expected_turns": 7,
            "injections": {"rtd": {"tracer_id": "TRACE"}},
            "topology": {
                "agents": [{"agent_id": "A"}, {"agent_id": "B"}],
                "speaking_order": ["A", "B"],
            },
        }
        validate_native_task(
            task,
            expected_task_id="TASK-RTD-TEST",
            metric="rtd",
        )
        self.assertEqual(expected_agentcollab_calls(task), 7)
        task["injections"]["rtd"]["expected_turns"] = 5
        self.assertEqual(expected_agentcollab_calls(task, metric="rtd"), 5)
        task["injections"]["rtd"].pop("expected_turns")
        one_agent = json.loads(json.dumps(task))
        one_agent["topology"]["agents"] = one_agent["topology"]["agents"][:1]
        with self.assertRaises(SmokeConfigurationError):
            validate_native_task(
                one_agent,
                expected_task_id="TASK-RTD-TEST",
                metric="rtd",
            )
        task["experimental_metadata"] = {"protocol_kind": "derived"}
        with self.assertRaises(SmokeConfigurationError):
            validate_native_task(
                task,
                expected_task_id="TASK-RTD-TEST",
                metric="rtd",
            )

    def test_private_output_rejects_symlink_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repository"
            outside = Path(directory) / "outside"
            root.mkdir()
            outside.mkdir()
            os.symlink(outside, root / "outputs")
            with self.assertRaises(SmokeConfigurationError):
                PrivateRunStore.create(root, "test-run", "secret")

    def test_real_driver_runs_pinned_upstream_with_offline_transport(self) -> None:
        workspace = Path(__file__).resolve().parents[2]
        source_upstream = workspace / "assets" / "AgentCollabBench"
        if not source_upstream.is_dir():
            self.skipTest("pinned AgentCollabBench checkout is not available")
        attempts = 0
        transport_saw_process_key: list[bool] = []

        def transport(endpoint, headers, body, timeout):
            nonlocal attempts
            attempts += 1
            transport_saw_process_key.append(
                "PAPERBYPASS_API_KEY" in os.environ
            )
            return HTTPResult(
                status=200,
                headers={"content-type": "application/json"},
                body=json.dumps(
                    {
                        "id": f"offline-{attempts}",
                        "model": PAPERBYPASS_MODEL,
                        "choices": [
                            {
                                "message": {
                                    "content": "offline deterministic response"
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 10,
                            "completion_tokens": 3,
                        },
                    }
                ).encode(),
            )

        settings = SmokeSettings(
            provider=ProviderSettings(
                base_url=PAPERBYPASS_BASE_URL,
                model=PAPERBYPASS_MODEL,
                send_seed=False,
            ),
            limits=BudgetLimits(
                max_calls=8,
                max_input_tokens=1_000_000,
                max_output_tokens=80,
                max_output_tokens_per_call=10,
                max_wall_seconds=30.0,
                max_cost_usd=Decimal("1"),
                max_input_cost_usd_per_million_tokens=Decimal("0.05"),
                max_output_cost_usd_per_million_tokens=Decimal("0.20"),
            ),
        )
        secret = "offline-integration-secret"
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as directory:
                temporary_root = Path(directory)
                upstream = temporary_root / "AgentCollabBench"
                clone = _run_git(
                    Path(__file__).resolve().parents[1],
                    [
                        "clone",
                        "--quiet",
                        "--no-hardlinks",
                        str(source_upstream),
                        str(upstream),
                    ],
                )
                self.assertEqual(clone.returncode, 0, clone.stderr)
                task_file = (
                    upstream / "tasks" / "TASK-DATAENG-RTD-060.json"
                )
                result = run_single_agentcollab_smoke(
                    repository_root=temporary_root / "driver-output",
                    agentcollab_repository=upstream,
                    task_file=task_file,
                    expected_task_id=APPROVED_TASK_ID,
                    metric="rtd",
                    settings=settings,
                    api_key=secret,
                    seed=7,
                    run_id="offline-integration",
                    transport=transport,
                )
                bundle = load_trace(result.trace_path)
                ledger_document = json.loads(result.ledger_path.read_text())
                raw_result = json.loads(result.raw_result_path.read_text())
                private_text = "\n".join(
                    path.read_text()
                    for path in result.run_directory.rglob("*")
                    if path.is_file()
                )
            self.assertNotIn("PAPERBYPASS_API_KEY", os.environ)

        self.assertEqual(attempts, 8)
        self.assertEqual(transport_saw_process_key, [False] * 8)
        self.assertEqual(ledger_document["budget"]["calls_started"], 8)
        self.assertEqual(ledger_document["budget"]["calls_completed"], 8)
        self.assertEqual(
            len(raw_result["run_result"]["trace"]["provider_requests"]),
            8,
        )
        self.assertEqual(bundle.manifest.purpose, PURPOSE)
        self.assertFalse(bundle.manifest.analysis_eligible)
        self.assertEqual(bundle.manifest.seed, 7)
        self.assertNotIn(secret, private_text)

    def test_urllib_transport_rejects_cross_origin_302_without_key_replay(
        self,
    ) -> None:
        secret = "redirect-sensitive-secret"
        request_urls: list[str] = []
        request_authorizations: list[str | None] = []
        start_url = "http://start.invalid/start"
        target_url = "http://target.invalid/redirect-target"

        class MemoryHTTPHandler(urllib.request.HTTPHandler):
            def http_open(self, request):
                request_urls.append(request.full_url)
                request_authorizations.append(
                    request.get_header("Authorization")
                )
                headers = email.message.Message()
                if request.full_url == start_url:
                    headers["Location"] = target_url
                    response = urllib.response.addinfourl(
                        BytesIO(b"redirect forbidden"),
                        headers,
                        request.full_url,
                        code=302,
                    )
                    response.msg = "Found"
                    return response
                response = urllib.response.addinfourl(
                    BytesIO(b"unexpected target request"),
                    headers,
                    request.full_url,
                    code=200,
                )
                response.msg = "OK"
                return response

        original_build_opener = urllib.request.build_opener

        def memory_opener(redirect_handler):
            return original_build_opener(
                redirect_handler,
                MemoryHTTPHandler(),
            )

        with patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.urllib.request.build_opener",
            side_effect=memory_opener,
        ):
            result = _urllib_transport(
                start_url,
                {
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                },
                b"{}",
                2.0,
            )

        self.assertEqual(result.status, 302)
        self.assertEqual(request_urls, [start_url])
        self.assertEqual(request_authorizations, [f"Bearer {secret}"])

    def test_response_reader_enforces_absolute_deadline_and_size(self) -> None:
        clock = [0.0]

        class SlowStream:
            headers: dict[str, str] = {}

            def read(self, size: int) -> bytes:
                clock[0] += 0.6
                return b"x"

        with self.assertRaises(ProviderRequestError):
            _read_response_body(
                SlowStream(),
                deadline=1.0,
                max_bytes=10,
                monotonic=lambda: clock[0],
            )

        oversized = BytesIO(b"123456")
        oversized.headers = {}
        with self.assertRaises(ProviderRequestError):
            _read_response_body(
                oversized,
                deadline=10.0,
                max_bytes=5,
                monotonic=lambda: 0.0,
            )

    def test_process_transport_times_out_slow_headers_and_reaps_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, _, _, provider = _ledger_and_provider(
                Path(directory), "in-memory-only-secret", None
            )
            self.assertIs(provider._transport, _process_bounded_urllib_transport)

        # A fork context lets this offline test inject a worker that stalls at
        # the point where urllib would be waiting for response headers.  The
        # production path explicitly requests spawn below.
        fork_context = multiprocessing.get_context("fork")
        worker_entered = fork_context.Event()

        def stall_before_headers(endpoint, headers, body, timeout):
            worker_entered.set()
            time.sleep(10.0)
            raise AssertionError("parent did not terminate stalled HTTP worker")

        prior_children = {child.pid for child in multiprocessing.active_children()}
        started = time.monotonic()
        with patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.multiprocessing.get_context",
            return_value=fork_context,
        ) as get_context, patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke._urllib_transport",
            side_effect=stall_before_headers,
        ):
            with self.assertRaises(ProviderRequestError):
                _process_bounded_urllib_transport(
                    "https://aigateway.paperbypass.com/api/v1/chat/completions",
                    {
                        "Authorization": "Bearer in-memory-only-secret",
                        "Content-Type": "application/json",
                    },
                    b"{}",
                    1.0,
                )
        get_context.assert_called_once_with("spawn")
        self.assertTrue(worker_entered.is_set(), "worker never reached header wait")
        self.assertLess(time.monotonic() - started, 2.5)
        remaining_children = {child.pid for child in multiprocessing.active_children()}
        self.assertTrue(remaining_children.issubset(prior_children))

    def test_test_process_was_started_without_api_key_in_proc_environ(self) -> None:
        environ_path = Path("/proc/self/environ")
        if not environ_path.is_file():
            self.skipTest("Linux /proc/self/environ is unavailable")
        entries = environ_path.read_bytes().split(b"\0")
        self.assertFalse(
            any(entry.startswith(b"PAPERBYPASS_API_KEY=") for entry in entries),
            "tests and real smoke must be launched without an environment key",
        )

    def test_git_subprocess_environment_is_sanitized_and_hardened(self) -> None:
        secret = "child-process-secret"
        with patch.dict(
            os.environ,
            {
                "PAPERBYPASS_API_KEY": secret,
                "GIT_DIR": "/malicious/git-dir",
                "GIT_WORK_TREE": "/malicious/worktree",
                "GIT_INDEX_FILE": "/malicious/index",
                "GIT_OBJECT_DIRECTORY": "/malicious/objects",
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/malicious/alternate",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.fsmonitor",
                "GIT_CONFIG_VALUE_0": "/malicious/fsmonitor",
            },
        ):
            environment = _git_subprocess_environment()
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os; print("
                        "'present' if 'PAPERBYPASS_API_KEY' in os.environ "
                        "else 'absent')"
                    ),
                ],
                capture_output=True,
                text=True,
                check=True,
                env=environment,
            )
            with patch(
                "mas_error_lifecycle.adapters.agentcollab_smoke.subprocess.run"
            ) as run:
                run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="", stderr=""
                )
                _run_git(Path.cwd(), ["status", "--porcelain"])
                command = run.call_args.args[0]
                child_environment = run.call_args.kwargs["env"]

        self.assertEqual(probe.stdout.strip(), "absent")
        self.assertNotIn("PAPERBYPASS_API_KEY", child_environment)
        self.assertFalse(any(name.startswith("GIT_") for name in child_environment))
        self.assertEqual(
            command[:6],
            [
                "git",
                "--no-replace-objects",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
            ],
        )

    def test_main_uses_patched_hidden_getpass_input(self) -> None:
        secret = "hidden-main-secret"
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.load_smoke_settings",
            return_value=_settings(max_calls=8),
        ), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.getpass.getpass",
            return_value=secret,
        ) as hidden_input, patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.run_single_agentcollab_smoke",
            side_effect=SmokeConfigurationError("expected test stop"),
        ) as run, contextlib.redirect_stderr(stderr):
            exit_code = main(
                [
                    "--agentcollab-repo",
                    "/unused/upstream",
                    "--task-file",
                    "/unused/task.json",
                    "--task-id",
                    APPROVED_TASK_ID,
                    "--metric",
                    "rtd",
                ]
            )
        hidden_input.assert_called_once()
        self.assertEqual(exit_code, 2)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertEqual(run.call_args.kwargs["api_key"], secret)
        self.assertEqual(
            run.call_args.kwargs["api_key_input_method"],
            "interactive_getpass",
        )

    def test_main_uses_patched_non_tty_stdin_input(self) -> None:
        secret = "stdin-main-secret"
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.load_smoke_settings",
            return_value=_settings(max_calls=8),
        ), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.sys.stdin",
            io.StringIO(secret + "\n"),
        ), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.getpass.getpass"
        ) as hidden_input, patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.run_single_agentcollab_smoke",
            side_effect=SmokeConfigurationError("expected test stop"),
        ) as run, contextlib.redirect_stderr(stderr):
            exit_code = main(
                [
                    "--api-key-stdin",
                    "--agentcollab-repo",
                    "/unused/upstream",
                    "--task-file",
                    "/unused/task.json",
                    "--task-id",
                    APPROVED_TASK_ID,
                    "--metric",
                    "rtd",
                ]
            )
        hidden_input.assert_not_called()
        self.assertEqual(exit_code, 2)
        self.assertNotIn(secret, stderr.getvalue())
        self.assertEqual(run.call_args.kwargs["api_key"], secret)
        self.assertEqual(
            run.call_args.kwargs["api_key_input_method"], "stdin_single_line"
        )

    def test_main_rejects_environment_key_before_config_or_prompt(self) -> None:
        secret = "unsafe-environment-secret"
        stderr = io.StringIO()
        with patch.dict(
            os.environ, {"PAPERBYPASS_API_KEY": secret}, clear=True
        ), patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.load_smoke_settings"
        ) as settings_loader, patch(
            "mas_error_lifecycle.adapters.agentcollab_smoke.getpass.getpass"
        ) as hidden_input, contextlib.redirect_stderr(stderr):
            exit_code = main(
                [
                    "--agentcollab-repo",
                    "/unused/upstream",
                    "--task-file",
                    "/unused/task.json",
                    "--task-id",
                    APPROVED_TASK_ID,
                    "--metric",
                    "rtd",
                ]
            )
        self.assertEqual(exit_code, 2)
        settings_loader.assert_not_called()
        hidden_input.assert_not_called()
        self.assertNotIn(secret, stderr.getvalue())

    def test_run_disables_bytecode_before_upstream_verification(self) -> None:
        observed: list[bool] = []

        def stop_after_observation(repository):
            observed.append(sys.dont_write_bytecode)
            raise SmokeConfigurationError("expected test stop")

        original = sys.dont_write_bytecode
        sys.dont_write_bytecode = False
        try:
            with patch.dict(os.environ, {}, clear=True), patch(
                "mas_error_lifecycle.adapters.agentcollab_smoke.verify_agentcollab_repository",
                side_effect=stop_after_observation,
            ), self.assertRaises(SmokeConfigurationError):
                run_single_agentcollab_smoke(
                    repository_root=Path("/unused/output"),
                    agentcollab_repository=Path("/unused/upstream"),
                    task_file=Path("/unused/task.json"),
                    expected_task_id=APPROVED_TASK_ID,
                    metric="rtd",
                    settings=_settings(max_calls=8),
                    api_key="in-memory-secret",
                )
        finally:
            sys.dont_write_bytecode = original
        self.assertEqual(observed, [True])

    def test_raw_tree_rejects_assume_unchanged_tracked_python_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, head = _create_integrity_test_repository(Path(directory))
            tracked = repository / "tracked.py"
            tracked.write_text("malicious raw replacement\n")
            update = _run_git(
                repository,
                ["update-index", "--assume-unchanged", "tracked.py"],
            )
            self.assertEqual(update.returncode, 0, update.stderr)
            hidden_status = _run_git(
                repository,
                [
                    "status",
                    "--porcelain",
                    "--ignored",
                    "--untracked-files=all",
                ],
            )
            self.assertEqual(hidden_status.stdout, "")
            with patch(
                "mas_error_lifecycle.adapters.agentcollab_smoke.TESTED_AGENTCOLLAB_COMMIT",
                head,
            ), self.assertRaisesRegex(
                SmokeConfigurationError, "raw worktree bytes"
            ):
                verify_agentcollab_repository(repository)

    def test_raw_tree_rejects_edit_hidden_by_clean_filter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository, head = _create_integrity_test_repository(
                Path(directory), clean_filter=True
            )
            (repository / "tracked.py").write_text("malicious filtered bytes\n")
            masked_add = _run_git(repository, ["add", "--", "tracked.py"])
            self.assertEqual(masked_add.returncode, 0, masked_add.stderr)
            hidden_status = _run_git(
                repository,
                [
                    "status",
                    "--porcelain",
                    "--ignored",
                    "--untracked-files=all",
                ],
            )
            self.assertEqual(hidden_status.returncode, 0, hidden_status.stderr)
            self.assertEqual(hidden_status.stdout, "")
            with patch(
                "mas_error_lifecycle.adapters.agentcollab_smoke.TESTED_AGENTCOLLAB_COMMIT",
                head,
            ), self.assertRaisesRegex(
                SmokeConfigurationError, "raw worktree bytes"
            ):
                verify_agentcollab_repository(repository)

    def test_repository_verification_rejects_nonignored_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            runner = repository / "agentcollabbench" / "harness" / "runner.py"
            runner.parent.mkdir(parents=True)
            runner.write_text("# test fixture\n")

            def git_output(path, arguments):
                if arguments == ["rev-parse", "--show-toplevel"]:
                    return str(repository) + "\n"
                if arguments == ["rev-parse", "--show-object-format"]:
                    return "sha1\n"
                if arguments == ["rev-parse", "HEAD"]:
                    return (
                        "f016f600568b6d8127dc861e4c83c87b72750d63\n"
                    )
                return "?? rogue.py\n"

            with patch(
                "mas_error_lifecycle.adapters.agentcollab_smoke._git_output",
                side_effect=git_output,
            ):
                with self.assertRaises(SmokeConfigurationError):
                    verify_agentcollab_repository(repository)

    def test_repository_verification_rejects_ignored_root_shadow_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            runner = repository / "agentcollabbench" / "harness" / "runner.py"
            runner.parent.mkdir(parents=True)
            runner.write_text("# test fixture\n")
            seen_arguments: list[list[str]] = []

            def git_output(path, arguments):
                seen_arguments.append(arguments)
                if arguments == ["rev-parse", "--show-toplevel"]:
                    return str(repository) + "\n"
                if arguments == ["rev-parse", "--show-object-format"]:
                    return "sha1\n"
                if arguments == ["rev-parse", "HEAD"]:
                    return "f016f600568b6d8127dc861e4c83c87b72750d63\n"
                if "--ignored" in arguments:
                    return "!! logging.pyc\n"
                return ""

            with patch(
                "mas_error_lifecycle.adapters.agentcollab_smoke._git_output",
                side_effect=git_output,
            ), self.assertRaisesRegex(SmokeConfigurationError, "checkout contains"):
                verify_agentcollab_repository(repository)
            self.assertIn(
                [
                    "status",
                    "--porcelain",
                    "--ignored",
                    "--untracked-files=all",
                ],
                seen_arguments,
            )


if __name__ == "__main__":
    unittest.main()
