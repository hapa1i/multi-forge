"""An encoded Claude project symlink must not grant cleanup ownership of outside logs."""

from pathlib import Path

import pytest

from forge.session.claude.cleanup import cleanup_session
from forge.session.claude.paths import encode_project_path

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("nested", [False, True])
def test_cleanup_preserves_logs_behind_encoded_project_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool
) -> None:
    native_projects = tmp_path / "claude" / "projects"
    native_projects.mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_HOME", str(native_projects.parent))
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    session_id = "abcabcab-3333-4333-8333-abcabcabcabc"
    log = external / session_id / "subagents" / "agent-test.jsonl" if nested else external / "agent-test.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(f'{{"sessionId": "{session_id}"}}\n')
    (native_projects / encode_project_path(str(project))).symlink_to(external, target_is_directory=True)

    result = cleanup_session(str(project), session_id)

    assert log.exists()
    assert result.deleted_agent_logs == []
