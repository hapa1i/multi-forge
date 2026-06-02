"""Tests for ClaudeHeadlessInvoker (Phase 4d).

The invoker owns the ``claude -p`` lifecycle extracted from the review engine:
ordered fan-out, per-job process groups + SIGTERM cleanup, single-shot parity,
run-tree identity surfacing, and opt-in per-worker usage emission. Subprocess is
always mocked; the autouse ``isolate_forge_home`` fixture gives a clean ledger.
"""

from __future__ import annotations

import signal
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from forge.core.invoker import Attribution, ClaudeHeadlessInvoker, HeadlessRequest
from forge.core.usage.ledger import read_usage_events


def _req(
    *,
    label: str = "w0",
    env: dict[str, str] | None = None,
    prompt: str = "p",
    model: str | None = None,
    provider: str | None = None,
    proxy_id: str | None = None,
    attribution: Attribution | None = None,
    timeout: int = 600,
) -> HeadlessRequest:
    return HeadlessRequest(
        argv=["claude", "-p"],
        prompt=prompt,
        env=env if env is not None else {},
        cwd=None,
        timeout_seconds=timeout,
        label=label,
        model=model,
        provider=provider,
        proxy_id=proxy_id,
        attribution=attribution,
    )


def _mock_proc(stdout: str = "out", returncode: int = 0, stderr: str = "", *, communicate_side_effect=None):
    proc = MagicMock()
    if communicate_side_effect is not None:
        proc.communicate.side_effect = communicate_side_effect
    else:
        proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.poll.return_value = returncode
    proc.pid = 12345
    proc.wait.return_value = returncode
    return proc


_IDENT = {"FORGE_RUN_ID": "run_w", "FORGE_PARENT_RUN_ID": "run_verb", "FORGE_ROOT_RUN_ID": "run_root"}


