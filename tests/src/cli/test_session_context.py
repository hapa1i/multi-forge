"""CLI tests for ``forge session context``."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from forge.cli.session import session


@pytest.fixture()
def runner():
    return CliRunner()


class TestSessionContextCLI:
    def test_no_session_falls_back_to_env(self, runner, monkeypatch):
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(session, ["context"])
        assert result.exit_code == 0

    def test_unknown_session_exits_nonzero(self, runner, monkeypatch):
        """Explicit nonexistent session is an error, even when env vars are set."""
        monkeypatch.setenv("ACTIVE_TEMPLATE", "litellm-openai")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8085")
        result = runner.invoke(session, ["context", "nonexistent-xyz-000"])
        assert result.exit_code != 0
        assert "Error" in result.output

    def test_field_with_no_session_returns_default(self, runner, monkeypatch):
        """--field with no Forge session falls back to env and returns default."""
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        monkeypatch.delenv("ACTIVE_TEMPLATE", raising=False)
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        result = runner.invoke(session, ["context", "--field", "model_family"])
        assert result.exit_code == 0
        assert "anthropic" in result.output

    def test_json_flag_accepted(self, runner, monkeypatch):
        """--json flag is accepted (falls back to env context when no session)."""
        monkeypatch.delenv("FORGE_SESSION", raising=False)
        result = runner.invoke(session, ["context", "--json"])
        assert result.exit_code == 0
        assert '"model_family"' in result.output

    def test_help_shows_context(self, runner):
        result = runner.invoke(session, ["context", "--help"])
        assert result.exit_code == 0
        assert "session context" in result.output.lower() or "SESSION_ID" in result.output
