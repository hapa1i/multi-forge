"""Fresh resume mixed a historical proxy template with the current intent URL.

After a direct resume cleared intent.proxy, manager._create_resume_child raised
instead of deriving a direct child. Native and transfer paths shared the defect.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.models import ProxyIntent, StartedWithProxy
from tests.fixtures.session_state import publish_session
from tests.src.cli.session_command_support import successful_claude_launch

pytestmark = pytest.mark.regression


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / ".forge").mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("COLUMNS", "500")
    return root


@pytest.mark.parametrize("resume_mode", ["native", "transfer"])
def test_fresh_direct_resume_after_clearing_proxy(project: Path, resume_mode: str) -> None:
    state = create_session_state(
        "parent", worktree_path=str(project), proxy_template="litellm-openai", proxy_base_url="http://localhost:8084"
    )
    state.confirmed.claude_session_id = "parent-conversation"
    state.confirmed.confirmed_by = "hook:SessionStart:startup"
    state.confirmed.started_with_proxy = StartedWithProxy(
        template="litellm-openai", base_url="http://localhost:8084", proxy_id="old-proxy"
    )
    publish_session(IndexStore(), state, project)
    runner = CliRunner()
    with successful_claude_launch():
        first = runner.invoke(main, ["session", "resume", "parent", "--no-proxy"])
    assert first.exit_code == 0, first.output
    parent = SessionStore(str(project), "parent")
    assert parent.read().intent.proxy is None
    assert parent.read().confirmed.started_with_proxy == state.confirmed.started_with_proxy
    before = parent.manifest_path.read_bytes()

    with successful_claude_launch() as launch:
        result = runner.invoke(
            main,
            [
                "session",
                "resume",
                "parent",
                "--fresh",
                "--no-proxy",
                "--child-name",
                "child",
                "--resume-mode",
                resume_mode,
            ],
        )

    assert result.exit_code == 0, result.output
    assert launch.call_count == 1
    child = SessionStore(str(project), "child").read()
    assert child.intent.proxy is None
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.inherited_proxy == "litellm-openai"
    assert parent.manifest_path.read_bytes() == before


@pytest.mark.parametrize("resume_mode", ["native", "transfer"])
def test_fresh_resume_keeps_proxy_pair_from_intent(project: Path, resume_mode: str) -> None:
    state = create_session_state(
        "parent", worktree_path=str(project), proxy_template="new-template", proxy_base_url="http://localhost:8090"
    )
    state.confirmed.claude_session_id = "parent-conversation"
    state.confirmed.confirmed_by = "hook:SessionStart:startup"
    state.confirmed.started_with_proxy = StartedWithProxy(
        template="old-template", base_url="http://localhost:8084", proxy_id="old-proxy"
    )
    publish_session(IndexStore(), state, project)

    child, _ = SessionManager().resume_session("parent", child_name="child", resume_mode=resume_mode)

    assert child.intent.proxy == ProxyIntent("new-template", "http://localhost:8090")
    assert child.confirmed.derivation is not None
    assert child.confirmed.derivation.inherited_proxy == "old-template"
