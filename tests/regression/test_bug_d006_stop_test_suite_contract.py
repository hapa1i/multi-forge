"""Regression for D006: Stop test-suite execution has a distinct infrastructure boundary.

Root cause: the fixed pytest subprocess ran in the hook process CWD, exposed raw
stderr, encoded result posture as legacy ``failed``/``warned`` labels, and kept a
block decision after state persistence failed. That could run the wrong project,
leak diagnostics, or block Stop without recording a trustworthy result.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from forge.cli.hooks import verification
from forge.cli.hooks.verification import _run_verification_check
from forge.session import SessionStore, create_session_state
from forge.session.models import SessionState, VerificationConfig

pytestmark = pytest.mark.regression


def _write_transcript(path: Path) -> Path:
    path.write_text(
        '{"timestamp":"2026-01-01T00:00:00Z","message":{"role":"assistant","content":[{"text":"done"}]}}\n',
        encoding="utf-8",
    )
    return path


def _configured_store(tmp_path: Path, *, on_incomplete: str = "block") -> tuple[SessionStore, SessionState, Path]:
    worktree = tmp_path / "session-worktree"
    worktree.mkdir()
    forge_root = tmp_path / "manifest-root"
    manifest = create_session_state("verification-test", worktree_path=str(worktree))
    manifest.forge_root = str(forge_root)
    manifest.intent.verification = VerificationConfig(type="test_suite", on_incomplete=on_incomplete)
    store = SessionStore(str(forge_root), manifest.name)
    store.write(manifest)
    return store, manifest, worktree


def test_fixed_suite_is_synchronous_in_session_worktree_and_excludes_subprocess_wall_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store, manifest, worktree = _configured_store(tmp_path)
    transcript = _write_transcript(tmp_path / "transcript.jsonl")
    observed: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed["cmd"] = cmd
        observed.update(kwargs)
        time.sleep(0.12)
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Keep overhead accounting deterministic under scheduler contention: the
    # verification spans 140 ms, of which the subprocess owns 120 ms.
    clock_samples = iter((10.0, 10.01, 10.13, 10.14))
    monkeypatch.setattr(verification, "perf_counter", lambda: next(clock_samples))
    started = time.perf_counter()
    with caplog.at_level(logging.WARNING, logger="forge.cli.hooks.verification"):
        allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)
    elapsed = time.perf_counter() - started

    assert elapsed >= 0.1  # The approved fixed test subprocess remains synchronous.
    assert allow is True and message is None
    assert observed["cmd"] == ["uv", "run", "pytest"]
    assert observed["cwd"] == worktree.resolve()
    assert observed["timeout"] == 300
    assert observed["shell"] is False
    assert "Forge-owned verification overhead exceeded" not in caplog.text
    assert list(clock_samples) == []
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    assert confirmed.last_result == "passed"


def test_test_suite_timeout_is_incomplete_and_follows_warn_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, manifest, _ = _configured_store(tmp_path, on_incomplete="warn")
    transcript = _write_transcript(tmp_path / "transcript.jsonl")

    def raise_timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd=["uv", "run", "pytest"], timeout=300)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is True and message is None
    assert "verification incomplete" in capsys.readouterr().err.lower()
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    assert confirmed.last_result == "incomplete"
    assert confirmed.last_error is not None and "timeout" in confirmed.last_error.lower()


def test_failed_test_diagnostic_is_bounded_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, manifest, _ = _configured_store(tmp_path, on_incomplete="warn")
    transcript = _write_transcript(tmp_path / "transcript.jsonl")
    secret = "sk-test-secret-value"
    bearer = "unregistered-bearer-secret"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    stderr = f"OPENAI_API_KEY={secret}\nAuthorization: Bearer {bearer}\n" + ("x" * 500)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=stderr.encode()),
    )

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is True and message is None
    displayed = capsys.readouterr().err
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    assert confirmed.last_result == "incomplete"
    assert confirmed.last_error is not None
    assert len(confirmed.last_error) <= 200
    assert secret not in displayed
    assert secret not in confirmed.last_error
    assert bearer not in displayed
    assert bearer not in confirmed.last_error
    assert "[REDACTED]" in displayed


def test_terminal_controls_are_removed_before_environment_secret_redaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "boundary-secret-material-for-redaction"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    split_secret = f"{secret[:12]}\x1b[31m{secret[12:]}\x1b[0m"

    assert verification._redacted_diagnostic(split_secret) == "[REDACTED]"


def test_terminal_hyperlink_controls_preserve_visible_diagnostic_text() -> None:
    linked_failure = "\x1b]8;;https://example.test\x1b\\FAILED test_widget.py::test_failure\x1b]8;;\x1b\\"

    assert verification._redacted_diagnostic(linked_failure) == "FAILED test_widget.py::test_failure"


def test_failed_test_diagnostic_prefers_late_stdout_summary_after_redaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, _ = _configured_store(tmp_path)
    transcript = _write_transcript(tmp_path / "transcript.jsonl")
    secret = "boundary-secret-material-" + ("s" * 80)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    failure_id = "FAILED tests/regression/test_stop_failure_excerpts.py::test_late_failure"
    detail_prefix = f"Tests failed (exit 1): {failure_id} - "
    filler = "x" * (185 - len(detail_prefix))
    failure_summary = f"{failure_id} - {filler}{secret} useful tail context " + ("y" * 100)
    # Before redaction the configured secret crosses the 200-character detail
    # boundary. Selecting or truncating first would leave a secret fragment.
    assert len(detail_prefix + filler) == 185
    stdout = (("=" * 80 + "\n") * 4) + failure_summary + "\n1 failed in 0.01s\n"
    stderr = "third-party plugin warning: unrelated cache notice\n"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd,
            1,
            stdout=stdout.encode(),
            stderr=stderr.encode(),
        ),
    )

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is False and message is not None
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    assert confirmed.last_result == "incomplete"
    persisted = confirmed.last_error
    assert persisted is not None
    assert failure_id in persisted
    assert "third-party plugin warning" not in persisted
    assert len(persisted) == 200
    assert "[REDACTED]" in persisted
    assert secret[:20] not in persisted
    assert f"Error: {persisted}\n\n" in message


def test_failed_test_diagnostic_ignores_captured_error_logs_before_short_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, _ = _configured_store(tmp_path)
    transcript = _write_transcript(tmp_path / "transcript.jsonl")
    failure_id = "FAILED tests/regression/test_stop_failure_excerpts.py::test_logged_failure"
    captured_logs = "\n".join(
        f"ERROR    root:mod.py:{line} captured error noise " + ("x" * 80) for line in range(10, 14)
    )
    stdout = (
        "=================================== FAILURES ===================================\n"
        "------------------------------ Captured log call -------------------------------\n"
        f"{captured_logs}\n"
        "=========================== short test summary info ============================\n"
        f"{failure_id} - AssertionError: expected true\n"
        "============================== 1 failed in 0.01s ===============================\n"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd,
            1,
            stdout=stdout.encode(),
            stderr=b"third-party plugin warning\n",
        ),
    )

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is False and message is not None
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    persisted = confirmed.last_error
    assert persisted is not None
    assert failure_id in persisted
    assert "captured error noise" not in persisted
    assert len(persisted) <= 200
    assert f"Error: {persisted}\n\n" in message


def test_failure_excerpt_keeps_error_only_short_summary() -> None:
    error_id = "ERROR tests/regression/test_stop_failure_excerpts.py::test_setup_failure"
    stdout = (
        "ERROR    root:mod.py:10 captured error noise\n"
        "=========================== short test summary info ============================\n"
        f"{error_id} - RuntimeError: fixture failed\n"
    )

    assert verification._select_test_failure_excerpt(stdout, "plugin warning\n") == (
        f"{error_id} - RuntimeError: fixture failed"
    )


def test_forced_color_failure_keeps_node_id_and_strips_terminal_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, manifest, _ = _configured_store(tmp_path)
    transcript = _write_transcript(tmp_path / "transcript.jsonl")
    test_path = tmp_path / "test_ansi_failure.py"
    test_path.write_text("def test_ansi_failure():\n    assert False\n", encoding="utf-8")
    env = dict(os.environ)
    env["PY_COLORS"] = "1"
    env["PYTEST_ADDOPTS"] = ""
    env.pop("NO_COLOR", None)
    colored = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", test_path.name],
        cwd=tmp_path,
        capture_output=True,
        env=env,
        check=False,
    )
    assert colored.returncode == 1
    assert "\x1b[" in colored.stdout.decode()

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(
            cmd,
            colored.returncode,
            stdout=colored.stdout,
            stderr=b"third-party plugin warning: unrelated cache notice\n",
        ),
    )

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is False and message is not None
    confirmed = store.read().confirmed.verification
    assert confirmed is not None
    persisted = confirmed.last_error
    assert persisted is not None
    assert "FAILED test_ansi_failure.py::test_ansi_failure" in persisted
    assert "third-party plugin warning" not in persisted
    assert "\x1b" not in persisted
    assert len(persisted) <= 200
    assert f"Error: {persisted}\n\n" in message


def test_incomplete_result_fails_open_when_state_cannot_be_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, manifest, _ = _configured_store(tmp_path)
    transcript = _write_transcript(tmp_path / "transcript.jsonl")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **_kwargs: subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"tests failed"),
    )
    monkeypatch.setattr(store, "update", lambda **_kwargs: (_ for _ in ()).throw(OSError("read-only state")))

    allow, message = _run_verification_check(store=store, manifest=manifest, transcript_path=transcript)

    assert allow is True and message is None
    assert "persistence failed" in capsys.readouterr().err.lower()
