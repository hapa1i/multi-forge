"""Session cleanup CLI uses immutable batch plans and keeps preview output scriptable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.cli.main import main
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.claude.paths import encode_project_path
from tests.fixtures.session_state import publish_session

THREAD = "01a12b5c-ce1a-72c2-ad3f-05d75f3fba00"


def seed(
    root: Path,
    name: str,
    *,
    parent: str | None = None,
    native: bool = False,
    incognito: bool = False,
):
    state = create_session_state(name, worktree_path=str(root), parent_session=parent)
    state.forge_root = str(root)
    state.is_incognito = incognito
    if native:
        state.confirmed.claude_session_id = THREAD
        state.confirmed.claude_project_root = str(root)
    publish_session(IndexStore(), state, root, forge_root=str(root))
    return state


def native_file(root: Path, home: Path):
    path = home / "projects" / encode_project_path(str(root)) / f"{THREAD}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": THREAD,
                "cwd": str(root),
                "version": "2.1.245",
            }
        )
        + "\n"
    )
    return path


@pytest.fixture
def stopped_native(monkeypatch, tmp_path):
    from forge.session import purge_native

    home = tmp_path / "native-claude"
    monkeypatch.setenv("CLAUDE_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.setattr(purge_native, "check_native_inactivity", lambda runtime: ())
    monkeypatch.setattr("forge.session.deletion.check_native_inactivity", lambda runtime: ())
    return home


def test_purge_empty_project_json(runner, temp_env):
    result = runner.invoke(main, ["session", "purge", "--all", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "schema_version": 1,
        "mode": "purge",
        "targets": [],
        "refused": [],
    }
    assert result.stderr == ""


@pytest.mark.parametrize(
    "args",
    [
        ["purge", "one", "--all"],
        ["purge", "--all", "--forge-root", "/missing"],
        ["purge", "one", "--json", "--yes"],
        ["purge", "one", "--forge-root", "relative"],
        ["delete", "one", "--keep-transcripts"],
        ["clean", "--older-than", "30", "--keep-transcripts"],
    ],
)
def test_cleanup_rejects_ambiguous_or_removed_options(runner, temp_env, args):
    result = runner.invoke(main, ["session", *args])
    assert result.exit_code == 2
    assert "Error:" in result.stderr


def test_purge_all_requires_project(runner, temp_env, monkeypatch):
    monkeypatch.chdir(temp_env.parent)
    result = runner.invoke(main, ["session", "purge", "--all"])
    assert result.exit_code == 2
    assert "requires being inside a Forge project" in result.stderr


def test_purge_preview_is_read_only_and_labels_exact_native_file(runner, temp_env, stopped_native):
    seed(temp_env, "subject", native=True)
    path = native_file(temp_env, stopped_native)
    index_path = IndexStore().index_path
    before = index_path.read_bytes(), index_path.stat().st_mtime_ns, path.read_bytes()
    result = runner.invoke(main, ["session", "purge", "subject", "--json", "--keep-worktree"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["targets"][0]["native"]["files"][0]["path"] == str(path)
    assert payload["targets"][0]["refusals"] == []
    assert (
        index_path.read_bytes(),
        index_path.stat().st_mtime_ns,
        path.read_bytes(),
    ) == before
    assert SessionStore(str(temp_env), "subject").exists()


def test_delete_keeps_native_and_removes_forge_artifacts(runner, temp_env, stopped_native):
    seed(temp_env, "subject", native=True)
    path = native_file(temp_env, stopped_native)
    content = path.read_bytes()
    artifact = temp_env / ".forge/artifacts/subject/transcripts/copy.jsonl"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    result = runner.invoke(main, ["session", "delete", "subject", "--yes", "--keep-worktree"])
    assert result.exit_code == 0, result.output
    assert path.read_bytes() == content
    assert not artifact.exists()
    assert not SessionStore(str(temp_env), "subject").exists()


def test_purge_apply_removes_native_and_forge_record(runner, temp_env, stopped_native):
    seed(temp_env, "subject", native=True)
    path = native_file(temp_env, stopped_native)
    result = runner.invoke(main, ["session", "purge", "subject", "--yes", "--keep-worktree"])
    assert result.exit_code == 0, result.output
    assert not path.exists()
    assert not SessionStore(str(temp_env), "subject").exists()


def test_delete_cancel_keeps_previewed_state(runner, temp_env):
    seed(temp_env, "subject")
    index = IndexStore().index_path
    before = index.read_bytes(), index.stat().st_mtime_ns
    result = runner.invoke(main, ["session", "delete", "subject", "--keep-worktree"], input="n\n")
    assert result.exit_code == 0, result.output
    assert "Cancelled" in result.stderr
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert SessionStore(str(temp_env), "subject").exists()


def test_purge_batch_refusal_is_not_readmitted_after_child_deleted(runner, temp_env, stopped_native):
    seed(temp_env, "parent")
    seed(temp_env, "child", parent="parent")
    result = runner.invoke(main, ["session", "purge", "--all", "--yes", "--keep-worktree"])
    assert result.exit_code == 1, result.output
    assert "child" in result.output
    assert SessionStore(str(temp_env), "parent").exists()
    assert not SessionStore(str(temp_env), "child").exists()


def test_purge_json_refusals_stay_on_stdout(runner, temp_env, stopped_native):
    seed(temp_env, "parent")
    seed(temp_env, "child", parent="parent")
    result = runner.invoke(main, ["session", "purge", "parent", "--json", "--keep-worktree"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert "child" in str(payload["targets"][0]["refusals"])
    assert "refused or failed" in result.stderr


def test_purge_all_ignores_other_projects_and_includes_incognito(runner, temp_env, stopped_native, tmp_path):
    seed(temp_env, "inside", incognito=True)
    other = tmp_path / "other-project"
    other.mkdir()
    (other / ".forge").mkdir()
    seed(other, "outside")
    result = runner.invoke(main, ["session", "purge", "--all", "--json", "--keep-worktree"])
    assert result.exit_code == 0, result.output
    assert [item["name"] for item in json.loads(result.stdout)["targets"]] == ["inside"]
