"""Real-runtime smoke tests for Codex and mixed workflow worker fan-out.

These tests use the host ChatGPT Codex login and keep Codex in its read-only sandbox. The
mixed case also uses the host direct-Claude credential. Run through ``test-integration.sh``
so the same integration prerequisites and isolation fixtures apply as the rest of the suite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.usage.ledger import read_usage_events

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _run_panel(cwd: Path, models: str) -> dict[str, Any]:
    result = CliRunner().invoke(
        main,
        [
            "workflow",
            "panel",
            "-p",
            "Reply with one short sentence confirming this workflow worker ran.",
            "--models",
            models,
            "--timeout",
            "180",
            "--cwd",
            str(cwd),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["failed"] == 0, payload
    return payload


def test_one_codex_worker_panel_produces_synthesis_text_and_runtime_event(
    codex_ready_cached: CodexPreflight,
    codex_git_forge_root: Path,
) -> None:
    assert codex_ready_cached.billing_mode == "subscription_quota"

    payload = _run_panel(codex_git_forge_root, "codex")

    assert payload["successful"] == 1
    result = payload["results"]["codex"]
    assert result["success"] is True
    assert isinstance(result["response"], str) and result["response"].strip()
    workers = [event for event in read_usage_events(command="panel") if event.attribution_granularity == "worker"]
    assert len(workers) == 1
    assert workers[0].runtime == "codex"
    assert workers[0].route == "codex_exec"
    assert workers[0].status == "success"


def test_mixed_direct_claude_and_codex_panel_preserves_order_and_runtime_events(
    codex_ready_cached: CodexPreflight,
    codex_git_forge_root: Path,
) -> None:
    assert codex_ready_cached.ready

    payload = _run_panel(codex_git_forge_root, "claude-opus,codex")

    assert payload["successful"] == 2
    assert list(payload["results"]) == ["claude-opus", "codex"]
    assert all(item["success"] for item in payload["results"].values())
    workers = [event for event in read_usage_events(command="panel") if event.attribution_granularity == "worker"]
    assert len(workers) == 2
    assert {event.runtime for event in workers} == {"claude_code", "codex"}
    assert all(event.status == "success" for event in workers)
