"""Verification policy logic for the Stop hook (Ralph-Wiggum pattern)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from forge.core.state import now_iso, parse_iso
from forge.session import SessionStore, set_override
from forge.session.effective import compute_effective_intent
from forge.session.models import SessionState, VerificationConfig, VerificationConfirmed
from forge.session.store import HOOK_LOCK_TIMEOUT_S


def _check_completion_promise(ver: "VerificationConfig", transcript_path: Path) -> tuple[bool | None, str | None]:
    """Check if promise appears on standalone line in last assistant message.

    Returns:
        (True, None): Verification passed
        (False, error): Verification failed
        (None, None): Skip (misconfiguration - no persistence needed)
    """
    if not ver.promise:
        return (None, None)  # No promise configured = skip

    if "\n" in ver.promise:
        return (None, None)  # Multi-line promises not supported = skip

    last_text = _get_last_assistant_text_for_verification(transcript_path)
    promise_stripped = ver.promise.strip()

    if last_text is not None:
        for line in last_text.splitlines():
            if line.strip() == promise_stripped:
                return (True, None)  # Passed

    return (False, f"Promise not found: {ver.promise}")


def _check_test_suite(ver: "VerificationConfig") -> tuple[bool | None, str | None]:
    """Run test suite and return (passed, error_message).

    Command is fixed: ["uv", "run", "pytest"]
    No shell=True, no user-configurable command.

    Returns:
        (True, None): Tests passed
        (False, error): Tests failed
        (None, None): Skip (infrastructure issue - no persistence needed)
    """
    import subprocess

    cmd = ["uv", "run", "pytest"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=ver.test_timeout_seconds,
            cwd=Path.cwd(),
        )
        if result.returncode == 0:
            return (True, None)
        else:
            # Include stderr snippet for debugging
            stderr_snippet = result.stderr.decode("utf-8", errors="replace")[:200]
            return (False, f"Tests failed (exit {result.returncode}): {stderr_snippet}")
    except subprocess.TimeoutExpired:
        return (False, f"timeout: {ver.test_timeout_seconds} seconds")
    except FileNotFoundError:
        # uv not found = misconfiguration, skip with warning (same as missing promise)
        click.echo("Warning: uv not found - skipping test_suite verification", err=True)
        return (None, None)
    except Exception as e:
        # Other errors = fail-open with warning
        click.echo(f"Warning: test_suite execution error: {e}", err=True)
        return (None, None)


def _run_verification_check(
    *,
    store: SessionStore,
    manifest: SessionState,
    transcript_path: Path,
) -> tuple[bool, str | None]:
    """Run verification check on Stop (Ralph-Wiggum pattern).

    Supports two verification types:
    - completion_promise: Check if last assistant message contains expected promise
    - test_suite: Run `uv run pytest` and check exit code

    Both types share escape hatch logic (max_iterations, max_minutes, bypass).

    Args:
        store: SessionStore for persisting verification state.
        manifest: Current session manifest.
        transcript_path: Path to the transcript file (for completion_promise type).

    Returns:
        Tuple of (should_allow_stop, block_message_or_none).
        If should_allow_stop is False, block_message contains the stderr message.
    """
    from datetime import UTC, datetime

    try:
        effective = compute_effective_intent(manifest)
    except Exception as e:
        print(
            f"[forge] Verification check: cannot compute effective intent: {e}",
            file=sys.stderr,
        )
        return (True, None)

    ver = effective.verification
    if ver is None:
        return (True, None)

    if ver.bypass:
        return (True, None)

    if ver.on_incomplete == "allow":  # applies to both verification types
        return (True, None)

    if ver.type == "test_suite":
        passed, check_error = _check_test_suite(ver)
    elif ver.type == "completion_promise":
        passed, check_error = _check_completion_promise(ver, transcript_path)
    else:
        # Unknown verification type = skip
        return (True, None)

    # passed=None means misconfiguration/infra issue; skip without persisting state
    if passed is None:
        return (True, None)

    # Persist verification state
    def _persist_verification(
        m: object,
        *,
        result: str,
        error: str | None = None,
        increment_iterations: bool = False,
        set_started_at: bool = False,
        auto_bypass: bool = False,
    ) -> None:
        if not isinstance(m, SessionState):
            return

        if m.confirmed.verification is None:
            m.confirmed.verification = VerificationConfirmed()

        m.confirmed.verification.last_result = result
        m.confirmed.verification.last_error = error[:200] if error else None

        if set_started_at and m.confirmed.verification.started_at is None:
            m.confirmed.verification.started_at = now_iso()

        if increment_iterations:
            m.confirmed.verification.iterations += 1

        if auto_bypass:
            set_override(m.overrides, "verification.bypass", True)

        m.confirmed.confirmed_at = now_iso()
        m.confirmed.confirmed_by = "hook:stop:verification"

    if passed:
        try:
            store.update(
                timeout_s=HOOK_LOCK_TIMEOUT_S,
                mutate=lambda m: _persist_verification(m, result="passed"),
            )
        except Exception as e:
            print(f"[forge] Verification state persistence failed: {e}", file=sys.stderr)
        return (True, None)

    if ver.on_incomplete == "warn":
        try:
            store.update(
                timeout_s=HOOK_LOCK_TIMEOUT_S,
                mutate=lambda m: _persist_verification(m, result="warned", error=check_error),
            )
        except Exception as e:
            print(f"[forge] Verification state persistence failed: {e}", file=sys.stderr)
        click.echo(
            f"Warning: Verification incomplete - {check_error}",
            err=True,
        )
        return (True, None)

    # on_incomplete == "block" - check escape hatches before blocking
    current_iterations = 0
    started_at: str | None = None
    if manifest.confirmed.verification:
        current_iterations = manifest.confirmed.verification.iterations
        started_at = manifest.confirmed.verification.started_at

    # current_iterations + 1 is the count after this block executes
    if current_iterations + 1 > ver.max_iterations:
        try:
            store.update(
                timeout_s=HOOK_LOCK_TIMEOUT_S,
                mutate=lambda m: _persist_verification(
                    m,
                    result="max_iterations",
                    error=f"Exceeded {ver.max_iterations} iterations",
                    auto_bypass=True,
                ),
            )
        except Exception as e:
            print(f"[forge] Verification state persistence failed: {e}", file=sys.stderr)
        click.echo(
            f"Verification auto-bypassed: exceeded max_iterations ({ver.max_iterations}).",
            err=True,
        )
        return (True, None)

    if ver.max_minutes is not None and started_at is not None:
        try:
            start_dt = parse_iso(started_at)
            now_dt = datetime.now(UTC)
            elapsed_minutes = (now_dt - start_dt).total_seconds() / 60
            if elapsed_minutes > ver.max_minutes:
                store.update(
                    timeout_s=HOOK_LOCK_TIMEOUT_S,
                    mutate=lambda m: _persist_verification(
                        m,
                        result="max_minutes",
                        error=f"Exceeded {ver.max_minutes} minutes",
                        auto_bypass=True,
                    ),
                )
                click.echo(
                    f"Verification auto-bypassed: exceeded max_minutes ({ver.max_minutes}).",
                    err=True,
                )
                return (True, None)
        except Exception as e:
            print(f"[forge] Verification time check failed: {e}", file=sys.stderr)

    try:
        store.update(
            timeout_s=HOOK_LOCK_TIMEOUT_S,
            mutate=lambda m: _persist_verification(
                m,
                result="failed",
                error=check_error,
                increment_iterations=True,
                set_started_at=True,
            ),
        )
    except Exception as e:
        print(f"[forge] Verification state persistence failed: {e}", file=sys.stderr)

    if ver.re_inject_prompt:
        block_message = ver.re_inject_prompt
    elif ver.type == "test_suite":
        block_message = (
            f"Verification incomplete: tests did not pass.\n"
            f"Error: {check_error}\n\n"
            f"Fix the failing tests and try again.\n"
            f"Escape hatches:\n"
            f"  - Type: %cancel-verification\n"
            f"  - Or run: forge session set verification.bypass true"
        )
    else:
        block_message = (
            f"Verification incomplete: expected completion promise not found.\n"
            f"Expected: {ver.promise}\n"
            f"(must appear on its own line in the assistant's response)\n\n"
            f"Continue working and output the completion promise when done.\n"
            f"Escape hatches:\n"
            f"  - Type: %cancel-verification\n"
            f"  - Or run: forge session set verification.bypass true"
        )

    return (False, block_message)


def _get_last_assistant_text_for_verification(
    transcript_path: str | Path,
) -> str | None:
    """Extract text from the most recent assistant message for verification.

    This is used by the verification policy to check if the completion promise
    is present in the last assistant response.

    Uses timestamp-based ordering to get the truly last assistant message.

    Supports two transcript formats:
    1. requestId/message.role format (newer Claude Code versions)
    2. entry.type == "assistant" format (older format)

    Returns:
        The text content of the last assistant message, or None if not found.
    """
    path = Path(transcript_path) if isinstance(transcript_path, str) else transcript_path

    if not path.is_file():
        return None

    latest_text: str | None = None
    latest_ts: str = ""

    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Format 1: requestId/message.role format
                message = entry.get("message")
                if isinstance(message, dict) and message.get("role") == "assistant":
                    ts = entry.get("timestamp", "")
                    if not isinstance(ts, str):
                        ts = ""

                    content = message.get("content")
                    if isinstance(content, list):
                        texts: list[str] = []
                        for block in content:
                            if isinstance(block, dict):
                                t = block.get("text")
                                if isinstance(t, str) and t:
                                    texts.append(t)
                        if texts:
                            joined = "".join(texts)
                            if ts >= latest_ts:
                                latest_ts = ts
                                latest_text = joined
                    continue

                # Format 2: entry.type == "assistant" format
                if entry.get("type") == "assistant":
                    ts = entry.get("timestamp", "")
                    if not isinstance(ts, str):
                        ts = ""

                    message = entry.get("message")
                    if not isinstance(message, dict):
                        continue

                    content = message.get("content")
                    if not isinstance(content, list):
                        continue

                    texts = []
                    for block in content:
                        if isinstance(block, dict):
                            t = block.get("text")
                            if isinstance(t, str) and t:
                                texts.append(t)

                    if texts:
                        joined = "".join(texts)
                        if ts >= latest_ts:
                            latest_ts = ts
                            latest_text = joined

    except Exception:
        pass

    return latest_text
