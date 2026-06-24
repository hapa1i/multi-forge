"""Stream-ownership guard: read leaves keep ``--json`` on stdout with clean stderr.

Slice 07 (forge_cli_cleanup): results and every ``--json`` payload go to stdout;
diagnostics go to stderr. Click 8.3 removed ``CliRunner(mix_stderr=...)`` -- the
plain runner already separates ``result.stdout`` / ``result.stderr``.

Covers the leaves that previously split their streams (``proxy audit`` rendered
its human table to stderr) plus the already-compliant telemetry leaves, so a
regression in either direction red-tests here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main

# --json success paths that need no seeded data: empty logs still yield valid JSON.
_JSON_STDOUT_LEAVES = [
    ["telemetry", "costs", "show", "--json"],
    ["telemetry", "trace", "list", "--json"],
    ["proxy", "audit", "show", "--json"],
    ["proxy", "audit", "diff", "--json"],
]


@pytest.mark.parametrize("args", _JSON_STDOUT_LEAVES, ids=lambda a: " ".join(a))
def test_json_payload_on_stdout_with_clean_stderr(args: list[str]) -> None:
    """``--json`` emits parseable JSON on stdout and writes nothing to stderr."""
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)  # raises if stdout is not pure JSON
    assert result.stderr == ""


def test_activity_json_on_stdout_when_seeded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seeded ``telemetry activity --json`` emits JSON on stdout, clean stderr.

    Bare invocation exits 1 (no session resolves in an isolated home), so seed the
    resolver + summary to exercise the success branch (``console.print_json``).
    """
    monkeypatch.setattr(
        "forge.cli.activity.resolve_session_identifier",
        lambda session: ("seeded-session", Path.cwd()),
    )
    monkeypatch.setattr(
        "forge.cli.activity.build_session_activity_summary",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "forge.cli.activity.activity_summary_to_json",
        lambda summary: {"session": "seeded-session", "operations": []},
    )

    result = CliRunner().invoke(main, ["telemetry", "activity", "seeded-session", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["session"] == "seeded-session"
    assert result.stderr == ""


def _seed_audit_logs(monkeypatch: pytest.MonkeyPatch, records: list[dict]) -> None:
    # audit_show/diff import read_audit_logs lazily from the source module, so the
    # patch must target the source attribute, not forge.cli.proxy_audit.
    monkeypatch.setattr("forge.proxy.audit_logger.read_audit_logs", lambda *a, **k: list(records))


def test_audit_show_human_table_on_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The human audit table lands on stdout (Slice 07 flipped the shared console off stderr)."""
    _seed_audit_logs(
        monkeypatch,
        [
            {
                "record_type": "request",
                "ts": "2026-01-01T00:00:00Z",
                "proxy_id": "audit-test",
                "mode": "inspect",
                "system_prompt_hash": "sha256:abcdef0123456789",
                "tool_surface_hash": "sha256:9876543210fedcba",
                "counts": {"num_messages": 2, "num_tools": 1},
            }
        ],
    )
    result = CliRunner().invoke(main, ["proxy", "audit", "show", "--period", "all"])
    assert result.exit_code == 0, result.output
    assert "Audit" in result.stdout
    assert "audit-test" in result.stdout
    assert result.stderr == ""


def test_audit_diff_human_table_on_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The human wire-changes table lands on stdout."""
    _seed_audit_logs(
        monkeypatch,
        [
            {
                "record_type": "drift",
                "ts": "2026-01-01T00:00:00Z",
                "proxy_id": "audit-test",
                "dimension": "system_prompt",
                "previous_hash": "sha256:aaaaaaaaaaaa",
                "current_hash": "sha256:bbbbbbbbbbbb",
            }
        ],
    )
    result = CliRunner().invoke(main, ["proxy", "audit", "diff", "--period", "all"])
    assert result.exit_code == 0, result.output
    assert "Wire changes" in result.stdout
    assert "audit-test" in result.stdout
    assert result.stderr == ""
