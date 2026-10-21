"""A parent cannot disappear while a child is prepared and published."""

from pathlib import Path

import pytest

import forge.session.manager as manager_module
from forge.session import ForgeSessionError, SessionManager, SessionStore

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("operation", ["start", "resume", "fork", "relaunch"])
def test_parent_cleanup_is_excluded_through_child_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    root = tmp_path / "project"
    (root / ".forge").mkdir(parents=True)
    (root / ".git").mkdir()
    monkeypatch.chdir(root)
    manager = SessionManager()
    manager.start_session("parent", worktree_path=str(root), direct=True)
    original = manager_module._publish_created_session
    attempts = []

    def publish(*args, **kwargs):
        with pytest.raises(ForgeSessionError, match="[Ww]orker|lease"):
            manager.delete_session("parent", forge_root=str(root), force=True)
        attempts.append("refused")
        return original(*args, **kwargs)

    monkeypatch.setattr(manager_module, "_publish_created_session", publish)
    if operation == "start":
        manager.start_session("child", worktree_path=str(root), parent_session="parent", direct=True)
    elif operation == "resume":
        manager.resume_session("parent", child_name="child", resume_mode="native", forge_root=str(root))
    elif operation == "fork":
        manager.fork_session("parent", "child", forge_root=str(root))
    else:
        manager.relaunch_session("parent", child_name="child", forge_root=str(root))
    assert attempts == ["refused"]
    assert SessionStore(str(root), "child").exists()
    with pytest.raises(ForgeSessionError, match="depend"):
        manager.delete_session("parent", forge_root=str(root), force=True)
