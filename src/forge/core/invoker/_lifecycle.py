"""Shared headless subprocess lifecycle (Phase 5b).

The ``run``/``run_parallel`` machinery is **runtime-neutral**: per-job process
groups (``start_new_session=True``) so ``os.killpg`` reaps orphans on timeout or
interrupt, ``SIGTERM`` -> wait -> ``SIGKILL`` cleanup, a 5-wide ``ThreadPoolExecutor``
with ``result_map[idx]`` input-order results, and the two cancellation TOCTOU races
(cleanup vs. spawn/register). This base owns all of it; per-runtime differences live
behind six template hooks:

- :meth:`_prepare_argv`              -- build the launch argv + opaque parse hints.
- :meth:`_build_result`             -- turn a completed run into a ``HeadlessResult``.
- :meth:`_emit`                     -- emit a usage event (opt-in on attribution).
- :meth:`_is_recoverable_format_rejection` -- did the CLI reject a format flag we can retry without?
- :meth:`_on_format_rejection`      -- mark the format unsupported; return the fallback argv + hints.
- :meth:`_missing_binary_error`     -- the "<cli> not found in PATH" message.

The format-retry *spawn* machinery (re-launching a tracked child so cleanup still
covers it) stays in this base; only the predicate and the fallback derivation are
hooks. A runtime whose ``_is_recoverable_format_rejection`` always returns ``False``
(Codex) never enters that branch, so it needs no ``_on_format_rejection``.

The invoker never raises: spawn-level failures (missing binary, OS error) land in
``HeadlessResult.error``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TypedDict, cast

from forge.core.invoker.types import Attribution, HeadlessRequest, HeadlessResult
from forge.core.reactive.env import (
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
)


@dataclass(frozen=True)
class ParseHints:
    """Opaque per-call parse context: produced by :meth:`_prepare_argv`, consumed by
    :meth:`_build_result` and :meth:`_is_recoverable_format_rejection`.

    The base passes it through without inspecting it; each runtime sets the field it
    needs (Claude: ``json_requested``; Codex: ``is_jsonl_stream``).
    """

    json_requested: bool = False
    is_jsonl_stream: bool = False


class _Identity(TypedDict):
    """The three run-tree identity fields, typed so ``**ident`` unpacks cleanly
    into ``HeadlessResult`` (mypy knows the exact keys, not arbitrary str keys)."""

    run_id: str | None
    parent_run_id: str | None
    root_run_id: str | None


def _identity(env: dict[str, str]) -> _Identity:
    """Read the run-tree identity stamped into ``env`` by the env builder."""
    return {
        "run_id": env.get(FORGE_RUN_ID_VAR),
        "parent_run_id": env.get(FORGE_PARENT_RUN_ID_VAR),
        "root_run_id": env.get(FORGE_ROOT_RUN_ID_VAR),
    }


def _status(result: HeadlessResult) -> str:
    """Map a result to a usage-event status string.

    A runtime-reported error (``runtime_is_error`` with exit 0) reads as ``error`` --
    the run did not succeed even though the process exited cleanly.
    """
    if result.timed_out:
        return "timeout"
    if not result.success:
        return "error"
    return "error" if result.runtime_is_error else "success"


def _worker_reason_code(result: HeadlessResult) -> str | None:
    """Classify a non-success run for the upstream row's ``reason_code``."""
    if result.timed_out:
        return "timeout"
    if result.error:
        return "subprocess_error"
    if result.runtime_is_error:
        return "runtime_reported_error"
    if result.returncode != 0:
        return f"exit_{result.returncode}"
    return None


def _record_worker_upstream(attribution: Attribution, result: HeadlessResult, status: str) -> None:
    """Record the per-worker upstream operation row (shared by the Claude + Codex invokers).

    ``operation=None`` suppresses the row (parity with arms whose only upstream outcome is
    the engine's ``policy.evaluate``); the usage event emitted by the caller stays.
    """
    if attribution.operation is None:
        return
    from forge.core.telemetry.upstream import UpstreamStatus, record_upstream_operation

    record_upstream_operation(
        command=attribution.command,
        operation=attribution.operation,
        status=cast(UpstreamStatus, status),
        session=attribution.session,
        run_id=result.run_id,
        parent_run_id=result.parent_run_id,
        root_run_id=result.root_run_id,
        reason_code=_worker_reason_code(result),
        message=None if status == "success" else result.error or result.stderr[:200] or None,
        latency_ms=round(result.duration_seconds * 1000, 1) if result.duration_seconds else None,
    )


def _terminate_and_reap(procs: list[subprocess.Popen[str]]) -> None:
    """Terminate and reap the given children. SIGTERM -> wait -> SIGKILL."""
    for proc in procs:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass
    for proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=2)
            except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass


