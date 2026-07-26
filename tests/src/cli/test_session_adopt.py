"""Tests for the `forge session adopt` CLI leaf (native_session_adoption Slice 2)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionStore
from forge.session.claude.paths import get_transcript_path
from tests.src.cli.session_command_support import successful_claude_launch

_UUID = "aaaa1111-2222-3333-4444-555566667777"


def _write_transcript(
    project: Path,
    *,
    session_uuid: str = _UUID,
    models: tuple[str, ...] = ("claude-opus-5",),
    stale: bool = True,
) -> Path:
    entries: list[dict[str, object]] = [{"type": "user", "cwd": str(project), "message": {"role": "user"}}]
    entries += [{"type": "assistant", "cwd": str(project), "message": {"model": m}} for m in models]

    path = get_transcript_path(str(project), session_uuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    if stale:
        # Past the 30-minute window, so no double-attach confirmation is prompted.
        os.utime(path, (0, 0))
    return path


class TestAdoptCli:
    def test_adopts_and_reports_the_inferred_model(self, runner: CliRunner, temp_env: Path) -> None:
        _write_transcript(temp_env, models=("claude-fable-5", "claude-opus-4-8"))

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted"])

        assert result.exit_code == 0, result.output
        assert "Adopted" in result.output
        assert "claude-opus-4-8" in result.output, "should report the last real model"

        state = SessionStore(str(temp_env), "adopted").read()
        assert state.confirmed.claude_session_id == _UUID
        assert state.confirmed.adoption is not None
        assert state.confirmed.adoption.model_basis == "inferred"

    def test_model_flag_overrides_inference(self, runner: CliRunner, temp_env: Path) -> None:
        _write_transcript(temp_env, models=("claude-opus-4-8",))

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted", "--model", "claude-opus-5"])

        assert result.exit_code == 0, result.output
        state = SessionStore(str(temp_env), "adopted").read()
        assert state.intent.launch is not None
        assert state.intent.launch.direct_model == "claude-opus-5"
        assert state.confirmed.adoption is not None
        assert state.confirmed.adoption.model_basis == "explicit"

    def test_no_basis_warns_and_pins_nothing(self, runner: CliRunner, temp_env: Path) -> None:
        """P3: with no basis adoption must not invent a pin a `--proxy` resume would apply."""
        _write_transcript(temp_env, models=())

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted"])

        assert result.exit_code == 0, result.output
        assert "unknown" in result.output.lower()

        state = SessionStore(str(temp_env), "adopted").read()
        assert state.intent.launch is not None
        assert state.intent.launch.direct_model is None
        assert state.confirmed.adoption is not None
        assert state.confirmed.adoption.model_basis == "none"

    def test_already_bound_names_the_owning_session(self, runner: CliRunner, temp_env: Path) -> None:
        _write_transcript(temp_env)
        assert runner.invoke(main, ["session", "adopt", _UUID, "--name", "first"]).exit_code == 0

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "second"])

        assert result.exit_code == 1
        assert "first" in result.output
        assert not (temp_env / ".forge" / "sessions" / "second").exists()

    def test_missing_transcript_rejects_without_creating_state(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "adopt", _UUID])

        assert result.exit_code == 1
        assert "no transcript" in result.output
        assert not (temp_env / ".forge" / "sessions").exists()

    def test_recent_transcript_requires_confirmation(self, runner: CliRunner, temp_env: Path) -> None:
        """Forge cannot see a live native client, so it asks rather than refusing."""
        _write_transcript(temp_env, stale=False)

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted"], input="n\n")

        assert result.exit_code == 0
        assert "cancelled" in result.output.lower()
        assert not (temp_env / ".forge" / "sessions" / "adopted").exists()

    def test_yes_skips_the_confirmation(self, runner: CliRunner, temp_env: Path) -> None:
        _write_transcript(temp_env, stale=False)

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted", "--yes"])

        assert result.exit_code == 0, result.output
        assert (temp_env / ".forge" / "sessions" / "adopted").exists()

    def test_adopted_session_reattaches_with_no_fork_session(self, runner: CliRunner, temp_env: Path) -> None:
        """The card's headline claim: reattach needs zero new resume code."""
        _write_transcript(temp_env)
        assert runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted"]).exit_code == 0

        with successful_claude_launch() as mock_invoke:
            result = runner.invoke(main, ["session", "resume", "adopted"])

        assert result.exit_code == 0, result.output
        kwargs = mock_invoke.call_args.kwargs
        assert kwargs.get("resume_id") == _UUID
        assert not kwargs.get("fork_session")
