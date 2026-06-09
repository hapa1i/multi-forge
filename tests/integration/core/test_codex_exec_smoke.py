"""Real-codex end-to-end smoke (Phase 5b).

Spawns the host ``codex exec --json`` binary ONCE to validate the full stack that the
hermetic unit tests can only mock: ``prepare_codex_request`` -> ``CodexHeadlessInvoker``
(shared lifecycle) -> real ``codex exec`` -> ``parse_codex_jsonl_stream`` ->
``emit_codex_usage``. CLAUDE.md mandates an integration test for any path that spawns a
real subprocess.

Billed: uses a trivial prompt and a ``read-only`` sandbox. Never skips -- fails loudly
if ``codex`` is not installed/authenticated (the project's no-skip policy).

Run via: ``./scripts/test-integration.sh tests/integration/core/test_codex_exec_smoke.py -v``
or ``uv run pytest -m slow tests/integration/core/test_codex_exec_smoke.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from forge.core.invoker import Attribution, CodexHeadlessInvoker, prepare_codex_request
from forge.core.runtime.codex_preflight import CodexPreflight, preflight_codex
from forge.core.usage.ledger import read_usage_events

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _require_codex_ready() -> CodexPreflight:
    pf = preflight_codex()
    if not pf.ready:
        pytest.fail(f"codex not ready ({pf.blocking_reason}). Install + authenticate codex, then re-run.")
    return pf


def _init_git_repo(path: Path) -> None:
    """codex exec refuses to run outside a git repo without --skip-git-repo-check; a
    real session worktree is always a git repo, so mirror that instead of bypassing it."""
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "smoke@test.local"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "smoke"], cwd=path, check=True)


def test_codex_exec_smoke_parses_text_tokens_and_emits_event(tmp_path: Path) -> None:
    pf = _require_codex_ready()
    _init_git_repo(tmp_path)

    req = prepare_codex_request(
        prompt="reply with the single word OK",
        preflight=pf,
        attribution=Attribution(command="smoke", session="codex-smoke"),
        sandbox="read-only",  # trivial reply needs no writes
        cwd=str(tmp_path),
        timeout_seconds=120,
        label="smoke",
    )
    run_id = req.env["FORGE_RUN_ID"]  # minted by prepare_codex_request

    result = CodexHeadlessInvoker().run(req)

    assert result.success, f"rc={result.returncode} error={result.error} stderr={result.stderr!r}"
    assert not result.runtime_is_error
    assert "OK" in result.stdout
    # The JSONL turn.completed.usage was lifted onto the result.
    assert result.input_tokens is not None and result.input_tokens > 0
    assert result.output_tokens is not None

    # Exactly one runtime_native usage event for this run, tokens but no cost.
    events = [e for e in read_usage_events() if e.run_id == run_id]
    assert len(events) == 1, events
    e = events[0]
    assert e.route == "codex_exec"
    assert e.reporter == "codex_jsonl"
    assert e.measurement_source == "runtime_native"
    assert e.confidence == "unavailable"
    assert e.cost_micro_usd is None and e.source_refs is None
    assert e.input_tokens == result.input_tokens
