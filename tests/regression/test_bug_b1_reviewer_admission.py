"""B1: old CLIs rejected isolation flags and auto-updates broke an exact version pin."""

import os
import subprocess
from time import monotonic
from unittest.mock import MagicMock, patch

import pytest

from forge.core.reactive.reviewer_runtime import (
    READ_ONLY_FLAGS,
    require_reviewer_runtime,
)
from forge.core.reactive.session_runner import run_claude_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "version,allowed", [("2.1.78", False), ("2.1.245", False), ("2.1.291", True), ("2.1.292", True)]
)
def test_version_and_flag_contract_survives_supported_updates(tmp_path, version, allowed):
    binary = tmp_path / "claude"
    binary.write_text("synthetic executable " + version)
    calls = []

    def probe(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, version if "--version" in argv else " ".join(READ_ONLY_FLAGS), "")

    with (
        patch("forge.core.reactive.reviewer_runtime.shutil.which", return_value=str(binary)),
        patch("forge.core.reactive.reviewer_runtime.run_guarded", side_effect=probe),
    ):
        for _ in range(2):
            if allowed:
                assert require_reviewer_runtime(env=dict(os.environ), deadline=monotonic() + 5) == str(binary)
            else:
                with pytest.raises(ValueError, match="claude update"):
                    require_reviewer_runtime(env=dict(os.environ), deadline=monotonic() + 5)
        assert len(calls) == (2 if allowed else 1)
        binary.write_text("updated executable " + version)
        if allowed:
            require_reviewer_runtime(env=dict(os.environ), deadline=monotonic() + 5)
            assert len(calls) == 4
    assert all("-p" not in argv for argv in calls)


def test_unsupported_reviewer_never_attempts_inference():
    with (
        patch(
            "forge.core.reactive.reviewer_runtime.require_reviewer_runtime", side_effect=ValueError("Run claude update")
        ),
        patch("forge.core.reactive.watchdog.run_guarded") as dispatch,
    ):
        result = run_claude_session("review", read_only=True)
    assert not result.dispatched
    assert "claude update" in result.error
    dispatch.assert_not_called()


@pytest.mark.parametrize("runtime", ["claude_code", "codex"])
def test_executor_resume_refuses_unavailable_reviewer_before_launch(tmp_path, runtime):
    from forge.core.ops.claude_session import launch_claude_session
    from forge.core.ops.codex_session import resolve_codex_session
    from forge.core.ops.session import ForgeOpError
    from forge.session import create_session_state
    from forge.session.models import PolicyIntent, SupervisorConfig

    state = create_session_state("worker", worktree_path=str(tmp_path), runtime=runtime)
    state.intent.policy = PolicyIntent(supervisor=SupervisorConfig(resume_id="planner"))
    with (
        patch(
            "forge.core.reactive.reviewer_runtime.preflight_supervisor_runtime",
            side_effect=ValueError("Run claude update before review"),
        ),
        pytest.raises(ForgeOpError, match="claude update"),
    ):
        if runtime == "codex":
            manager = MagicMock()
            manager.get_session.return_value = state
            resolve_codex_session(manager, state.name, forge_root=tmp_path)
        else:
            launch_claude_session(
                manifest=state,
                session_id=None,
                resume_id=None,
                effective_template=None,
                runtime_base_url=None,
                context_limit=None,
                use_sidecar=False,
            )
