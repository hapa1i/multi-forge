"""Tests for the `forge session adopt` CLI leaf (native_session_adoption Slice 2)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest
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

    def test_unknown_id_rejects_without_creating_state(self, runner: CliRunner, temp_env: Path) -> None:
        """Runtime detection runs first, so the error names where both arms looked."""
        result = runner.invoke(main, ["session", "adopt", _UUID])

        assert result.exit_code == 1
        assert "no conversation" in result.output
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

    def test_failed_index_enqueue_names_a_real_recovery_command(
        self, runner: CliRunner, temp_env: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The recovery tip must name a command that exists.

        It once suggested `forge search reindex`; the actual leaf is
        `forge search rebuild-index`, and nothing else validates tip commands.
        """
        import forge.core.ops.session_adopt as adopt_mod

        _write_transcript(temp_env)
        monkeypatch.setattr(adopt_mod, "enqueue_index_marker", lambda **_: None)

        result = runner.invoke(main, ["session", "adopt", _UUID, "--name", "adopted"])

        assert result.exit_code == 0, result.output
        assert "forge search rebuild-index" in result.output

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


class TestAdoptPreview:
    def test_bare_adopt_lists_candidates_with_turns_and_preview(self, runner: CliRunner, temp_env: Path) -> None:
        path = _write_transcript(temp_env, models=("claude-opus-5",))
        entries = [
            {"type": "user", "cwd": str(temp_env), "message": {"content": "<command-message>init</command-message>"}},
            {"type": "user", "cwd": str(temp_env), "message": {"content": "wire up the payment retry"}},
            {"type": "assistant", "cwd": str(temp_env), "message": {"model": "claude-opus-5"}},
        ]
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

        result = runner.invoke(main, ["session", "adopt"])

        assert result.exit_code == 0, result.output
        assert _UUID in result.output
        assert "wire up the payment retry" in result.output, "synthetic wrapper must not win the preview"
        assert str(temp_env) in result.output, "the scanned cwd must be named"

    def test_bare_adopt_with_nothing_here_points_at_the_launch_directory(
        self, runner: CliRunner, temp_env: Path
    ) -> None:
        result = runner.invoke(main, ["session", "adopt"])

        assert result.exit_code == 0, result.output
        assert "No unbound conversations" in result.output
        assert "subdirectory" in result.output, "exact-CWD guidance is the actionable part"
        assert str(temp_env) in result.output

    def test_bare_adopt_hides_a_conversation_it_already_adopted(self, runner: CliRunner, temp_env: Path) -> None:
        _write_transcript(temp_env)
        assert runner.invoke(main, ["session", "adopt", _UUID, "--name", "mine"]).exit_code == 0

        result = runner.invoke(main, ["session", "adopt"])

        assert result.exit_code == 0, result.output
        assert _UUID not in result.output
        assert "No unbound conversations" in result.output


class TestPreviewContract:
    def test_json_preview_is_machine_readable(self, runner: CliRunner, temp_env: Path) -> None:
        path = _write_transcript(temp_env)
        entries = [
            {"type": "user", "cwd": str(temp_env), "message": {"content": "check the retry path"}},
            {"type": "assistant", "cwd": str(temp_env), "message": {"model": "claude-opus-5"}},
        ]
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        os.utime(path, (0, 0))

        result = runner.invoke(main, ["session", "adopt", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["cwd"] == str(temp_env)
        assert payload["scanned_dir"]
        assert [c["conversation_id"] for c in payload["candidates"]] == [_UUID]

        # The payload is a machine contract: pin the exact key sets so a field
        # cannot drift or vanish without this test noticing.
        assert set(payload) == {"cwd", "scanned_dir", "candidates"}
        candidate = payload["candidates"][0]
        assert set(candidate) == {"conversation_id", "transcript_path", "modified_at", "user_turns", "preview"}
        assert candidate["transcript_path"] == str(path)
        assert datetime.fromisoformat(candidate["modified_at"])
        assert candidate["user_turns"] == 1
        assert candidate["preview"] == "check the retry path"

    def test_json_with_a_conversation_id_is_rejected(self, runner: CliRunner, temp_env: Path) -> None:
        _write_transcript(temp_env)
        result = runner.invoke(main, ["session", "adopt", _UUID, "--json"])
        assert result.exit_code == 1
        assert "--json applies to the preview" in result.output

    @pytest.mark.parametrize("flag", [["--name", "x"], ["--model", "claude-opus-5"], ["--yes"]])
    def test_binding_flags_are_refused_in_preview_mode(
        self, runner: CliRunner, temp_env: Path, flag: list[str]
    ) -> None:
        """Silently ignoring them would imply the preview had adopted something."""
        result = runner.invoke(main, ["session", "adopt", *flag])
        assert result.exit_code == 1
        assert "not to previewing" in result.output

    def test_transcript_markup_is_not_interpreted(self, runner: CliRunner, temp_env: Path) -> None:
        """A conversation is external input; Rich must not read `[...]` in it."""
        path = _write_transcript(temp_env)
        entries = [{"type": "user", "cwd": str(temp_env), "message": {"content": "why is [red] logged here?"}}]
        path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
        os.utime(path, (0, 0))

        result = runner.invoke(main, ["session", "adopt"])

        assert result.exit_code == 0, result.output
        assert "[red]" in result.output, "the bracket text must survive verbatim"


class TestCodexArm:
    """The CLI routes by on-disk evidence, not by the shape of the id."""

    _THREAD = "019f0b65-b51c-7683-99c7-bb48107f7b83"

    @pytest.fixture(autouse=True)
    def _codex(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
        import forge.core.ops.codex_adopt as mod

        class _Preflight:
            auth_method = "codex_store"
            auth_source = "chatgpt"
            billing_mode = "subscription"

        monkeypatch.setattr(mod, "assert_codex_ready", lambda **_: _Preflight())

    def _rollout(self, tmp_path: Path, cwd: Path) -> Path:
        day = tmp_path / "codex" / "sessions" / "2026" / "06" / "27"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-06-27T19-24-02-{self._THREAD}.jsonl"
        path.write_text(
            json.dumps({"type": "session_meta", "payload": {"id": self._THREAD, "cwd": str(cwd)}}) + "\n",
            encoding="utf-8",
        )
        os.utime(path, (0, 0))
        return path

    def test_adopts_a_codex_thread(self, runner: CliRunner, temp_env: Path, tmp_path: Path) -> None:
        rollout = self._rollout(tmp_path, temp_env)

        result = runner.invoke(main, ["session", "adopt", self._THREAD, "--name", "codex-spike"])

        assert result.exit_code == 0, result.output
        assert "Codex thread" in result.output
        state = SessionStore(str(temp_env), "codex-spike").read()
        assert state.confirmed.codex is not None
        assert state.confirmed.codex.rollout_path == str(rollout)
        assert state.confirmed.claude_session_id is None

    def test_model_is_refused_for_codex(self, runner: CliRunner, temp_env: Path, tmp_path: Path) -> None:
        self._rollout(tmp_path, temp_env)

        result = runner.invoke(main, ["session", "adopt", self._THREAD, "--model", "claude-opus-5"])

        assert result.exit_code == 1
        assert "does not apply to Codex" in result.output

    def test_unknown_id_names_both_search_locations(self, runner: CliRunner, temp_env: Path) -> None:
        result = runner.invoke(main, ["session", "adopt", self._THREAD])

        assert result.exit_code == 1
        assert "CODEX_HOME" in result.output
