"""Real hook processes and Git capture with synthetic input and a recording reviewer stub."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from forge.policy.semantic import stop_review
from tests.fixtures.stop_review import context

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("failure_at", ["never", "start", "stop"])
def test_hook_lifecycle_preserves_global_ignores(tmp_path: Path, failure_at: str) -> None:
    ctx = context(tmp_path)
    rules, config, sent = (tmp_path / name for name in ("global-ignore", "gitconfig", "reviewer-input.jsonl"))
    rules.write_text(".env\n")
    config.write_text(f'[core]\nexcludesFile = "{rules}"\n')
    private = ctx.checkout / ".env"
    private.write_text("SYNTHETIC_IGNORED_BEFORE\n")
    driver = tmp_path / "hook-driver.py"
    # Admission and the reviewer are stubbed; CLI routing, session resolution,
    # action capture, Git config, journals and Stop reservation are real.
    driver.write_text(textwrap.dedent("""\
            import json
            import os
            from unittest.mock import patch
            from forge.cli.main import main
            from forge.policy.semantic.supervisor import SupervisorRun
            from forge.policy.types import PolicyDecision

            def record(config, action, **kwargs):
                with open(os.environ['FIXTURE_REVIEW_INPUT'], 'a') as stream:
                    stream.write(json.dumps(action.raw_diff) + '\\n')
                return SupervisorRun(PolicyDecision('allow', 'semantic.supervisor'), run_ok=True, parsed=True)

            with (
                patch('forge.cli.hooks.codex_stop.stop_review_supported', return_value=True),
                patch('forge.core.runtime.codex_turn_enrollment.verified', return_value=True),
                patch('forge.core.runtime.codex_turn_enrollment.observe', return_value=False),
                patch('forge.policy.semantic.stop_review.run_supervisor_check', side_effect=record),
            ):
                main()
            """))
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=str(config),
        GIT_CONFIG_NOSYSTEM="1",
        FORGE_SESSION=ctx.session,
        FORGE_FORGE_ROOT=str(ctx.forge_root),
        FORGE_CODEX_EXECUTOR_IDENTITY="{}",
        FIXTURE_REVIEW_INPUT=str(sent),
        PYTHON_DOTENV_DISABLED="1",
    )

    def invoke(command: str, event: str, **kwargs) -> dict:
        result = subprocess.run(
            [sys.executable, str(driver), "hook", command],
            input=json.dumps(
                dict(
                    hook_event_name=event,
                    session_id=ctx.thread_id,
                    turn_id=ctx.turn_id,
                    cwd=str(ctx.checkout),
                    **kwargs,
                )
            ),
            cwd=ctx.checkout,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else {}

    if failure_at == "start":
        config.write_text("[invalid\n")
    invoke("codex-turn-start", "UserPromptSubmit")
    fields = dict(tool_name="exec_command", tool_use_id="tool-one", tool_input={"cmd": "./synthetic-task"})
    invoke("codex-policy-check", "PreToolUse", **fields)
    (ctx.checkout / "work.txt").write_text("visible work\n")
    (ctx.checkout / "new.txt").write_text("visible addition\n")
    private.write_text("SYNTHETIC_IGNORED_AFTER\n")
    invoke("codex-turn-tool", "PostToolUse", tool_response="Exit code 0", **fields)
    if failure_at == "stop":
        config.write_text("[invalid\n")
    wire = invoke("codex-stop", "Stop", stop_hook_active=False)
    if failure_at != "never":
        assert not sent.exists()
        assert "unavailable" in wire["systemMessage"].lower()
        return
    assert stop_review.status(ctx.forge_root, ctx.session)["state"] == "reviewed"
    invoke("codex-stop", "Stop", stop_hook_active=True)
    lines = sent.read_text().splitlines()
    assert len(lines) == 1
    outgoing = json.loads(lines[0])
    assert "visible work" in outgoing and "visible addition" in outgoing
    assert "SYNTHETIC_IGNORED" not in outgoing and '".env"' not in outgoing
    for path in ctx.storage.iterdir():
        if path.suffix in {".blob", ".snapshot"}:
            assert b"SYNTHETIC_IGNORED" not in path.read_bytes()
