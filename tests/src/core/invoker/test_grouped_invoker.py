"""Tests for mixed-runtime grouped headless dispatch."""

from __future__ import annotations

import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from forge.core.invoker._lifecycle import (
    ParseHints,
    _HeadlessLifecycleBase,
    _Identity,
    _status,
    run_grouped_parallel,
)
from forge.core.invoker.types import HeadlessRequest, HeadlessResult


class _TestInvoker(_HeadlessLifecycleBase):
    def __init__(self, runtime: str) -> None:
        self.runtime = runtime
        self.emitted: list[HeadlessResult] = []

    def _prepare_argv(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        return [self.runtime, request.label or ""], ParseHints()

    def _build_result(
        self,
        request: HeadlessRequest,
        *,
        stdout: str,
        stderr: str,
        returncode: int,
        duration_seconds: float,
        ident: _Identity,
        hints: ParseHints,
    ) -> HeadlessResult:
        return HeadlessResult(
            label=request.label,
            stdout=f"{self.runtime}:{stdout}",
            stderr=stderr,
            returncode=returncode,
            duration_seconds=duration_seconds,
            **ident,
        )

    def _emit(self, request: HeadlessRequest, result: HeadlessResult) -> None:
        self.emitted.append(result)

    def _missing_binary_error(self) -> str:
        return f"{self.runtime} missing"


def _request(label: str) -> HeadlessRequest:
    return HeadlessRequest(argv=[], prompt=f"prompt-{label}", env={}, label=label, output_format=None)


def _proc(stdout: str, *, returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.communicate.return_value = (stdout, "")
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 1000
    proc.wait.return_value = returncode
    return proc


class TestGroupedParallel:
    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_uses_each_paired_invoker_hooks_and_preserves_input_order(self, mock_popen):
        claude = _TestInvoker("claude")
        codex = _TestInvoker("codex")

        def make_proc(argv, **_kwargs):
            return _proc(f"raw-{argv[1]}")

        mock_popen.side_effect = make_proc
        jobs = [
            (claude, _request("c0")),
            (codex, _request("x0")),
            (claude, _request("c1")),
            (codex, _request("x1")),
        ]

        results = run_grouped_parallel(jobs)

        assert [result.label for result in results] == ["c0", "x0", "c1", "x1"]
        assert [result.stdout for result in results] == [
            "claude:raw-c0",
            "codex:raw-x0",
            "claude:raw-c1",
            "codex:raw-x1",
        ]
        assert [result.label for result in claude.emitted] == ["c0", "c1"]
        assert [result.label for result in codex.emitted] == ["x0", "x1"]

    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    @patch("forge.core.invoker._lifecycle.ThreadPoolExecutor", wraps=ThreadPoolExecutor)
    def test_global_concurrency_is_capped_at_five_across_runtimes(self, mock_executor, mock_popen):
        claude = _TestInvoker("claude")
        codex = _TestInvoker("codex")
        lock = threading.Lock()
        release = threading.Event()
        live = 0
        max_live = 0

        def make_proc(argv, **_kwargs):
            proc = _proc(f"raw-{argv[1]}")

            def communicate(**_communicate_kwargs):
                nonlocal live, max_live
                with lock:
                    live += 1
                    max_live = max(max_live, live)
                    if live == 5:
                        release.set()
                assert release.wait(timeout=5)
                with lock:
                    live -= 1
                return (f"raw-{argv[1]}", "")

            proc.communicate.side_effect = communicate
            return proc

        mock_popen.side_effect = make_proc
        jobs = [
            (claude if idx % 2 == 0 else codex, _request(f"w{idx}"))
            for idx in range(8)
        ]

        results = run_grouped_parallel(jobs)

        assert len(results) == 8
        assert mock_executor.call_args.kwargs["max_workers"] == 5
        assert max_live == 5

    @patch("forge.core.invoker._lifecycle.os.getpgid", side_effect=lambda pid: pid)
    @patch("forge.core.invoker._lifecycle.os.killpg")
    @patch("forge.core.invoker._lifecycle.subprocess.Popen")
    def test_interrupt_reaps_both_runtimes_and_suppresses_never_started_emission(
        self,
        mock_popen,
        mock_killpg,
        _mock_getpgid,
    ):
        claude = _TestInvoker("claude")
        codex = _TestInvoker("codex")
        registered = 0
        registered_lock = threading.Lock()
        five_registered = threading.Event()
        release = threading.Event()
        watchdog_fired = threading.Event()
        next_pid = 2000

        def make_proc(_argv, **_kwargs):
            nonlocal next_pid
            proc = _proc("killed", returncode=-signal.SIGTERM)
            proc.pid = next_pid
            next_pid += 1
            proc.poll.return_value = None

            def communicate(**_communicate_kwargs):
                nonlocal registered
                with registered_lock:
                    registered += 1
                    if registered == 5:
                        five_registered.set()
                assert release.wait(timeout=5)
                return ("killed", "")

            proc.communicate.side_effect = communicate
            return proc

        mock_popen.side_effect = make_proc
        mock_killpg.side_effect = lambda _pgid, _sig: release.set()

        def fake_as_completed(_futures):
            assert five_registered.wait(timeout=5)
            raise KeyboardInterrupt

        def watchdog() -> None:
            if not release.wait(timeout=2):
                watchdog_fired.set()
                release.set()

        watcher = threading.Thread(target=watchdog, daemon=True)
        watcher.start()
        jobs = [
            (claude if idx % 2 == 0 else codex, _request(f"w{idx}"))
            for idx in range(6)
        ]
        try:
            with patch("forge.core.invoker._lifecycle.as_completed", fake_as_completed):
                with pytest.raises(KeyboardInterrupt):
                    run_grouped_parallel(jobs)
        finally:
            release.set()
            watcher.join(timeout=2)

        emitted = [*claude.emitted, *codex.emitted]
        assert mock_popen.call_count == 5
        assert len(emitted) == 5
        assert all(result.cancelled is False and _status(result) == "error" for result in emitted)
        assert mock_killpg.call_count >= 5
        assert not watchdog_fired.is_set()