class _HeadlessLifecycleBase:
    """Runtime-neutral ``run``/``run_parallel`` lifecycle. Subclasses fill the hooks."""

    # --- template hooks (subclasses override) ---------------------------------

    def _prepare_argv(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        """Return the launch argv and opaque parse hints for this request."""
        raise NotImplementedError

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
        """Build a :class:`HeadlessResult` from a completed run."""
        raise NotImplementedError

    def _emit(self, request: HeadlessRequest, result: HeadlessResult) -> None:
        """Emit a usage event for the run (opt-in on ``request.attribution``)."""
        raise NotImplementedError

    def _is_recoverable_format_rejection(self, returncode: int, stderr: str, hints: ParseHints) -> bool:
        """True iff the CLI rejected a format flag we can retry without (Claude only)."""
        return False

    def _on_format_rejection(self, request: HeadlessRequest) -> tuple[list[str], ParseHints]:
        """Mark the format unsupported; return the fallback argv + hints.

        Only reached when :meth:`_is_recoverable_format_rejection` returns ``True``.
        """
        raise NotImplementedError

    def _missing_binary_error(self) -> str:
        """The ``"<cli> not found in PATH"`` message for a ``FileNotFoundError``."""
        raise NotImplementedError

    # --- lifecycle (shared) ---------------------------------------------------

    def run(self, request: HeadlessRequest) -> HeadlessResult:
        """Run one already-shaped job single-shot.

        The request's ``argv``/``env`` are pre-built by the caller; this is a pure
        runner (no routing). Captures stdout/stderr and never raises. Like the
        parallel path, the child runs in its own process group so timeouts reap
        tool subprocesses spawned by the runtime.
        """
        start = time.monotonic()
        ident = _identity(request.env)
        run_argv, hints = self._prepare_argv(request)
        proc: subprocess.Popen[str] | None = None
        try:
            proc = subprocess.Popen(
                run_argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=request.cwd,
                env=request.env,
                start_new_session=True,
            )
            stdout, stderr = proc.communicate(input=request.prompt, timeout=request.timeout_seconds)
            returncode = proc.returncode if proc.returncode is not None else -1
            # Retry-once backstop: a format flag passed the capability gate but the CLI rejected it.
            if self._is_recoverable_format_rejection(returncode, stderr, hints):
                run_argv, hints = self._on_format_rejection(request)
                proc = subprocess.Popen(
                    run_argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=request.cwd,
                    env=request.env,
                    start_new_session=True,
                )
                stdout, stderr = proc.communicate(input=request.prompt, timeout=request.timeout_seconds)
                returncode = proc.returncode if proc.returncode is not None else -1
            result = self._build_result(
                request,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                duration_seconds=time.monotonic() - start,
                ident=ident,
                hints=hints,
            )
        except subprocess.TimeoutExpired:
            if proc is not None:
                _terminate_and_reap([proc])
            result = HeadlessResult(
                label=request.label,
                stdout="",
                stderr="",
                returncode=-1,
                duration_seconds=time.monotonic() - start,
                timed_out=True,
                **ident,
            )
        except FileNotFoundError:
            result = HeadlessResult(
                label=request.label,
                stdout="",
                stderr="",
                returncode=-1,
                duration_seconds=time.monotonic() - start,
                error=self._missing_binary_error(),
                **ident,
            )
        except Exception as e:
            result = HeadlessResult(
                label=request.label,
                stdout="",
                stderr="",
                returncode=-1,
                duration_seconds=time.monotonic() - start,
                error=str(e),
                **ident,
            )
        self._emit(request, result)
        return result

    def run_parallel(self, requests: list[HeadlessRequest]) -> list[HeadlessResult]:
        """Run jobs concurrently; return results in input order.

        Per-job process groups, SIGTERM->SIGKILL cleanup, a 5-wide thread pool, and
        ``result_map[idx]`` ordering. Cancellation (KeyboardInterrupt mid-fan-out)
        SIGTERMs children before the executor join.
        """
        if not requests:
            return []

        # Thread-safe child tracking. cleanup_started closes cancellation races where
        # a worker is about to spawn, or has spawned but not yet registered, a child.
        children: list[subprocess.Popen[str]] = []
        children_lock = threading.Lock()
        cleanup_started = False

        def _cleanup() -> None:
            """Mark cancellation, then terminate every child registered so far."""
            nonlocal cleanup_started
            with children_lock:
                cleanup_started = True
                snapshot = list(children)
            _terminate_and_reap(snapshot)

        def _run_one(request: HeadlessRequest) -> HeadlessResult:
            start = time.monotonic()
            ident = _identity(request.env)
            run_argv, hints = self._prepare_argv(request)
            proc: subprocess.Popen[str] | None = None
            try:
                with children_lock:
                    if cleanup_started:
                        return HeadlessResult(
                            label=request.label,
                            stdout="",
                            stderr="",
                            returncode=-1,
                            duration_seconds=time.monotonic() - start,
                            error="cancelled",
                            cancelled=True,
                            **ident,
                        )

                proc = subprocess.Popen(
                    run_argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=request.cwd,
                    env=request.env,
                    start_new_session=True,
                )
                with children_lock:
                    children.append(proc)
                    should_cancel = cleanup_started

                if should_cancel:
                    # Cleanup may have started after Popen returned but before the child
                    # was registered in `children`. In that race, the worker owns reaping
                    # its just-spawned process so shutdown(wait=True) cannot hang on it.
                    _terminate_and_reap([proc])
                    result = HeadlessResult(
                        label=request.label,
                        stdout="",
                        stderr="",
                        returncode=proc.returncode if proc.returncode is not None else -1,
                        duration_seconds=time.monotonic() - start,
                        error="cancelled",
                        cancelled=True,
                        **ident,
                    )
                else:
                    stdout, stderr = proc.communicate(input=request.prompt, timeout=request.timeout_seconds)
                    returncode = proc.returncode if proc.returncode is not None else -1
                    # Retry-once backstop: format flag rejected despite the capability latch. The
                    # original process already exited; spawn the unflagged retry as a TRACKED child
                    # (own process group + registered in `children`, with `proc` reassigned to it)
                    # so the SIGTERM->SIGKILL cleanup and timeout handler below cover it too -- a
                    # plain subprocess.run here would be unterminable on cancellation and could hang
                    # shutdown for up to timeout_seconds.
                    if self._is_recoverable_format_rejection(returncode, stderr, hints):
                        retry_argv, hints = self._on_format_rejection(request)
                        proc = subprocess.Popen(
                            retry_argv,
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            cwd=request.cwd,
                            env=request.env,
                            start_new_session=True,
                        )
                        with children_lock:
                            children.append(proc)
                            retry_should_cancel = cleanup_started
                        if retry_should_cancel:
                            # Same race as the primary spawn (above): _cleanup() takes a
                            # one-shot snapshot of `children`, so if it ran between this
                            # retry Popen returning and the append above, the retry child
                            # is not in that snapshot. The worker reaps it here -- otherwise
                            # shutdown(wait=True) blocks on its communicate() for up to
                            # timeout_seconds, the exact hang the tracked-child design prevents.
                            _terminate_and_reap([proc])
                            return HeadlessResult(
                                label=request.label,
                                stdout="",
                                stderr="",
                                returncode=proc.returncode if proc.returncode is not None else -1,
                                duration_seconds=time.monotonic() - start,
                                error="cancelled",
                                cancelled=True,
                                **ident,
                            )
                        stdout, stderr = proc.communicate(input=request.prompt, timeout=request.timeout_seconds)
                        returncode = proc.returncode if proc.returncode is not None else -1
                    result = self._build_result(
                        request,
                        stdout=stdout,
                        stderr=stderr,
                        returncode=returncode,
                        duration_seconds=time.monotonic() - start,
                        ident=ident,
                        hints=hints,
                    )
            except subprocess.TimeoutExpired:
                try:
                    if proc is not None:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                        proc.wait(timeout=5)
                except (OSError, ProcessLookupError, subprocess.TimeoutExpired):
                    pass
                result = HeadlessResult(
                    label=request.label,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    duration_seconds=time.monotonic() - start,
                    timed_out=True,
                    **ident,
                )
            except FileNotFoundError:
                result = HeadlessResult(
                    label=request.label,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    duration_seconds=time.monotonic() - start,
                    error=self._missing_binary_error(),
                    **ident,
                )
            except (OSError, subprocess.SubprocessError) as e:
                result = HeadlessResult(
                    label=request.label,
                    stdout="",
                    stderr="",
                    returncode=-1,
                    duration_seconds=time.monotonic() - start,
                    error=str(e),
                    **ident,
                )
            self._emit(request, result)
            return result

        result_map: dict[int, HeadlessResult] = {}
        max_workers = min(len(requests), 5)
        # Manage the executor manually (no `with`) so cleanup runs in the right order on
        # cancellation. `with ThreadPoolExecutor(...)` calls shutdown(wait=True) on __exit__
        # -- BEFORE an outer finally -- which blocks until every worker drains its blocking
        # communicate() (up to timeout_seconds). On a KeyboardInterrupt or main-thread error
        # mid-loop we must instead SIGTERM the children FIRST (so communicate() returns
        # promptly), then join. Normal path: every child already exited, so _cleanup() is a
        # no-op and shutdown joins instantly.
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_idx = {executor.submit(_run_one, req): idx for idx, req in enumerate(requests)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result_map[idx] = future.result()
                except Exception as e:
                    result_map[idx] = HeadlessResult(
                        label=requests[idx].label,
                        stdout="",
                        stderr="",
                        returncode=-1,
                        duration_seconds=0.0,
                        error=f"Thread error: {e}",
                    )
        finally:
            try:
                _cleanup()  # kill running children first (prompt cancellation)
            finally:
                executor.shutdown(wait=True, cancel_futures=True)  # always join workers (never leak threads)

        return [result_map[idx] for idx in range(len(requests)) if idx in result_map]
