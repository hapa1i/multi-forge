"""Tests for `forge proxy audit show` CLI (Phase 2 audit proxy)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from forge.cli.proxy import proxy
from forge.proxy import audit_logger

ROUTE = {"template": "anthropic-passthrough", "provider": "litellm"}
SECRET_SYS = "secret system prompt PLAINTEXT"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    audit_logger._drift_state.clear()
    yield


def _write(proxy_id="audit-test", request_id="r"):
    audit_logger.write_metadata_record(
        request_id=request_id,
        proxy_id=proxy_id,
        mode="inspect",
        route=ROUTE,
        system_prompt_hash=audit_logger.hash_system_prompt(SECRET_SYS),
        tool_surface_hash=None,
        counts={"num_messages": 2, "num_tools": 1},
    )


def test_audit_show_empty():
    result = CliRunner().invoke(proxy, ["audit", "show", "--period", "all"])
    assert result.exit_code == 0
    assert "No audit data" in result.output


def test_audit_show_renders_metadata_no_secrets():
    _write()
    result = CliRunner().invoke(proxy, ["audit", "show", "--period", "all"])
    assert result.exit_code == 0
    assert "audit-test" in result.output
    assert "inspect" in result.output
    assert SECRET_SYS not in result.output  # plaintext is never shown


def test_audit_show_scopes_by_proxy():
    _write(proxy_id="p1", request_id="a")
    _write(proxy_id="p2", request_id="b")
    result = CliRunner().invoke(proxy, ["audit", "show", "p1", "--period", "all"])
    assert result.exit_code == 0
    assert "p1" in result.output
    assert "p2" not in result.output


def test_audit_show_json():
    _write()
    result = CliRunner().invoke(proxy, ["audit", "show", "--period", "all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["proxy_id"] == "audit-test"
    assert SECRET_SYS not in result.output
