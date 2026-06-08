"""Tests for the `forge runtime` CLI (Phase 4e).

Hermetic: PATH presence and the Claude version probe are stubbed so no real
``claude/codex/gemini --version`` subprocess runs.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli.runtime import runtime


@pytest.fixture(autouse=True)
def _no_real_probes(monkeypatch) -> None:
    """Make detection hermetic: nothing on PATH, Claude probe returns None."""
    monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _name: None)
    monkeypatch.setattr("forge.install.version.get_claude_runtime_version", lambda: None)


def test_list_renders_all_runtimes() -> None:
    result = CliRunner().invoke(runtime, ["list"])
    assert result.exit_code == 0
    for rid in ("claude_code", "codex", "gemini"):
        assert rid in result.output
    # The Codex partial-enforcement caveat is surfaced, not hidden.
    assert "partial" in result.output
    # Hooks render as the tri-state value (Codex is gated, not a bare "yes").
    assert "gated" in result.output
    # The note's bracketed token survives Rich markup (escape, not eaten as a tag).
    assert "[features]" in result.output


def test_list_json_carries_capability_fields() -> None:
    result = CliRunner().invoke(runtime, ["list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {d["id"] for d in data} == {"claude_code", "codex", "gemini"}

    codex = next(d for d in data if d["id"] == "codex")
    assert codex["pretool_policy"] == "partial"  # limit encoded, not parity
    # Hooks are gated, and the gate is machine-readable (not buried in the note).
    assert codex["native_hooks"] == "gated"
    assert codex["hook_min_version"] == "0.131.0"
    assert codex["hook_feature_flag"] is None  # no required hook flag; codex_hooks remains a deprecated alias
    assert codex["installed"] is False  # nothing on PATH (stubbed)
    assert codex["version"] is None
    assert "detect" not in codex  # the callable is dropped from JSON

    claude = next(d for d in data if d["id"] == "claude_code")
    assert claude["install_scopes"] == ["user", "project", "local"]
