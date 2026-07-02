"""Manifest characterization tests for the Claude session CLI path.

These snapshots exercise the CLI session entrypoints and pin manifest behavior
across the Claude session op extraction (a behavior-preserving refactor). They pin
key order as well as values by comparing JSON rendered without ``sort_keys``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import SessionStore
from forge.session.models import SessionState, session_state_to_dict

_ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("COLUMNS", "500")

    project = tmp_path / "project"
    project.mkdir()
    (project / ".git").mkdir()
    (project / ".forge").mkdir()
    monkeypatch.chdir(project)
    return project


def _normalize_manifest_value(value: object, *, project: Path) -> object:
    if isinstance(value, dict):
        return {k: _normalize_manifest_value(v, project=project) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_manifest_value(v, project=project) for v in value]
    if isinstance(value, str):
        if _ISO_TIMESTAMP_RE.match(value):
            return "<timestamp>"
        if _UUID_RE.match(value):
            return "<uuid>"
        normalized = value
        path_variants = {str(project), str(project.resolve())}
        for path in sorted(path_variants, key=len, reverse=True):
            normalized = normalized.replace(path, "<project>")
        return normalized
    return value


def _manifest_json(state: SessionState, *, project: Path) -> str:
    normalized = _normalize_manifest_value(session_state_to_dict(state), project=project)
    return json.dumps(normalized, indent=2)


def test_start_no_launch_manifest_shape(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(main, ["session", "start", "char-start", "--no-launch"])

    assert result.exit_code == 0, result.output
    state = SessionStore(str(temp_env), "char-start").read()
    assert _manifest_json(state, project=temp_env) == """{
  "schema_version": 1,
  "name": "char-start",
  "created_at": "<timestamp>",
  "last_accessed_at": "<timestamp>",
  "parent_session": null,
  "is_fork": false,
  "is_incognito": false,
  "worktree": {
    "path": "<project>",
    "branch": "char-start",
    "is_worktree": false,
    "owns_worktree": true
  },
  "intent": {
    "agent": "claude-code",
    "proxy": null,
    "subprocess_proxy": null,
    "launch": {
      "mode": "host",
      "sidecar": null,
      "direct_model": null,
      "runtime": "claude_code"
    },
    "system_prompt": null,
    "memory": null,
    "policy": null,
    "verification": null,
    "consumer_lanes": null
  },
  "overrides": {},
  "confirmed": {
    "claude_session_id": "<uuid>",
    "transcript_path": null,
    "started_with_proxy": null,
    "latest_plan_path": null,
    "artifacts": {},
    "policy": null,
    "verification": null,
    "compaction": null,
    "subagents": null,
    "is_sandboxed": false,
    "launch": null,
    "codex": null,
    "derivation": null,
    "claude_project_root": null,
    "consumer_lanes": null,
    "confirmed_at": null,
    "confirmed_by": null
  },
  "forge_root": "<project>"
}"""


def test_incognito_start_manifest_shape_and_cleanup(runner: CliRunner, temp_env: Path) -> None:
    """Pin the incognito manifest shape mid-launch and the op-owned delete-on-exit.

    Incognito rejects ``--no-launch`` (auto-delete-on-exit is its contract), so the
    manifest only exists during the launch window. Capture it from inside a mocked
    ``invoke_claude`` -- which the op reaches only after ``record_launch_confirmed``,
    so ``confirmed.launch`` and ``claude_project_root`` are populated here (both stay
    null in the ``--no-launch`` snapshots). Then assert the op's ``finally`` removed
    the manifest, guarding the incognito cleanup ownership that moved into
    ``start_claude_session``.
    """
    captured: dict[str, str] = {}

    def _capture_manifest(*_args: object, **_kwargs: object) -> int:
        captured["json"] = _manifest_json(SessionStore(str(temp_env), "char-incognito").read(), project=temp_env)
        return 0

    with patch("forge.cli.session.invoke_claude", side_effect=_capture_manifest):
        result = runner.invoke(main, ["session", "start", "char-incognito", "--incognito"])

    assert result.exit_code == 0, result.output
    assert captured["json"] == """{
  "schema_version": 1,
  "name": "char-incognito",
  "created_at": "<timestamp>",
  "last_accessed_at": "<timestamp>",
  "parent_session": null,
  "is_fork": false,
  "is_incognito": true,
  "worktree": {
    "path": "<project>",
    "branch": "char-incognito",
    "is_worktree": false,
    "owns_worktree": true
  },
  "intent": {
    "agent": "claude-code",
    "proxy": null,
    "subprocess_proxy": null,
    "launch": {
      "mode": "host",
      "sidecar": null,
      "direct_model": null,
      "runtime": "claude_code"
    },
    "system_prompt": null,
    "memory": null,
    "policy": null,
    "verification": null,
    "consumer_lanes": null
  },
  "overrides": {},
  "confirmed": {
    "claude_session_id": "<uuid>",
    "transcript_path": null,
    "started_with_proxy": null,
    "latest_plan_path": null,
    "artifacts": {},
    "policy": null,
    "verification": null,
    "compaction": null,
    "subagents": null,
    "is_sandboxed": false,
    "launch": {
      "routing_mode": "direct",
      "proxy_id": null,
      "base_url": null,
      "proxy_cost_baseline_micros": null,
      "proxy_cost_baseline_started_at": null,
      "api_key_available_to_child": true,
      "api_key_source": "env"
    },
    "codex": null,
    "derivation": null,
    "claude_project_root": "<project>",
    "consumer_lanes": null,
    "confirmed_at": null,
    "confirmed_by": null
  },
  "forge_root": "<project>"
}"""

    manifest_path = temp_env / ".forge" / "sessions" / "char-incognito" / "forge.session.json"
    assert not manifest_path.exists(), "incognito finally should delete the manifest on exit"


def test_fresh_resume_manifest_shape(runner: CliRunner, temp_env: Path) -> None:
    result = runner.invoke(main, ["session", "start", "char-start", "--no-launch"])
    assert result.exit_code == 0, result.output

    with patch("forge.cli.session_lifecycle._launch_claude_for_session", return_value=0):
        result = runner.invoke(main, ["session", "resume", "char-start", "--fresh", "--child-name", "char-child"])

    assert result.exit_code == 0, result.output
    state = SessionStore(str(temp_env), "char-child").read()
    assert _manifest_json(state, project=temp_env) == """{
  "schema_version": 1,
  "name": "char-child",
  "created_at": "<timestamp>",
  "last_accessed_at": "<timestamp>",
  "parent_session": "char-start",
  "is_fork": false,
  "is_incognito": false,
  "worktree": {
    "path": "<project>",
    "branch": "char-start",
    "is_worktree": false,
    "owns_worktree": true
  },
  "intent": {
    "agent": "claude-code",
    "proxy": null,
    "subprocess_proxy": null,
    "launch": {
      "mode": "host",
      "sidecar": null,
      "direct_model": null,
      "runtime": "claude_code"
    },
    "system_prompt": null,
    "memory": null,
    "policy": null,
    "verification": null,
    "consumer_lanes": null
  },
  "overrides": {},
  "confirmed": {
    "claude_session_id": "<uuid>",
    "transcript_path": null,
    "started_with_proxy": null,
    "latest_plan_path": null,
    "artifacts": {},
    "policy": null,
    "verification": null,
    "compaction": null,
    "subagents": null,
    "is_sandboxed": false,
    "launch": null,
    "codex": null,
    "derivation": {
      "parent_session": "char-start",
      "parent_transcript": null,
      "inherited_proxy": null,
      "resume_mode": "transfer",
      "strategy": "structured",
      "depth": 1,
      "resumed_at": "<timestamp>",
      "lineage": [
        "char-start"
      ],
      "context_file": ".forge/prev_sessions/char-start/children/char-child.md",
      "relocated_parent_session_id": null,
      "dropped_turns": null,
      "rewind_relocated_session_id": null,
      "parent_forge_root": "<project>",
      "parent_project_root": "<project>"
    },
    "claude_project_root": null,
    "consumer_lanes": null,
    "confirmed_at": null,
    "confirmed_by": null
  },
  "forge_root": "<project>"
}"""
