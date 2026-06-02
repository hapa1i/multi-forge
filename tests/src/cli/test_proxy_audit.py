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


def _write_drift(proxy_id="audit-test"):
    audit_logger.write_drift_record(
        request_id="r",
        proxy_id=proxy_id,
        dimension="system_prompt",
        previous_hash="sha256:aaaaaaaaaa",
        current_hash="sha256:bbbbbbbbbb",
        route=ROUTE,
    )


def _write_mutation(proxy_id="audit-test"):
    audit_logger.write_mutation_record(
        request_id="r",
        proxy_id=proxy_id,
        route=ROUTE,
        mutation={
            "blocked": False,
            "system_prompt_hash_before": "sha256:1111111111",
            "system_prompt_hash_after": "sha256:2222222222",
            "mutations": [
                {
                    "target": "system_prompt",
                    "action": "augment",
                    "augment_len": 12,
                    "cache_invalidation_expected": True,
                },
                {
                    "target": "thinking",
                    "action": "reasoning_pin",
                    "effort_floor": "high",
                    "budget_before": 100,
                    "budget_after": 10000,
                },
            ],
        },
    )


def test_audit_diff_empty():
    result = CliRunner().invoke(proxy, ["audit", "diff", "--period", "all"])
    assert result.exit_code == 0
    assert "No wire changes" in result.output


def test_audit_diff_shows_drift_and_mutation():
    _write_drift()
    _write_mutation()
    result = CliRunner().invoke(proxy, ["audit", "diff", "--period", "all"])
    assert result.exit_code == 0
    assert "drift" in result.output
    assert "mutation" in result.output
    assert "augment" in result.output
    assert "thinking pin" in result.output  # reasoning pin rendered


def test_audit_diff_json():
    _write_mutation()
    result = CliRunner().invoke(proxy, ["audit", "diff", "--period", "all", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert any(r["record_type"] == "mutation" for r in data)
