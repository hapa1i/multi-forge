"""Claude headless invoker (Phase 4d).

Owns the ``claude -p`` subprocess lifecycle for single-shot (:meth:`run`) and
parallel fan-out (:meth:`run_parallel`). The parallel path is the review engine's
lifecycle, extracted verbatim:

- each job runs in its own process group (``start_new_session=True``) so
  ``os.killpg`` can reap orphans on interrupt or timeout;
- ``ThreadPoolExecutor(max_workers=min(N, 5))`` with a ``result_map[idx]`` so
  output is in deterministic input order regardless of completion order;
- per-job ``communicate(timeout=...)``; ``SIGTERM`` -> wait -> ``SIGKILL`` cleanup
  in a ``finally``.

Run-tree identity (stamped into each job's ``env`` by ``build_claude_env``) is
surfaced onto the result; when a job carries :class:`Attribution`, a per-job
``UsageEvent`` is emitted (granularity ``worker``, cost null -- the verb aggregate
holds the estimated total). The invoker never raises: spawn-level failures land in
``HeadlessResult.error``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypedDict

from forge.core.invoker.types import HeadlessRequest, HeadlessResult
from forge.core.reactive.env import (
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
)


class _Identity(TypedDict):
    """The three run-tree identity fields, typed so ``**ident`` unpacks cleanly
    into ``HeadlessResult`` (mypy knows the exact keys, not arbitrary str keys)."""

    run_id: str | None
    parent_run_id: str | None
    root_run_id: str | None


def _identity(env: dict[str, str]) -> _Identity:
    """Read the run-tree identity ``build_claude_env`` stamped into ``env``."""
    return {
        "run_id": env.get(FORGE_RUN_ID_VAR),
        "parent_run_id": env.get(FORGE_PARENT_RUN_ID_VAR),
        "root_run_id": env.get(FORGE_ROOT_RUN_ID_VAR),
    }


def _status(result: HeadlessResult) -> str:
    """Map a result to a usage-event status string."""
    if result.timed_out:
        return "timeout"
    return "success" if result.success else "error"


class ClaudeHeadlessInvoker:
    """Runs ``claude -p`` jobs. Implements the :class:`HeadlessInvoker` protocol."""

    def run(self, request: HeadlessRequest) -> HeadlessResult:
        """Run one already-shaped job single-shot (mirrors ``run_claude_session``).

        The request's ``argv``/``env`` are pre-built by the caller; this is a pure
        runner (no ``--bare``/proxy arg-building -- that stays in the caller, e.g.
        ``run_claude_session``). Captures stdout/stderr and never raises.
        """
        start = time.monotonic()
        ident = _identity(request.env)
        try:
            completed = subprocess.run(
                request.argv,
                input=request.prompt,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                cwd=request.cwd,
                env=request.env,
            )
            result = HeadlessResult(
                label=request.label,
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                duration_seconds=time.monotonic() - start,
                **ident,
            )
        except subprocess.TimeoutExpired:
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
                error="claude CLI not found in PATH",
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
        _emit_worker(request, result)
        return result

    def run_parallel(self, requests: list[HeadlessRequest]) -> list[HeadlessResult]:
        """Run jobs concurrently; return results in input order.

        Absorbs the review-engine lifecycle: per-job process groups, SIGTERM->
        SIGKILL cleanup, a 5-wide thread pool, and ``result_map[idx]`` ordering.
        """
        if not requests:
            return []

        # Thread-safe child tracking. cleanup_started closes cancellation races where
        # a worker is about to spawn, or has spawned but not yet registered, a child.
        children: list[subprocess.Popen[str]] = []
        children_lock = threading.Lock()
        cleanup_started = False

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
                    request.argv,
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
                    result = HeadlessResult(
                        label=request.label,
                        stdout=stdout,
                        stderr=stderr,
                        returncode=proc.returncode,
                        duration_seconds=time.monotonic() - start,
                        **ident,
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
                    error="claude CLI not found in PATH",
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
            _emit_worker(request, result)
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


def _emit_worker(request: HeadlessRequest, result: HeadlessResult) -> None:
    """Emit a per-worker UsageEvent when the request carries attribution.

    Opt-in (no attribution -> no event), so non-workflow callers of ``run_parallel``
    don't suddenly write to the ledger. No identity -> nothing to attribute. A
    cancelled job did no attributable work, so it is not recorded either.
    """
    attribution = request.attribution
    if attribution is None or not result.run_id or result.cancelled:
        return
    from forge.core.usage import emit_worker_usage

    emit_worker_usage(
        run_id=result.run_id,
        parent_run_id=result.parent_run_id,
        root_run_id=result.root_run_id,
        command=attribution.command,
        workflow=attribution.workflow,
        session=attribution.session,
        runtime=attribution.runtime,
        model=request.model,
        provider=request.provider,
        proxy_id=request.proxy_id,
        status=_status(result),
        latency_ms=round(result.duration_seconds * 1000, 1) if result.duration_seconds else None,
    )
