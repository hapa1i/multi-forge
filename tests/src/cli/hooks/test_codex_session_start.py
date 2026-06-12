"""Hook-level tests for `forge hook codex-session-start`.

Wire invariant under test: stdout carries ONLY the strict SessionStart
``additionalContext`` JSON (Codex fails OPEN on malformed hook output). Every
non-delivery path is a silent no-op: exit 0 with empty stdout AND empty stderr --
a user-scope registration fires for every Codex session, so unrelated sessions
must see no Forge noise. Diagnostics ride the debug log, not stderr.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.hooks.codex_transfer import format_session_start_context
from forge.cli.hooks.commands import hooks
from forge.session import SessionStore, create_session_state
from forge.session.codex_handoff import (
    observation_receipt_path,
    pending_context_path,
    read_observation_receipt,
    read_receipt,
    receipt_path,
    stage_pending_context,
)

_THREAD_ID = "019eb075-ef05-7702-9045-0a8a88b512d2"
_ROLLOUT = "/codex-home/sessions/2026/06/10/rollout-2026-06-10T03-36-19-" + _THREAD_ID + ".jsonl"
_BODY = "# Handoff context (curated transfer from a prior planning session)\n\nCURATED-BODY\n"


def _make_session(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    set_forge_root_env: bool = True,
) -> SessionStore:
    monkeypatch.chdir(root)
    monkeypatch.setenv("FORGE_SESSION", "codex-transfer-session")
    if set_forge_root_env:
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(root))
    else:
        monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)

    store = SessionStore(str(root), "codex-transfer-session")
    manifest = create_session_state("codex-transfer-session", worktree_path=str(root))
    manifest.forge_root = str(root)
    store.write(manifest)
    return store


def _payload(
    *,
    cwd: str,
    hook_event_name: str = "SessionStart",
    session_id: str | None = _THREAD_ID,
    source: str = "startup",
) -> str:
    # Mirrors tests/fixtures/codex/hooks/session_start.stdin.json (snake_case, thread UUID).
    data: dict[str, object] = {
        "transcript_path": _ROLLOUT,
        "cwd": cwd,
        "hook_event_name": hook_event_name,
        "model": "gpt-5.5",
        "permission_mode": "bypassPermissions",
        "source": source,
    }
    if session_id is not None:
        data["session_id"] = session_id
    return json.dumps(data)


def _invoke(payload: str):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(hooks, ["codex-session-start"], input=payload)


class TestDelivery:
    def test_staged_context_delivered_and_consumed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)

        result = _invoke(_payload(cwd=str(tmp_path)))

        assert result.exit_code == 0
        assert result.stdout == format_session_start_context(_BODY) + "\n"
        assert not pending_context_path(store.session_dir).exists()
        receipt = read_receipt(store.session_dir)
        assert receipt is not None
        assert receipt.session_id == _THREAD_ID
        assert receipt.transcript_path == _ROLLOUT
        assert receipt.source == "startup"

    def test_wire_is_exactly_one_single_line_strict_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression (wire strictness): Codex fails OPEN on malformed output, so a
        non-empty stdout must be exactly one single-line JSON object with the pinned
        key sets and nothing else."""
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)

        result = _invoke(_payload(cwd=str(tmp_path)))

        lines = result.stdout.splitlines()
        assert len(lines) == 1
        wire = json.loads(lines[0])
        assert set(wire.keys()) == {"hookSpecificOutput"}
        inner = wire["hookSpecificOutput"]
        assert set(inner.keys()) == {"hookEventName", "additionalContext"}
        assert inner["hookEventName"] == "SessionStart"
        assert inner["additionalContext"] == _BODY

    def test_payload_cwd_rooting(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: session-store rooting must use the payload cwd. FORGE_FORGE_ROOT
        is unset and the manifest is never indexed, so only the payload-cwd forge_root
        derivation finds the staged file."""
        project = tmp_path / "project"
        project.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        store = _make_session(project, monkeypatch, set_forge_root_env=False)
        stage_pending_context(store.session_dir, _BODY)
        monkeypatch.chdir(elsewhere)  # process CWD points away from the project

        result = _invoke(_payload(cwd=str(project)))

        assert result.exit_code == 0
        assert result.stdout == format_session_start_context(_BODY) + "\n"


class TestSilentNoOps:
    def _assert_silent(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_empty_stdin(self) -> None:
        self._assert_silent(_invoke(""))

    def test_non_json_stdin(self) -> None:
        self._assert_silent(_invoke("not json {"))

    def test_wrong_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)
        result = _invoke(_payload(cwd=str(tmp_path), hook_event_name="PreToolUse"))
        self._assert_silent(result)
        assert pending_context_path(store.session_dir).exists()  # not consumed

    def test_missing_session_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)
        result = _invoke(_payload(cwd=str(tmp_path), session_id=None))
        self._assert_silent(result)
        assert pending_context_path(store.session_dir).exists()

    def test_no_resolvable_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression: a user-scope registration fires for every Codex session, so an
        unresolvable session (any non-Forge Codex start) must emit NO stderr -- the
        diagnostic rides the debug log only."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.delenv("FORGE_FORGE_ROOT", raising=False)
        caplog.set_level(logging.DEBUG, logger="forge.cli.hooks.codex_transfer")
        result = _invoke(_payload(cwd=str(tmp_path)))
        self._assert_silent(result)
        assert "no session resolved" in caplog.text

    def test_consume_failure_fails_open_and_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Regression: a staged-context read failure must stay a silent exit-0 no-op
        (no stderr), with the diagnostic on the debug log only."""
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)

        def _boom(*args: object, **kwargs: object) -> str:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr("forge.cli.hooks.codex_transfer.consume_pending_context", _boom)
        caplog.set_level(logging.DEBUG, logger="forge.cli.hooks.codex_transfer")

        result = _invoke(_payload(cwd=str(tmp_path)))

        self._assert_silent(result)
        assert pending_context_path(store.session_dir).exists()  # not consumed
        assert "staged-context read failed" in caplog.text

    def test_nothing_staged_is_the_resume_case(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A resume-turn SessionStart finds no staged file (one-shot consumed at start)
        and must stay silent -- no late delivery, no DELIVERY receipt. Since Phase 5 an
        observation receipt IS written (interactive thread capture), still silently."""
        store = _make_session(tmp_path, monkeypatch)
        result = _invoke(_payload(cwd=str(tmp_path), source="resume"))
        self._assert_silent(result)
        assert not receipt_path(store.session_dir).exists()
        observation = read_observation_receipt(store.session_dir)
        assert observation is not None
        assert observation.source == "resume"


class TestObservationReceipt:
    """Phase 5: nothing-staged turns in a managed session record an observation."""

    def _assert_silent(self, result) -> None:  # type: ignore[no-untyped-def]
        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_nothing_staged_writes_observation_from_payload(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _make_session(tmp_path, monkeypatch)
        result = _invoke(_payload(cwd=str(tmp_path)))
        self._assert_silent(result)
        observation = read_observation_receipt(store.session_dir)
        assert observation is not None
        assert observation.session_id == _THREAD_ID
        assert observation.transcript_path == _ROLLOUT
        assert observation.source == "startup"
        assert not receipt_path(store.session_dir).exists()

    def test_staged_turn_writes_no_observation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Per-turn mutual exclusivity: a delivery turn leaves only the delivery receipt."""
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)
        result = _invoke(_payload(cwd=str(tmp_path)))
        assert result.stdout == format_session_start_context(_BODY) + "\n"
        assert read_receipt(store.session_dir) is not None
        assert not observation_receipt_path(store.session_dir).exists()

    def test_staged_delivery_receipt_failure_writes_no_observation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: consume returns None both for "nothing staged" and "staged but
        the delivery receipt write failed". The failure case is a DELIVERY failure --
        recording it as a nothing-staged observation would be dishonest."""
        store = _make_session(tmp_path, monkeypatch)
        stage_pending_context(store.session_dir, _BODY)

        def _boom(*args: object, **kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("forge.session.codex_handoff.atomic_write_json", _boom)

        result = _invoke(_payload(cwd=str(tmp_path)))

        self._assert_silent(result)
        assert pending_context_path(store.session_dir).read_text() == _BODY  # delivery failed, pending kept
        assert not receipt_path(store.session_dir).exists()
        assert not observation_receipt_path(store.session_dir).exists()

    def test_pre_resolution_paths_write_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Wrong event / missing session_id return before resolution: zero writes."""
        store = _make_session(tmp_path, monkeypatch)
        self._assert_silent(_invoke(_payload(cwd=str(tmp_path), hook_event_name="PreToolUse")))
        self._assert_silent(_invoke(_payload(cwd=str(tmp_path), session_id=None)))
        assert not observation_receipt_path(store.session_dir).exists()

    def test_multi_turn_last_wins(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        store = _make_session(tmp_path, monkeypatch)
        _invoke(_payload(cwd=str(tmp_path), session_id="11111111-1111-1111-1111-111111111111"))
        _invoke(_payload(cwd=str(tmp_path), session_id="22222222-2222-2222-2222-222222222222", source="resume"))
        observation = read_observation_receipt(store.session_dir)
        assert observation is not None
        assert observation.session_id == "22222222-2222-2222-2222-222222222222"
        assert observation.source == "resume"

    def test_observation_write_failure_stays_silent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _make_session(tmp_path, monkeypatch)

        def _boom(*args: object, **kwargs: object) -> bool:
            raise RuntimeError("disk on fire")

        monkeypatch.setattr("forge.cli.hooks.codex_transfer.write_observation_receipt", _boom)
        caplog.set_level(logging.DEBUG, logger="forge.cli.hooks.codex_transfer")

        result = _invoke(_payload(cwd=str(tmp_path)))

        self._assert_silent(result)
        assert "observation write failed" in caplog.text