class TestRunParallel:
    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_empty_returns_empty_without_spawning(self, mock_popen):
        assert ClaudeHeadlessInvoker().run_parallel([]) == []
        mock_popen.assert_not_called()

    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_results_in_input_order(self, mock_popen):
        # Distinct proc per spawn; completion order is nondeterministic across threads,
        # so assert input-order labels (the result_map[idx] guarantee) + that every
        # output is present (placed at the right index).
        mock_popen.side_effect = [_mock_proc(f"out-{i}") for i in range(4)]
        out = ClaudeHeadlessInvoker().run_parallel([_req(label=f"w{i}") for i in range(4)])
        assert [r.label for r in out] == [f"w{i}" for i in range(4)]
        assert {r.stdout for r in out} == {f"out-{i}" for i in range(4)}

    @patch("forge.core.invoker.claude.subprocess.Popen")
    @patch("forge.core.invoker.claude.ThreadPoolExecutor", wraps=ThreadPoolExecutor)
    def test_concurrency_capped_at_five(self, mock_tpe, mock_popen):
        mock_popen.return_value = _mock_proc("out")
        ClaudeHeadlessInvoker().run_parallel([_req(label=f"w{i}") for i in range(7)])
        assert mock_tpe.call_args.kwargs["max_workers"] == 5

    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_run_id_surfaced_from_env(self, mock_popen):
        mock_popen.return_value = _mock_proc("out")
        out = ClaudeHeadlessInvoker().run_parallel([_req(env=dict(_IDENT))])
        r = out[0]
        assert (r.run_id, r.parent_run_id, r.root_run_id) == ("run_w", "run_verb", "run_root")

    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_nonzero_exit_is_failure(self, mock_popen):
        mock_popen.return_value = _mock_proc("", returncode=1, stderr="boom")
        out = ClaudeHeadlessInvoker().run_parallel([_req()])
        assert out[0].success is False
        assert out[0].returncode == 1

    @patch("forge.core.invoker.claude.os.getpgid", return_value=999)
    @patch("forge.core.invoker.claude.os.killpg")
    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_timeout_kills_process_group(self, mock_popen, mock_killpg, _getpgid):
        proc = _mock_proc(communicate_side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=1))
        proc.poll.return_value = 0  # cleanup sees it exited; only the _run_one SIGTERM fires
        mock_popen.return_value = proc
        out = ClaudeHeadlessInvoker().run_parallel([_req(timeout=1)])
        assert out[0].timed_out is True and out[0].success is False
        assert any(call.args == (999, signal.SIGTERM) for call in mock_killpg.call_args_list)

    @patch("forge.core.invoker.claude.os.getpgid", return_value=777)
    @patch("forge.core.invoker.claude.os.killpg")
    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_cancellation_sigterms_children_before_join(self, mock_popen, mock_killpg, _getpgid):
        """On a main-thread cancellation (KeyboardInterrupt) mid-fan-out, children are
        SIGTERMed BEFORE the blocking executor join -- not after workers drain their
        per-worker timeout. Regression guard for the `with ThreadPoolExecutor` ordering
        trap (its __exit__ shutdown(wait=True) would otherwise run before cleanup).

        Deterministic: a 3-party barrier rendezvous (both workers registered + a faked
        ``as_completed`` that then raises) makes the cancellation happen while children
        are 'running'; ``os.killpg`` releases the blocked workers. A failsafe watchdog
        releases them too if killpg never fires -- so a regression can't hang forever, and
        ``watchdog_fired`` staying clear proves cleanup ran *before* the join.
        """
        registered = threading.Barrier(3, timeout=5)  # 2 workers + the faked as_completed
        release = threading.Event()
        killpg_happened = threading.Event()
        watchdog_fired = threading.Event()

        def killpg_side_effect(_pgid, _sig):
            release.set()  # _cleanup's SIGTERM "kills" the children -> communicate() returns
            killpg_happened.set()

        mock_killpg.side_effect = killpg_side_effect

        def make_proc(*_a, **_k):
            proc = _mock_proc()
            proc.poll.return_value = None  # still running until killed

            def blocking_communicate(*_ca, **_ck):
                registered.wait()  # this worker is registered + about to block
                release.wait(timeout=5)  # block until SIGTERM (or watchdog failsafe)
                return ("", "")

            proc.communicate.side_effect = blocking_communicate
            return proc

        mock_popen.side_effect = make_proc

        def fake_as_completed(_futs):
            registered.wait()  # both workers registered & blocked -> simulate Ctrl+C now
            raise KeyboardInterrupt

        def watchdog():
            if not killpg_happened.wait(timeout=2.0):
                release.set()
                watchdog_fired.set()

        wd = threading.Thread(target=watchdog, daemon=True)
        wd.start()
        try:
            with patch("forge.core.invoker.claude.as_completed", fake_as_completed):
                with pytest.raises(KeyboardInterrupt):
                    ClaudeHeadlessInvoker().run_parallel([_req(label="w0"), _req(label="w1")])
        finally:
            release.set()  # ensure nothing is left blocked
            wd.join(timeout=2)

        assert any(call.args == (777, signal.SIGTERM) for call in mock_killpg.call_args_list)
        assert not watchdog_fired.is_set()  # killpg, not the failsafe, unblocked the workers

    @patch("forge.core.invoker.claude.os.getpgid", return_value=888)
    @patch("forge.core.invoker.claude.os.killpg")
    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_cancellation_reaps_child_registered_after_cleanup(self, mock_popen, mock_killpg, _getpgid):
        """If cleanup starts while Popen is still returning, the worker reaps its child.

        This guards the narrow race where a process exists but has not yet been
        appended to the shared children list. Cleanup marks cancellation, sees no
        registered children, and the worker must kill the just-spawned child before
        entering communicate().
        """
        cleanup_lock_entered = threading.Event()
        popen_started = threading.Event()
        real_lock = threading.Lock()

        class ObservedLock:
            def __init__(self) -> None:
                self.entries = 0

            def __enter__(self):
                real_lock.acquire()
                self.entries += 1
                if self.entries == 2:
                    cleanup_lock_entered.set()
                return self

            def __exit__(self, *_exc) -> None:
                real_lock.release()

        proc = _mock_proc()
        proc.poll.return_value = None
        proc.communicate.side_effect = AssertionError("cancelled child should not communicate")

        def make_proc(*_a, **_k):
            popen_started.set()
            assert cleanup_lock_entered.wait(timeout=5)
            return proc

        mock_popen.side_effect = make_proc

        def fake_as_completed(_futs):
            assert popen_started.wait(timeout=5)
            raise KeyboardInterrupt

        observed_threading = SimpleNamespace(Lock=ObservedLock)
        try:
            with patch("forge.core.invoker.claude.threading", observed_threading):
                with patch("forge.core.invoker.claude.as_completed", fake_as_completed):
                    with pytest.raises(KeyboardInterrupt):
                        ClaudeHeadlessInvoker().run_parallel([_req(label="w0")])
        finally:
            cleanup_lock_entered.set()

        assert any(call.args == (888, signal.SIGTERM) for call in mock_killpg.call_args_list)
        proc.communicate.assert_not_called()


