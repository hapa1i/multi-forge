"""Verification policy logic for the Stop hook (Ralph-Wiggum pattern)."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Literal

import click

from forge.core.credential_registry import CREDENTIALS
from forge.core.reactive.env import FORGE_SIDECAR_VAR
from forge.core.state import now_iso, parse_iso
from forge.session import SessionStore, set_override
from forge.session.effective import compute_effective_intent
from forge.session.models import SessionState, VerificationConfig, VerificationConfirmed
from forge.session.store import HOOK_LOCK_TIMEOUT_S
from forge.session.verification_config import (
    VERIFICATION_INCOMPLETE_MODES,
    VERIFICATION_TYPES,
)

_logger = logging.getLogger(__name__)
_MAX_DIAGNOSTIC_CHARS = 200
_FORGE_OVERHEAD_WARNING_SECONDS = 0.1
_SECRET_ASSIGNMENT_RE = re.compile(r"(?im)\b(api[_-]?key|token|secret|password|authorization)\b(\s*[:=]\s*)([^\r\n]*)")
_TOKEN_PREFIX_RE = re.compile(r"\b(?:sk|gh[pousr])-[A-Za-z0-9_-]{8,}\b|\bgh[pousr]_[A-Za-z0-9_]{8,}\b")
_TERMINAL_CONTROL_SEQUENCE_RE = re.compile(
    r"(?:\x1b\](?:[^\x07\x1b\r\n]|\x1b(?!\\))*(?:\x07|\x1b\\))"  # one-line OSC controls
    r"|(?:\x1b[P^_][^\r\n]*?\x1b\\)"  # one-line DCS, PM, and APC strings terminated by ST
    r"|(?:(?:\x1b\[)|\x9b)[0-?]*[ -/]*[@-~]"  # CSI, including pytest SGR color sequences
    r"|(?:\x1b[()][0-2A-Z])"  # character-set selection
    r"|(?:\x1b[@-_])"  # remaining two-byte escape sequences
    r"|[\x80-\x9f]"  # decoded C1 controls, including DCS, CSI, ST, and OSC
)
_PYTEST_FAILURE_SUMMARY_RE = re.compile(r"^\s*(?P<kind>FAILED|ERROR)\s+\S")
_PYTEST_SHORT_SUMMARY_MARKER_RE = re.compile(r"^\s*=+\s+short test summary info\s+=+\s*$", re.IGNORECASE)

_VerificationStatus = Literal["passed", "incomplete", "misconfigured", "infrastructure_error"]


@dataclass(frozen=True)
class _VerificationOutcome:
    status: _VerificationStatus
    detail: str | None = None
    external_seconds: float = 0.0


@dataclass
class _VerificationTiming:
    """External verification time excluded from the enclosing Stop budget."""

    external_seconds: float = 0.0


def _warn_if_forge_overhead_exceeded(*, started: float, external_seconds: float, operation: str) -> None:
    forge_overhead = max(0.0, perf_counter() - started - external_seconds)
    if forge_overhead > _FORGE_OVERHEAD_WARNING_SECONDS:
        _logger.warning(
            "Forge-owned %s overhead exceeded 100 ms: %.1f ms",
            operation,
            forge_overhead * 1000,
        )


def _redacted_diagnostic(value: str | bytes | None) -> str:
    """Decode, neutralize terminal controls, and redact diagnostics without truncating them."""
    if value is None:
        return ""
    text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
    text = _TERMINAL_CONTROL_SEQUENCE_RE.sub("", text).replace("\x1b", "")
    text = _render_terminal_text(text)
    for credential in CREDENTIALS.values():
        for env_var in credential.env_vars:
            secret = os.environ.get(env_var.name) if env_var.secret else None
            if secret:
                text = text.replace(secret, "[REDACTED]")
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    text = _TOKEN_PREFIX_RE.sub("[REDACTED]", text)
    return text


def _render_terminal_text(value: str) -> str:
    """Apply basic cursor motion and return text without unsafe C0 controls.

    Backspace and carriage return can overwrite printable cells. Rendering them
    before redaction prevents control-inserted secrets from evading exact
    replacement; tabs become spaces and other C0/DEL controls are discarded.
    """
    rendered: list[str] = []
    line: list[str] = []
    cursor = 0

    for character in value:
        if character == "\n":
            rendered.extend(line)
            rendered.append(character)
            line = []
            cursor = 0
            continue
        if character == "\r":
            cursor = 0
            continue
        if character == "\b":
            cursor = max(0, cursor - 1)
            continue
        if character == "\t":
            next_tab_stop = ((cursor // 8) + 1) * 8
            if len(line) < next_tab_stop:
                line.extend(" " for _ in range(next_tab_stop - len(line)))
            cursor = next_tab_stop
            continue
        if ord(character) < 0x20 or character == "\x7f":
            continue

        if cursor < len(line):
            line[cursor] = character
        else:
            if cursor > len(line):
                line.extend(" " for _ in range(cursor - len(line)))
            line.append(character)
        cursor += 1

    rendered.extend(line)
    return "".join(rendered)


def _bounded_diagnostic(value: str | bytes | None) -> str:
    """Redact known credentials and bound untrusted verification diagnostics."""
    return _redacted_diagnostic(value)[:_MAX_DIAGNOSTIC_CHARS]


def _pytest_failure_lines(stream: str, *, after_short_summary_marker: bool) -> list[tuple[str, str]]:
    lines = stream.splitlines()
    if after_short_summary_marker:
        marker_indexes = [index for index, line in enumerate(lines) if _PYTEST_SHORT_SUMMARY_MARKER_RE.match(line)]
        if not marker_indexes:
            return []
        lines = lines[marker_indexes[-1] + 1 :]

    matches: list[tuple[str, str]] = []
    for line in lines:
        match = _PYTEST_FAILURE_SUMMARY_RE.match(line)
        if match:
            matches.append((match.group("kind"), line.strip()))
    return matches


def _preferred_pytest_failure_lines(matches: list[tuple[str, str]]) -> str:
    failed = [line for kind, line in matches if kind == "FAILED"]
    selected = failed or [line for kind, line in matches if kind == "ERROR"]
    return "\n".join(selected)


def _select_test_failure_excerpt(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    """Select pytest summary lines before falling back to the prior stderr-first posture."""
    # Redact complete streams before selecting lines or applying a character
    # boundary. Truncating first could leave an unmatched fragment of a secret.
    redacted_stdout = _redacted_diagnostic(stdout)
    redacted_stderr = _redacted_diagnostic(stderr)
    streams = (redacted_stdout, redacted_stderr)
    summary_matches = [
        match for stream in streams for match in _pytest_failure_lines(stream, after_short_summary_marker=True)
    ]
    if summary_matches:
        return _preferred_pytest_failure_lines(summary_matches)

    fallback_matches = [
        match for stream in streams for match in _pytest_failure_lines(stream, after_short_summary_marker=False)
    ]
    if fallback_matches:
        return _preferred_pytest_failure_lines(fallback_matches)
    return redacted_stderr or redacted_stdout


def _check_completion_promise(ver: VerificationConfig, transcript_path: Path) -> _VerificationOutcome:
    """Classify a completion-promise check without applying Stop policy."""
    if not ver.promise or not ver.promise.strip():
        return _VerificationOutcome("misconfigured", "completion_promise requires a non-empty promise")

    if "\n" in ver.promise or "\r" in ver.promise:
        return _VerificationOutcome("misconfigured", "completion_promise must be a single line")

    if not transcript_path.is_file():
        return _VerificationOutcome("infrastructure_error", "verification transcript is unavailable")

    try:
        last_text = _get_last_assistant_text_for_verification(transcript_path, raise_on_error=True)
    except Exception as exc:
        return _VerificationOutcome(
            "infrastructure_error",
            f"verification transcript could not be read ({type(exc).__name__})",
        )

    promise_stripped = ver.promise.strip()

    if last_text is not None:
        for line in last_text.splitlines():
            if line.strip() == promise_stripped:
                return _VerificationOutcome("passed")

    return _VerificationOutcome("incomplete", _bounded_diagnostic(f"Promise not found: {ver.promise}"))


def _check_test_suite(ver: VerificationConfig, worktree: Path) -> _VerificationOutcome:
    """Run the fixed suite synchronously and classify its result.

    Command is fixed: ["uv", "run", "pytest"]
    No shell, no user-configurable command. Only the subprocess wall time is
    recorded as external so Stop overhead accounting can exclude it.
    """
    cmd = ["uv", "run", "pytest"]
    if not worktree.is_dir():
        return _VerificationOutcome(
            "infrastructure_error",
            f"session worktree is unavailable: {_bounded_diagnostic(str(worktree))}",
        )

    external_started = perf_counter()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=ver.test_timeout_seconds,
            cwd=worktree,
            shell=False,
        )
        external_seconds = perf_counter() - external_started
        if result.returncode == 0:
            return _VerificationOutcome("passed", external_seconds=external_seconds)
        diagnostic = _select_test_failure_excerpt(result.stdout, result.stderr)
        detail = f"Tests failed (exit {result.returncode})"
        if diagnostic:
            detail = f"{detail}: {diagnostic}"
        return _VerificationOutcome("incomplete", _bounded_diagnostic(detail), external_seconds)
    except subprocess.TimeoutExpired:
        return _VerificationOutcome(
            "incomplete",
            f"test_suite timeout after {ver.test_timeout_seconds} seconds",
            perf_counter() - external_started,
        )
    except FileNotFoundError:
        return _VerificationOutcome(
            "infrastructure_error",
            "uv executable was not found for test_suite verification",
            perf_counter() - external_started,
        )
    except Exception as exc:
        return _VerificationOutcome(
            "infrastructure_error",
            f"test_suite execution failed ({type(exc).__name__})",
            perf_counter() - external_started,
        )


def _verification_worktree(store: SessionStore, manifest: SessionState) -> Path:
    """Resolve the checkout visible to the process running the Stop hook."""
    if os.environ.get(FORGE_SIDECAR_VAR) == "1":
        return store.forge_root
    if manifest.worktree is not None:
        return Path(manifest.worktree.path).expanduser().resolve()
    return store.forge_root


def _legacy_config_outcome(ver: VerificationConfig) -> _VerificationOutcome | None:
    if ver.type not in VERIFICATION_TYPES:
        return _VerificationOutcome(
            "misconfigured",
            _bounded_diagnostic(f"Unknown legacy verification.type {ver.type!r}"),
        )
    if ver.on_incomplete not in VERIFICATION_INCOMPLETE_MODES:
        return _VerificationOutcome(
            "misconfigured",
            _bounded_diagnostic(f"Unknown legacy verification.on_incomplete {ver.on_incomplete!r}"),
        )
    return None


def _persist_verification(
    store: SessionStore,
    *,
    result: str,
    error: str | None = None,
    increment_iterations: bool = False,
    set_started_at: bool = False,
    auto_bypass: bool = False,
) -> bool:
    """Persist one verification outcome; report failure without changing Stop policy."""

    def _mutate(manifest: SessionState) -> None:
        if manifest.confirmed.verification is None:
            manifest.confirmed.verification = VerificationConfirmed()

        manifest.confirmed.verification.last_result = result
        manifest.confirmed.verification.last_error = _bounded_diagnostic(error) or None

        if set_started_at and manifest.confirmed.verification.started_at is None:
            manifest.confirmed.verification.started_at = now_iso()

        if increment_iterations:
            manifest.confirmed.verification.iterations += 1

        if auto_bypass:
            set_override(manifest.overrides, "verification.bypass", True)

        manifest.confirmed.confirmed_at = now_iso()
        manifest.confirmed.confirmed_by = "hook:stop:verification"

    try:
        store.update(timeout_s=HOOK_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as exc:
        click.echo(
            f"[forge] Verification state persistence failed ({type(exc).__name__}); allowing Stop.",
            err=True,
        )
        return False
    return True


def _report_fail_open(outcome: _VerificationOutcome, store: SessionStore) -> tuple[bool, None]:
    _persist_verification(store, result=outcome.status, error=outcome.detail)
    label = outcome.status.replace("_", " ")
    click.echo(f"Warning: Verification {label} - {outcome.detail}; allowing Stop.", err=True)
    return (True, None)


def _run_verification_check(
    *,
    store: SessionStore,
    manifest: SessionState,
    transcript_path: Path,
    timing: _VerificationTiming | None = None,
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
        timing: Optional accumulator for the enclosing Stop pipeline.

    Returns:
        Tuple of (should_allow_stop, block_message_or_none).
        If should_allow_stop is False, block_message contains the stderr message.
    """
    from datetime import UTC, datetime

    verification_started = perf_counter()
    external_seconds = 0.0
    try:
        try:
            effective = compute_effective_intent(manifest)
        except Exception as exc:
            click.echo(
                f"[forge] Verification check could not compute effective intent ({type(exc).__name__}); allowing Stop.",
                err=True,
            )
            return (True, None)

        ver = effective.verification
        if ver is None:
            return (True, None)

        legacy_outcome = _legacy_config_outcome(ver)
        if legacy_outcome is not None:
            return _report_fail_open(legacy_outcome, store)

        if ver.bypass or ver.on_incomplete == "allow":
            return (True, None)

        if ver.type == "test_suite":
            outcome = _check_test_suite(ver, _verification_worktree(store, manifest))
            external_seconds = outcome.external_seconds
        else:
            outcome = _check_completion_promise(ver, transcript_path)

        if outcome.status == "passed":
            _persist_verification(store, result="passed")
            return (True, None)

        if outcome.status in {"misconfigured", "infrastructure_error"}:
            return _report_fail_open(outcome, store)

        check_error = outcome.detail or "verification did not pass"
        if ver.on_incomplete == "warn":
            _persist_verification(store, result="incomplete", error=check_error)
            click.echo(f"Warning: Verification incomplete - {check_error}", err=True)
            return (True, None)

        current_iterations = 0
        started_at: str | None = None
        if manifest.confirmed.verification:
            current_iterations = manifest.confirmed.verification.iterations
            started_at = manifest.confirmed.verification.started_at

        if current_iterations + 1 > ver.max_iterations:
            persisted = _persist_verification(
                store,
                result="max_iterations",
                error=f"Exceeded {ver.max_iterations} iterations",
                auto_bypass=True,
            )
            if persisted:
                click.echo(
                    f"Verification auto-bypassed: exceeded max_iterations ({ver.max_iterations}).",
                    err=True,
                )
            return (True, None)

        if ver.max_minutes is not None and started_at is not None:
            try:
                start_dt = parse_iso(started_at)
                elapsed_minutes = (datetime.now(UTC) - start_dt).total_seconds() / 60
            except Exception as exc:
                return _report_fail_open(
                    _VerificationOutcome(
                        "infrastructure_error",
                        f"verification timing state is unreadable ({type(exc).__name__})",
                    ),
                    store,
                )
            if elapsed_minutes > ver.max_minutes:
                persisted = _persist_verification(
                    store,
                    result="max_minutes",
                    error=f"Exceeded {ver.max_minutes} minutes",
                    auto_bypass=True,
                )
                if persisted:
                    click.echo(
                        f"Verification auto-bypassed: exceeded max_minutes ({ver.max_minutes}).",
                        err=True,
                    )
                return (True, None)

        if not _persist_verification(
            store,
            result="incomplete",
            error=check_error,
            increment_iterations=True,
            set_started_at=True,
        ):
            return (True, None)

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
            expected = _bounded_diagnostic(ver.promise)
            block_message = (
                f"Verification incomplete: expected completion promise not found.\n"
                f"Expected: {expected}\n"
                f"(must appear on its own line in the assistant's response)\n\n"
                f"Continue working and output the completion promise when done.\n"
                f"Escape hatches:\n"
                f"  - Type: %cancel-verification\n"
                f"  - Or run: forge session set verification.bypass true"
            )

        return (False, block_message)
    finally:
        if timing is not None:
            timing.external_seconds = external_seconds
        else:
            _warn_if_forge_overhead_exceeded(
                started=verification_started,
                external_seconds=external_seconds,
                operation="verification",
            )


def _join_assistant_text_blocks(texts: list[str]) -> str:
    """Join distinct text blocks without collapsing or doubling their line boundary."""
    joined = texts[0]
    for text in texts[1:]:
        if not joined.endswith(("\n", "\r")) and not text.startswith(("\n", "\r")):
            joined += "\n"
        joined += text
    return joined


def _get_last_assistant_text_for_verification(
    transcript_path: str | Path,
    *,
    raise_on_error: bool = False,
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

    Raises:
        OSError: When ``raise_on_error`` is true and the transcript cannot be read.
        UnicodeError: When ``raise_on_error`` is true and transcript decoding fails.
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
                            joined = _join_assistant_text_blocks(texts)
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
                        joined = _join_assistant_text_blocks(texts)
                        if ts >= latest_ts:
                            latest_ts = ts
                            latest_text = joined

    except Exception:
        if raise_on_error:
            raise

    return latest_text
