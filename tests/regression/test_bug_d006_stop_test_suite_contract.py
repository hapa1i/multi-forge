"""Regression for D006: Stop test-suite execution has a distinct infrastructure boundary.

Root cause: the fixed pytest subprocess ran in the hook process CWD, exposed raw
stderr, encoded result posture as legacy ``failed``/``warned`` labels, and kept a
block decision after state persistence failed. That could run the wrong project,
leak diagnostics, or block Stop without recording a trustworthy result.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

import pytest

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
