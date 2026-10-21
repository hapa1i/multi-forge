"""Offline CLI lifecycle checks isolated through the standard Docker fixture.

These tests never invoke a model. Native bytes are explicitly synthetic; the
separately approved probe captures real Claude bytes after this offline gate.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.claude.paths import encode_project_path
from forge.session.purge_native import check_native_inactivity
from tests.fixtures.docker import ContainerLike, DockerContainer
from tests.fixtures.session_state import publish_session

pytestmark = [pytest.mark.integration, pytest.mark.docker_in]
NATIVE_ID = "aaaa1111-2222-4333-8444-555555555555"


@pytest.fixture
def container_case_completed(
    request: pytest.FixtureRequest, synced_container: ContainerLike, local_claude_available: bool
) -> bool:
    """Delegate host collection; run the assertions directly when already in the test image."""
    if local_claude_available:
        assert Path("/.dockerenv").is_file(), "Native lifecycle checks require a Docker process namespace"
        return False
    assert isinstance(synced_container, DockerContainer), "Host collection must use the Docker fixture"
    node = f"tests/integration/docker/test_session_delete_purge_lifecycle.py::{request.node.name}"
    result = synced_container.exec(
        f"cd /forge && PYTHON_DOTENV_DISABLED=1 /forge/.venv/bin/python -m pytest -q {shlex.quote(node)}"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return True


def _fixture(root: Path, name: str, native_home: Path, *, parent: str | None = None) -> Path:
    state = create_session_state(name, worktree_path=str(root), parent_session=parent)
    state.forge_root = str(root)
    state.confirmed.claude_project_root = str(root)
    state.confirmed.claude_session_id = NATIVE_ID if parent is None else None
    publish_session(IndexStore(), state, root, forge_root=root)
    native = native_home / "projects" / encode_project_path(str(root)) / f"{NATIVE_ID}.jsonl"
    native.parent.mkdir(parents=True, exist_ok=True)
    native.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": NATIVE_ID,
                "cwd": str(root),
                "version": "2.1.245",
            }
        )
        + "\n"
    )
    return native


def test_cancel_delete_then_purge_exact_native_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, container_case_completed: bool
) -> None:
    if container_case_completed:
        return
    root, home = tmp_path / "project", tmp_path / "native"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    native = _fixture(root, "delete-me", home)
    original = native.read_bytes()
    artifact = root / ".forge/artifacts/delete-me/transcripts/native.jsonl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(original)
    index = IndexStore().index_path
    before = index.read_bytes(), index.stat().st_mtime_ns
    runner = CliRunner()
    cancelled = runner.invoke(main, ["session", "delete", "delete-me", "--keep-worktree"], input="n\n")
    assert cancelled.exit_code == 0, cancelled.output
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert artifact.exists() and native.read_bytes() == original
    deleted = runner.invoke(main, ["session", "delete", "delete-me", "--yes", "--keep-worktree"])
    assert deleted.exit_code == 0, deleted.output
    assert not artifact.exists() and native.read_bytes() == original
    assert not SessionStore(str(root), "delete-me").exists()
    _fixture(root, "purge-me", home)
    sentinel = native.with_name("unrelated.txt")
    sentinel.write_text("retain")
    preview = runner.invoke(main, ["session", "purge", "purge-me", "--json", "--keep-worktree"])
    assert preview.exit_code == 0, preview.output
    selected = json.loads(preview.stdout)["targets"][0]["native"]["files"]
    assert [item["path"] for item in selected] == [str(native)]
    applied = runner.invoke(main, ["session", "purge", "purge-me", "--yes", "--keep-worktree"])
    assert applied.exit_code == 0, applied.output
    assert not native.exists() and sentinel.read_text() == "retain"


def test_inactive_child_refuses_parent_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, container_case_completed: bool
) -> None:
    if container_case_completed:
        return
    root, home = tmp_path / "project", tmp_path / "native"
    root.mkdir()
    monkeypatch.chdir(root)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    native = _fixture(root, "parent", home)
    _fixture(root, "child", home, parent="parent")
    result = CliRunner().invoke(main, ["session", "delete", "parent", "--yes", "--keep-worktree"])
    assert result.exit_code == 1 and "child" in result.output
    assert native.exists()
    assert SessionStore(str(root), "parent").exists()


def test_real_process_census_refuses_unmanaged_client(container_case_completed: bool) -> None:
    if container_case_completed:
        return
    # argv[0] represents a native client without executing Claude or spending tokens.
    process = subprocess.Popen(
        ["claude", "-c", "import time; time.sleep(30)"],
        executable=sys.executable,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert any(str(process.pid) in reason for reason in check_native_inactivity("claude"))
    finally:
        process.terminate()
        process.wait(timeout=5)