class TestRun:
    @patch("forge.core.invoker.claude.subprocess.run")
    def test_single_shot_success_surfaces_run_id(self, mock_run):
        mock_run.return_value = MagicMock(stdout="out", stderr="", returncode=0)
        out = ClaudeHeadlessInvoker().run(_req(env={"FORGE_RUN_ID": "run_s", "FORGE_ROOT_RUN_ID": "run_s"}))
        assert out.success and out.stdout == "out"
        assert out.run_id == "run_s"

    @patch("forge.core.invoker.claude.subprocess.run")
    def test_single_shot_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=1)
        out = ClaudeHeadlessInvoker().run(_req(timeout=1))
        assert out.timed_out is True and out.success is False

    @patch("forge.core.invoker.claude.subprocess.run")
    def test_single_shot_missing_binary(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        out = ClaudeHeadlessInvoker().run(_req())
        assert out.success is False and out.error == "claude CLI not found in PATH"


class TestPerWorkerEmission:
    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_attribution_emits_worker_event(self, mock_popen):
        mock_popen.return_value = _mock_proc("out")
        attr = Attribution(command="panel", workflow="panel", session="s1")
        ClaudeHeadlessInvoker().run_parallel(
            [
                _req(
                    env=dict(_IDENT),
                    model="openai/gpt-5.5",
                    provider="openrouter",
                    proxy_id="openrouter-openai",
                    attribution=attr,
                )
            ]
        )
        events = read_usage_events()
        assert len(events) == 1
        e = events[0]
        assert (e.command, e.run_id, e.parent_run_id, e.root_run_id) == ("panel", "run_w", "run_verb", "run_root")
        assert e.attribution_granularity == "worker"
        assert e.measurement_source == "unattributed"
        assert (e.status, e.workflow, e.session) == ("success", "panel", "s1")
        # records the actual routed model/provider/proxy, not a friendly catalog id
        assert (e.model, e.provider, e.proxy_id) == ("openai/gpt-5.5", "openrouter", "openrouter-openai")
        assert e.cost_micro_usd is None and e.input_tokens is None  # no per-worker cost

    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_no_attribution_no_event(self, mock_popen):
        mock_popen.return_value = _mock_proc("out")
        ClaudeHeadlessInvoker().run_parallel([_req(env=dict(_IDENT))])
        assert read_usage_events() == []

    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_failed_worker_emits_error_status(self, mock_popen):
        mock_popen.return_value = _mock_proc("", returncode=1, stderr="boom")
        ClaudeHeadlessInvoker().run_parallel([_req(env=dict(_IDENT), attribution=Attribution(command="panel"))])
        assert read_usage_events()[0].status == "error"

    @patch("forge.core.invoker.claude.subprocess.Popen")
    def test_one_event_per_worker(self, mock_popen):
        mock_popen.return_value = _mock_proc("out")
        attr = Attribution(command="panel")
        reqs = [_req(label=f"w{i}", env=dict(_IDENT, FORGE_RUN_ID=f"run_{i}"), attribution=attr) for i in range(3)]
        ClaudeHeadlessInvoker().run_parallel(reqs)
        assert {e.run_id for e in read_usage_events()} == {"run_0", "run_1", "run_2"}

    def test_cancelled_worker_emits_no_event(self):
        """A cancelled job did no attributable work, so it is not recorded even
        with attribution -- the verb-level aggregate still holds the estimated total."""
        from forge.core.invoker.claude import _emit_worker
        from forge.core.invoker.types import HeadlessResult

        cancelled = HeadlessResult(
            label="w0",
            stdout="",
            stderr="",
            returncode=-1,
            duration_seconds=0.01,
            error="cancelled",
            cancelled=True,
            run_id="run_w",
            parent_run_id="run_verb",
            root_run_id="run_root",
        )
        _emit_worker(_req(env=dict(_IDENT), attribution=Attribution(command="panel")), cancelled)
        assert read_usage_events() == []
