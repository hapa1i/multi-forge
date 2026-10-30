from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.ops.session import ForgeOpError


def test_session_model_group_has_only_the_two_read_leaves() -> None:
    result = CliRunner().invoke(main, ["session", "model", "--help"])

    assert result.exit_code == 0
    assert "show" in result.output
    assert "history" in result.output

    missing_alias = CliRunner().invoke(main, ["session", "route", "--help"])
    assert missing_alias.exit_code != 0
    assert "No such command 'route'" in missing_alias.stderr


@pytest.mark.parametrize("session_name", [None, "planner"])
def test_session_model_show_forwards_omitted_or_explicit_target(
    monkeypatch: pytest.MonkeyPatch, session_name: str | None
) -> None:
    seen: list[str | None] = []

    def model_report(**kwargs: Any) -> SimpleNamespace:
        seen.append(kwargs["session_name"])
        return SimpleNamespace(to_dict=lambda: {"schema_version": 1, "session": "planner"})

    monkeypatch.setattr(
        "forge.cli.session_model.get_session_model_report",
        model_report,
    )
    argv = ["session", "model", "show", "--json"]
    if session_name is not None:
        argv.insert(3, session_name)

    result = CliRunner().invoke(main, argv)

    assert result.exit_code == 0
    assert json.loads(result.stdout)["session"] == "planner"
    assert seen == [session_name]


def test_session_model_read_error_uses_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "forge.cli.session_model.get_session_model_report",
        lambda **_kwargs: (_ for _ in ()).throw(ForgeOpError("routing journal is malformed")),
    )

    result = CliRunner().invoke(main, ["session", "model", "show", "planner", "--json"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "routing journal is malformed" in result.stderr


def test_session_model_history_human_output_keeps_ids_slots_and_limitations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event: dict[str, Any] = {
        "timestamp": "2026-08-22T12:00:00Z",
        "event_id": "sevt_0123456789abcdef0123456789abcdef",
        "event_type": "launch_routing_committed",
        "run_id": "run_0123456789ab",
        "outcome": "success",
        "payload": {
            "route": {"kind": "direct"},
            "marking_snapshots": [
                {
                    "slot": "direct",
                    "tier": None,
                    "request_model": None,
                    "route_model": "claude-opus-5",
                }
            ],
        },
    }
    monkeypatch.setattr(
        "forge.cli.session_model.get_session_model_history_report",
        lambda **_kwargs: SimpleNamespace(
            to_dict=lambda: {
                "schema_version": 1,
                "session": "planner",
                "history_status": "supported",
                "events": [event],
            }
        ),
    )

    result = CliRunner().invoke(
        main,
        ["session", "model", "history", "planner"],
        terminal_width=300,
    )

    assert result.exit_code == 0
    assert event["event_id"] in result.output
    assert event["run_id"] in result.output
    assert "direct=claude-opus-5" in result.output
    assert "route commitment only" in result.output


@pytest.mark.parametrize("surface", ["human", "json", "direct"])
def test_session_model_effort_explains_distinct_resolution_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, surface: str
) -> None:
    from forge.cli.hooks import hooks

    monkeypatch.chdir(tmp_path)
    observation = {
        "tier": "opus",
        "tier_source": "header",
        "client_model": "gemini-4-argon",
        "mapped_model": "gemini/gemini-4-argon",
        "requested": "max",
        "thinking": "between_tools",
        "opt_in": True,
        "client_applicable": False,
        "derived": "none",
        "floor": "high",
        "pre_clamp": "high",
        "supported": ["low", "medium", "high"],
        "resolved": "high",
        "source": "floor",
        "applied": "high",
        "wire": "thinkingConfig.thinkingLevel",
        "note": None,
        "observed_at": "2026-10-30T12:00:00Z",
    }
    payload = {
        "session": "planner",
        "runtime": "claude_code",
        "active": True,
        "route_intent": {"kind": "proxy"},
        "route_commit": {"kind": "proxy", "evidence_source": "route_commit"},
        "live_proxy": {"evidence_source": "runtime", "default_tier": "sonnet"},
        "history_status": "supported",
        "marking": {"launch_entries": [], "live_proxy_entries": []},
        "effort": {
            "status": "observed",
            "reason": None,
            "launch_id": "run_0123456789ab",
            "backend_id": "litellm",
            "observations": {"opus": observation},
        },
        "limitations": ["effort describes Forge's outbound parameter, not provider-side execution"],
    }

    def report(**_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(to_dict=lambda: payload)

    monkeypatch.setattr("forge.cli.session_model.get_session_model_report", report)
    monkeypatch.setattr("forge.core.ops.session_model.get_session_model_report", report)
    if surface == "direct":
        result = CliRunner().invoke(
            hooks,
            ["user-prompt-submit"],
            input=json.dumps({"prompt": "%session model show"}),
        )
        output = json.loads(result.stdout)["reason"]
    else:
        arguments = ["session", "model", "show"] + (["--json"] if surface == "json" else [])
        result = CliRunner().invoke(main, arguments, terminal_width=300)
        output = result.stdout
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    if surface == "json":
        assert json.loads(output)["effort"]["observations"]["opus"] == observation
    else:
        assert "opt-in: yes; applicable: no; used: no" in output
        for field in (
            "derived",
            "minimum",
            "pre-clamp",
            "supported",
            "tier source",
            "wire",
            "model",
        ):
            assert f"Opus {field}" in output
        assert "thinkingConfig.thinkingLevel" in output
        assert "gemini/gemini-4-argon" in output
        assert "not provider-side execution" in output
