"""Regression: walkthrough cleanup must target only fixed owned resources."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from forge.install.models import (
    Installation,
    InstalledFile,
    InstalledManifest,
    ModuleOwner,
)
from forge.install.tracking import TrackingStore, compute_checksum
from forge.session import IndexStore, SessionStore, create_session_state
from tests.fixtures.session_state import (
    publish_session_from_fields,
    seed_row_only_session,
)

pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "src/skills/walkthrough/scripts"


def _write_answering_python(fake_bin: Path) -> None:
    """Let a fake Forge launcher expose the interpreter used by this test run."""

    python = fake_bin / "python"
    python.write_text(
        f'#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} "$@"\n',
        encoding="utf-8",
    )
    python.chmod(0o755)


def _setup_walkthrough(
    tmp_path: Path,
    *,
    target: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[Path, dict[str, str]]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    requested_target = target or (tmp_path / "walkthrough")
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(requested_target)
    if extra_env:
        env.update(extra_env)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr
    return requested_target.resolve(), env


def _run_runtime_cleanup(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "runtime",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _run_extensions_cleanup(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "extensions",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _valid_progress_state(*, sidecar_may_exist: str = "false") -> dict[str, object]:
    return {
        "schema_version": 2,
        "checklist_version": "2.0.0",
        "mode": "walkthrough",
        "started_at": "2026-09-02T00:00:00+00:00",
        "last_updated": "2026-09-02T00:00:00+00:00",
        "current_step": "0.1",
        "vars": {"SIDECAR_MAY_EXIST": sidecar_may_exist},
        "steps": {},
    }


def test_cleanup_ignores_a_fixed_name_session_from_a_sibling_root(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    publish_session_from_fields(
        index,
        "walkthrough-demo",
        sibling,
        sibling,
        forge_root=sibling,
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "forge-calls.log"
    forge = fake_bin / "forge"
    forge.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$WALKTHROUGH_FAKE_LOG"
if [[ "$1 $2" == "proxy list" ]]; then
  printf '%s\\n' '[]'
else
  exit 99
fi
""",
        encoding="utf-8",
    )
    forge.chmod(0o755)
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_FAKE_LOG"] = str(log)

    result = _run_runtime_cleanup(env)

    assert result.returncode == 0, result.stderr
    assert "session delete walkthrough-demo" not in log.read_text(encoding="utf-8")
    assert target.is_dir()


def test_cleanup_preserves_foreign_row_only_session_index_evidence(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    residue = create_session_state("foreign-row-only", worktree_path=str(foreign_root))
    residue.forge_root = str(foreign_root)
    # This deliberately models crash residue: cleanup must not repair an
    # unrelated row merely while proving ownership of fixed walkthrough names.
    seed_row_only_session(index, residue, foreign_root, forge_root=foreign_root)
    before = index.index_path.read_bytes()

    result = _run_runtime_cleanup(env)

    assert result.returncode == 0, result.stderr
    assert index.index_path.read_bytes() == before


def test_cleanup_preserves_foreign_artifacts_and_rebuilds_their_search_index(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    transcript = (
        '{"requestId":"r1","timestamp":"2026-01-01T00:00:00Z",'
        '"message":{"role":"user","content":[{"type":"text","text":"preserve foreign evidence"}]}}\n'
    )
    owned = target / ".forge/artifacts/walkthrough-demo/transcripts/owned.jsonl"
    foreign = target / ".forge/artifacts/foreign-session/transcripts/foreign.jsonl"
    owned.parent.mkdir(parents=True)
    foreign.parent.mkdir(parents=True)
    owned.write_text(transcript.replace("foreign", "owned"), encoding="utf-8")
    foreign.write_text(transcript, encoding="utf-8")
    initial_index = subprocess.run(
        ["bash", str(SCRIPTS / "run-in-repo.sh"), "forge", "search", "rebuild-index"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert initial_index.returncode == 0, initial_index.stderr

    result = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not owned.exists()
    assert foreign.read_text(encoding="utf-8") == transcript
    documents = json.loads((target / ".forge/search-index/documents.json").read_text(encoding="utf-8"))["documents"]
    assert [row["session_name"] for row in documents] == ["foreign-session"]


@pytest.mark.parametrize(
    "mount_inventory",
    [
        [],
        [
            {"Source": "/first/project", "Destination": "/workspace"},
            {"Source": "/second/project", "Destination": "/workspace"},
        ],
    ],
    ids=["missing", "ambiguous"],
)
def test_cleanup_refuses_a_fixed_name_container_without_one_workspace_mount(
    tmp_path: Path,
    mount_inventory: list[dict[str, str]],
) -> None:
    _, env = _setup_walkthrough(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    forge = fake_bin / "forge"
    forge.write_text(
        """#!/usr/bin/env bash
if [[ "$1 $2" == "session list" || "$1 $2" == "proxy list" ]]; then
  printf '%s\\n' '[]'
else
  exit 99
fi
""",
        encoding="utf-8",
    )
    forge.chmod(0o755)
    _write_answering_python(fake_bin)
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$WALKTHROUGH_DOCKER_LOG"
case "$1" in
  ps) printf '%s\\n' forge-walkthrough-sidecar ;;
  inspect) printf '%s\\n' "$WALKTHROUGH_MOUNT_INVENTORY" ;;
  rm) exit 99 ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_DOCKER_LOG"] = str(docker_log)
    env["WALKTHROUGH_MOUNT_INVENTORY"] = json.dumps(mount_inventory)
    env["WALKTHROUGH_SIDECAR_MAY_EXIST"] = "true"

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "no unambiguous /workspace mount" in result.stderr
    assert "rm -f" not in docker_log.read_text(encoding="utf-8")


def test_runtime_cleanup_preflights_the_install_registry_before_mutation(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    evidence = target / ".forge/artifacts/walkthrough-demo/preserve.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    (target / ".forge-home/installed.json").write_text("not json\n", encoding="utf-8")

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "registry is unreadable or malformed" in result.stderr
    assert evidence.read_text(encoding="utf-8") == "{}\n"


def test_runtime_cleanup_refuses_a_symlinked_forge_parent_before_mutation(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    external_forge = tmp_path / "external-forge"
    (target / ".forge").rename(external_forge)
    (target / ".forge").symlink_to(external_forge, target_is_directory=True)
    evidence = external_forge / "artifacts/walkthrough-demo/preserve.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "Expected real directory missing" in result.stderr
    assert evidence.read_text(encoding="utf-8") == "{}\n"


@pytest.mark.parametrize(
    "relative_path",
    [
        ".forge/sessions",
        ".forge-home/sessions",
        ".forge-home/proxies",
        ".forge-home/proxies/walkthrough-sidecar-proxy",
    ],
)
def test_runtime_cleanup_refuses_symlinked_session_or_proxy_store_paths_before_mutation(
    tmp_path: Path,
    relative_path: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    store_path = target / relative_path
    external = tmp_path / f"external-{relative_path.replace('/', '-')}"
    if store_path.exists():
        store_path.rename(external)
    else:
        external.mkdir(parents=True)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.symlink_to(external, target_is_directory=True)
    evidence = external / "preserve.txt"
    evidence.write_text("preserve\n", encoding="utf-8")

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "not a real directory" in result.stderr
    assert evidence.read_text(encoding="utf-8") == "preserve\n"


def test_runtime_cleanup_refuses_a_symlinked_fixed_session_dir_before_manifest_deletion(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    publish_session_from_fields(
        index,
        "walkthrough-demo",
        target,
        target,
        forge_root=target,
    )
    session_dir = target / ".forge/sessions/walkthrough-demo"
    external = tmp_path / "external-session"
    session_dir.rename(external)
    session_dir.symlink_to(external, target_is_directory=True)
    manifest = external / "forge.session.json"
    before_manifest = manifest.read_bytes()
    before_index = index.index_path.read_bytes()

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "session path is not a real directory" in result.stderr
    assert manifest.read_bytes() == before_manifest
    assert index.index_path.read_bytes() == before_index


def test_runtime_cleanup_refuses_a_symlinked_fixed_session_manifest_before_deletion(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    publish_session_from_fields(
        index,
        "walkthrough-demo",
        target,
        target,
        forge_root=target,
    )
    manifest = target / ".forge/sessions/walkthrough-demo/forge.session.json"
    external = tmp_path / "external-manifest.json"
    manifest.replace(external)
    manifest.symlink_to(external)
    before_manifest = external.read_bytes()
    before_index = index.index_path.read_bytes()

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "session manifest is not a regular file" in result.stderr
    assert external.read_bytes() == before_manifest
    assert index.index_path.read_bytes() == before_index


def test_runtime_cleanup_refuses_fixed_session_with_external_worktree_identity(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    external = tmp_path / "external-worktree"
    external.mkdir()
    evidence = external / "preserve.txt"
    evidence.write_text("preserve\n", encoding="utf-8")
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    publish_session_from_fields(
        index,
        "walkthrough-demo",
        target,
        target,
        forge_root=target,
    )
    store = SessionStore(str(target), "walkthrough-demo")

    def redirect_worktree(state) -> None:
        assert state.worktree is not None
        state.worktree.path = str(external)
        state.worktree.is_worktree = True
        state.worktree.owns_worktree = True
        state.confirmed.claude_project_root = str(external)

    store.update(timeout_s=5.0, mutate=redirect_worktree)
    before_manifest = store.manifest_path.read_bytes()
    before_index = index.index_path.read_bytes()

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "Could not prove whether walkthrough-demo is walkthrough-owned" in result.stderr
    assert evidence.read_text(encoding="utf-8") == "preserve\n"
    assert store.manifest_path.read_bytes() == before_manifest
    assert index.index_path.read_bytes() == before_index


def test_runtime_preflights_every_owned_resource_before_deleting_an_earlier_session(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    publish_session_from_fields(
        index,
        "walkthrough-codex",
        target,
        target,
        forge_root=target,
    )
    store = SessionStore(str(target), "walkthrough-codex")
    before_manifest = store.manifest_path.read_bytes()
    before_index = index.index_path.read_bytes()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "forge-calls.log"
    forge = fake_bin / "forge"
    forge.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WALKTHROUGH_FAKE_LOG"
if [[ "$1 $2" == "proxy list" ]]; then
  printf '%s\n' '[{"proxy_id":"walkthrough-sidecar-proxy","template":"foreign-template"}]'
else
  exit 99
fi
""",
        encoding="utf-8",
    )
    forge.chmod(0o755)
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_FAKE_LOG"] = str(log)

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "unexpected identity" in result.stderr
    assert "session delete" not in log.read_text(encoding="utf-8")
    assert store.manifest_path.read_bytes() == before_manifest
    assert index.index_path.read_bytes() == before_index


def test_reset_refuses_malformed_progress_without_a_sidecar_session(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    progress = target / ".forge/walkthrough/progress.json"
    progress.write_text("not json\n", encoding="utf-8")
    evidence = target / ".forge/artifacts/walkthrough-demo/preserve.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "progress is unreadable or malformed" in reset.stderr
    assert evidence.read_text(encoding="utf-8") == "{}\n"


def test_validate_malformed_progress_does_not_recommend_the_refusing_reset(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    progress = target / ".forge/walkthrough/progress.json"
    state = _valid_progress_state()
    state["vars"] = {
        "RUN_OPTIONS": "codex=true,sidecar=false",
        "SIDECAR_MAY_EXIST": "false",
    }
    state["steps"] = []
    progress.write_text(json.dumps(state) + "\n", encoding="utf-8")
    evidence = target / ".forge/artifacts/walkthrough-demo/preserve.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")

    validate = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "walkthrough-state.py"),
            str(SCRIPTS.parent / "resources/checklist.md"),
            "validate",
            str(progress),
            "--from",
            "1.1",
            "--report",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert validate.returncode == 2, validate.stderr
    refusal = json.loads(validate.stdout)
    assert refusal["recovery_kind"] == "manual-state-inspection"
    assert refusal["reset_safe"] is False
    assert refusal["recovery_state_path"] == str(progress)
    assert refusal["alternate_fresh_command"] == "/walkthrough --codex --report"
    assert "different empty path" in refusal["recovery"]
    assert "/walkthrough --reset" not in refusal["recovery"]

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "progress is unreadable or malformed" in reset.stderr
    assert evidence.read_text(encoding="utf-8") == "{}\n"


def test_reset_accepts_state_written_directly_by_init(tmp_path: Path) -> None:
    target, env = _setup_walkthrough(tmp_path)
    progress = target / ".forge/walkthrough/progress.json"
    checklist = SCRIPTS.parent / "resources/checklist.md"
    initialized = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "walkthrough-state.py"),
            str(checklist),
            "init",
            str(progress),
            "--force",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(progress.read_text(encoding="utf-8"))["vars"] == {}

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 0, reset.stderr
    assert not progress.exists()


@pytest.mark.parametrize("missing_home", [".forge-home", ".claude-user", ".codex-user"])
def test_reset_recreates_missing_generated_home_before_gated_cleanup(
    tmp_path: Path,
    missing_home: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    generated_home = target / missing_home
    preserved_home = tmp_path / f"preserved-{missing_home.removeprefix('.')}"
    generated_home.rename(preserved_home)

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 0, reset.stderr
    assert generated_home.is_dir()
    assert preserved_home.is_dir()
    assert (target / ".codex-user").stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("missing_home", [".forge-home", ".claude-user", ".codex-user"])
def test_fresh_setup_reports_existing_sandbox_when_a_generated_home_is_missing(
    tmp_path: Path,
    missing_home: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    generated_home = target / missing_home
    preserved_home = tmp_path / f"preserved-{missing_home.removeprefix('.')}"
    sentinel = generated_home / "preserve.txt"
    sentinel.write_text("preserve\n", encoding="utf-8")
    generated_home.rename(preserved_home)

    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert setup.returncode == 1
    assert f"Walkthrough repository already exists: {target}" in setup.stderr
    assert "Use --reset to reclaim owned resources" in setup.stderr
    assert "Did you source env.sh?" not in setup.stderr
    assert not generated_home.exists()
    assert (preserved_home / "preserve.txt").read_text(encoding="utf-8") == "preserve\n"


@pytest.mark.parametrize(
    "case",
    [
        "incomplete",
        "wrong-top-level-type",
        "wrong-sidecar-type",
        "newer-schema",
        "incomplete-legacy-schema",
    ],
)
def test_reset_refuses_structurally_invalid_or_newer_progress(
    tmp_path: Path,
    case: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    state: object = _valid_progress_state()
    if case == "incomplete":
        assert isinstance(state, dict)
        state.pop("steps")
    elif case == "wrong-top-level-type":
        assert isinstance(state, dict)
        state["steps"] = []
    elif case == "wrong-sidecar-type":
        assert isinstance(state, dict)
        state["vars"] = {"SIDECAR_MAY_EXIST": False}
    elif case == "newer-schema":
        assert isinstance(state, dict)
        state["schema_version"] = 3
    else:
        assert isinstance(state, dict)
        state["schema_version"] = 1
    progress = target / ".forge/walkthrough/progress.json"
    progress.write_text(json.dumps(state) + "\n", encoding="utf-8")
    evidence = target / ".forge/artifacts/walkthrough-demo/preserve.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "progress is unreadable or malformed" in reset.stderr
    assert evidence.read_text(encoding="utf-8") == "{}\n"


def test_setup_rejects_an_explicitly_empty_claude_config_dir(tmp_path: Path) -> None:
    target = tmp_path / "walkthrough"
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "FORGE_TEST_REPO": str(target), "CLAUDE_CONFIG_DIR": ""})

    result = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 2
    assert "CLAUDE_CONFIG_DIR is explicitly set to empty" in result.stderr
    assert not target.exists()


def test_setup_canonicalizes_a_symlink_parent_for_the_shipped_claude_probe(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias-parent"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    native_claude = tmp_path / "native-claude"
    native_claude.write_text("#!/usr/bin/env bash\nprintf '%s\\n' 'Claude test'\n", encoding="utf-8")
    native_claude.chmod(0o755)
    target, env = _setup_walkthrough(
        tmp_path,
        target=alias_parent / "walkthrough",
        extra_env={"FORGE_WALKTHROUGH_CLAUDE_BIN": str(native_claude)},
    )

    result = subprocess.run(
        ["bash", str(SCRIPTS / "run-in-repo.sh"), "claude", "--version"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert target == real_parent / "walkthrough"
    assert result.returncode == 0, result.stderr
    assert "Claude test" in result.stdout


@pytest.mark.parametrize("marker_kind", ["symlink", "wrong-content"])
def test_run_wrapper_and_reset_reject_noncanonical_marker_without_mutation(
    tmp_path: Path,
    marker_kind: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    marker = target / ".forge-walkthrough-marker"
    external_marker = tmp_path / "external-marker"
    if marker_kind == "symlink":
        marker.replace(external_marker)
        marker.symlink_to(external_marker)
        expected_marker = b"forge-walkthrough-marker\n"
    else:
        marker.write_bytes(b"foreign-marker\n")
        expected_marker = b"foreign-marker\n"
    evidence = target / ".forge/artifacts/walkthrough-demo/preserve.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("{}\n", encoding="utf-8")
    command_sentinel = tmp_path / "command-ran"

    wrapped = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            "-c",
            'printf ran > "$1"',
            "_",
            str(command_sentinel),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert wrapped.returncode == 1
    assert "Canonical marker file missing" in wrapped.stderr
    assert reset.returncode == 1
    assert "no canonical walkthrough marker" in reset.stderr
    assert not command_sentinel.exists()
    assert evidence.read_text(encoding="utf-8") == "{}\n"
    marker_source = external_marker if marker_kind == "symlink" else marker
    assert marker_source.read_bytes() == expected_marker


def test_run_wrapper_rejects_symlinked_env_without_executing_external_code(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    env_path = target / ".forge/walkthrough/env.sh"
    external_env = tmp_path / "external-env.sh"
    source_sentinel = tmp_path / "external-env-sourced"
    command_sentinel = tmp_path / "command-ran"
    external_bytes = f"printf sourced > {shlex.quote(str(source_sentinel))}\n".encode()
    env_path.unlink()
    external_env.write_bytes(external_bytes)
    env_path.symlink_to(external_env)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            "-c",
            'printf ran > "$1"',
            "_",
            str(command_sentinel),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "env.sh not found" in result.stderr
    assert not source_sentinel.exists()
    assert not command_sentinel.exists()
    assert external_env.read_bytes() == external_bytes


@pytest.mark.parametrize(
    "relative_path",
    [".forge", ".forge/walkthrough", ".forge-home", ".claude-user", ".codex-user"],
)
def test_run_wrapper_rejects_symlinked_sandbox_intermediates_before_command(
    tmp_path: Path,
    relative_path: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    owned_path = target / relative_path
    external_path = tmp_path / f"external-{relative_path.replace('/', '-').removeprefix('.')}"
    owned_path.rename(external_path)
    owned_path.symlink_to(external_path, target_is_directory=True)
    evidence = external_path / "preserve.txt"
    evidence.write_text("preserve\n", encoding="utf-8")
    command_sentinel = tmp_path / "command-ran"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            "-c",
            'printf ran > "$1"',
            "_",
            str(command_sentinel),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert not command_sentinel.exists()
    assert evidence.read_text(encoding="utf-8") == "preserve\n"


@pytest.mark.parametrize("target_kind", ["wrapper-dir", "wrapper-file", "env-file"])
def test_reset_refuses_symlinked_generated_environment_target_without_external_mutation(
    tmp_path: Path,
    target_kind: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    external = tmp_path / f"external-{target_kind}"
    source_sentinel = tmp_path / "external-code-ran"
    if target_kind == "wrapper-dir":
        generated_target = target / ".forge/walkthrough/bin"
        generated_target.rename(tmp_path / "original-bin")
        external.mkdir()
        evidence = external / "preserve.txt"
        evidence.write_text("preserve\n", encoding="utf-8")
        expected_bytes = b"preserve\n"
    else:
        generated_target = target / (
            ".forge/walkthrough/bin/claude" if target_kind == "wrapper-file" else ".forge/walkthrough/env.sh"
        )
        generated_target.unlink()
        evidence = external
        expected_bytes = f"printf sourced > {shlex.quote(str(source_sentinel))}\n".encode()
        evidence.write_bytes(expected_bytes)
    generated_target.symlink_to(external, target_is_directory=target_kind == "wrapper-dir")
    runtime_evidence = target / ".forge/artifacts/walkthrough-demo/preserve.json"
    runtime_evidence.parent.mkdir(parents=True)
    runtime_evidence.write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert not source_sentinel.exists()
    assert evidence.read_bytes() == expected_bytes
    assert runtime_evidence.read_text(encoding="utf-8") == "{}\n"


def test_extension_cleanup_requires_nested_repo_metadata_before_git_mutation(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=parent, check=True)
    parent_file = parent / "parent.txt"
    parent_file.write_text("preserve\n", encoding="utf-8")
    subprocess.run(["git", "add", "parent.txt"], cwd=parent, check=True)
    target, env = _setup_walkthrough(tmp_path, target=parent / "walkthrough")
    (target / ".git").rename(tmp_path / "nested-repo-metadata")
    greeting = target / "src/greeting.py"
    greeting.write_text("preserve greeting\n", encoding="utf-8")
    subprocess.run(["git", "add", "walkthrough/src/greeting.py"], cwd=parent, check=True)
    parent_index = parent / ".git/index"
    before_index = parent_index.read_bytes()

    result = _run_extensions_cleanup(env)

    assert result.returncode == 1
    assert "requires a real repository metadata directory" in result.stderr
    assert parent_index.read_bytes() == before_index
    assert greeting.read_text(encoding="utf-8") == "preserve greeting\n"


def test_runtime_cleanup_is_repeatable_and_preserves_foreign_resources(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "forge-calls.log"
    fake = fake_bin / "forge"
    fake.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\t%s\\n' "${CLAUDE_HOME:-}" "$*" >> "$WALKTHROUGH_FAKE_LOG"
if [[ "$1 $2" == "session list" ]]; then
  printf '[{"name":"walkthrough-demo","forge_root":"%s"},{"name":"foreign-session","forge_root":"/foreign"}]\\n' "$FORGE_TEST_REPO"
elif [[ "$1 $2" == "session delete" ]]; then
  test "$3" = "walkthrough-demo"
elif [[ "$1 $2" == "proxy list" ]]; then
  printf '%s\\n' '[{"proxy_id":"walkthrough-sidecar-proxy","template":"openrouter-anthropic"},{"proxy_id":"foreign-proxy","template":"openrouter-anthropic"}]'
elif [[ "$1 $2" == "proxy delete" ]]; then
  test "$3" = "walkthrough-sidecar-proxy"
else
  printf '%s\\n' '{"installations":[]}'
fi
""")
    fake.chmod(0o755)
    index = IndexStore(index_path=target / ".forge-home/sessions/index.json")
    publish_session_from_fields(
        index,
        "walkthrough-demo",
        target,
        target,
        forge_root=target,
    )
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_FAKE_LOG"] = str(log)
    env["WALKTHROUGH_SIDECAR_MAY_EXIST"] = "false"
    owned_transfer = target / ".forge/prev_sessions/walkthrough-demo/generated.md"
    owned_transfer.parent.mkdir(parents=True)
    owned_transfer.write_text("owned\n", encoding="utf-8")
    foreign_transfer = target / ".forge/prev_sessions/foreign-session/generated.md"
    foreign_transfer.parent.mkdir(parents=True)
    foreign_transfer.write_text("preserve\n", encoding="utf-8")

    first = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "runtime",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    second = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "runtime",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert first.returncode == second.returncode == 0
    calls = log.read_text()
    assert "session delete walkthrough-demo --yes --force" in calls
    assert f"{home / '.claude'}\tsession delete walkthrough-demo --yes --force" in calls
    assert "session delete foreign-session" not in calls
    assert "proxy delete walkthrough-sidecar-proxy --yes" in calls
    assert "proxy delete foreign-proxy" not in calls
    assert "docker" not in calls
    assert not owned_transfer.exists()
    assert foreign_transfer.read_text(encoding="utf-8") == "preserve\n"


def test_cleanup_refuses_when_ownership_inventory_cannot_be_read(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    artifact = target / ".forge/artifacts/preserve.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "forge"
    fake.write_text("#!/usr/bin/env bash\nexit 9\n")
    fake.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "runtime",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "Could not inspect the session index" in result.stderr
    assert artifact.read_text(encoding="utf-8") == "{}\n"


def test_cleanup_refuses_fixed_proxy_id_with_unexpected_template(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "forge-calls.log"
    fake = fake_bin / "forge"
    fake.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "$WALKTHROUGH_FAKE_LOG"
if [[ "$1 $2" == "session list" ]]; then
  printf '%s\\n' '[]'
elif [[ "$1 $2" == "proxy list" ]]; then
  printf '%s\\n' '[{"proxy_id":"walkthrough-sidecar-proxy","template":"foreign-template"}]'
else
  exit 99
fi
""")
    fake.chmod(0o755)
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_FAKE_LOG"] = str(log)

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "runtime",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "unexpected identity" in result.stderr
    assert "proxy delete" not in log.read_text(encoding="utf-8")


def test_cleanup_refuses_unregistered_fixed_proxy_directory_without_mutation(
    tmp_path: Path,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    proxy_dir = target / ".forge-home/proxies/walkthrough-sidecar-proxy"
    proxy_dir.mkdir(parents=True)
    evidence = proxy_dir / "preserve.yaml"
    evidence.write_text("foreign: true\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "forge-calls.log"
    forge = fake_bin / "forge"
    forge.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WALKTHROUGH_FAKE_LOG"
if [[ "$1 $2" == "proxy list" ]]; then
  printf '%s\n' '[]'
else
  exit 99
fi
""",
        encoding="utf-8",
    )
    forge.chmod(0o755)
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_FAKE_LOG"] = str(log)

    result = _run_runtime_cleanup(env)

    assert result.returncode == 1
    assert "absent from the proxy registry" in result.stderr
    assert f"Unregistered path: {proxy_dir}" in result.stderr
    assert "Inspect it first:" in result.stderr
    assert "If it is foreign, move it" in result.stderr
    assert "If you verify it is abandoned walkthrough residue" in result.stderr
    assert "rm -rf" in result.stderr
    assert "proxy delete" not in log.read_text(encoding="utf-8")
    assert evidence.read_text(encoding="utf-8") == "foreign: true\n"


@pytest.mark.parametrize("relative_path", ["src", ".git"])
def test_extension_cleanup_refuses_symlinked_source_or_git_parent_before_mutation(
    tmp_path: Path,
    relative_path: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    owned_parent = target / relative_path
    external = tmp_path / f"external-{relative_path.removeprefix('.')}"
    owned_parent.rename(external)
    owned_parent.symlink_to(external, target_is_directory=True)
    evidence = external / "preserve.txt"
    evidence.write_text("preserve\n", encoding="utf-8")
    auth = target / ".codex-user/auth.json"
    auth.write_text('{"preserve":true}\n', encoding="utf-8")

    result = _run_extensions_cleanup(env)

    assert result.returncode == 1
    expected_error = (
        "requires a real repository metadata directory"
        if relative_path == ".git"
        else "cleanup path is not a real directory"
    )
    assert expected_error in result.stderr
    assert evidence.read_text(encoding="utf-8") == "preserve\n"
    assert auth.read_text(encoding="utf-8") == '{"preserve":true}\n'


@pytest.mark.parametrize(
    ("scope", "relative_path"),
    [("local", ".claude"), ("user", ".claude-user")],
)
def test_extension_cleanup_refuses_symlinked_install_boundary_with_valid_tracking_row(
    tmp_path: Path,
    scope: str,
    relative_path: str,
) -> None:
    target, env = _setup_walkthrough(tmp_path)
    owned_parent = target / relative_path
    external = tmp_path / f"external-{scope}-install"
    owned_parent.rename(external)
    owned_parent.symlink_to(external, target_is_directory=True)
    tracked_file = external / "commands/managed.md"
    tracked_file.parent.mkdir(parents=True)
    tracked_file.write_text("preserve\n", encoding="utf-8")
    owner = ModuleOwner(module="commands", runtime="claude_code")
    installation = Installation(
        scope=scope,
        mode="copy",
        profile="standard",
        project_path=str(target) if scope == "local" else None,
        module_owners=[owner],
        files=[
            InstalledFile(
                target_path=str(tracked_file),
                source_path="/packaged/commands/managed.md",
                checksum=compute_checksum(tracked_file),
                mode="copy",
                installed_at="2026-09-02T00:00:00+00:00",
                attribution=owner,
            )
        ],
    )
    installation_key = f"local:{target}" if scope == "local" else "user"
    registry_store = TrackingStore(target / ".forge-home/installed.json")
    registry_store.write(InstalledManifest(installations={installation_key: installation}))
    assert registry_store.read().installations[installation_key].files[0].target_path == str(tracked_file)
    before_registry = registry_store.path.read_bytes()

    result = _run_extensions_cleanup(env)

    assert result.returncode == 1
    expected_error = (
        "CLAUDE_HOME is not redirected" if relative_path == ".claude-user" else "cleanup path is not a real directory"
    )
    assert expected_error in result.stderr
    assert tracked_file.read_text(encoding="utf-8") == "preserve\n"
    assert registry_store.path.read_bytes() == before_registry


def test_extension_cleanup_preserves_auth_when_install_inventory_fails(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    auth = target / ".codex-user/auth.json"
    auth.write_text('{"tokens":[]}\n', encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "forge"
    fake.write_text("#!/usr/bin/env bash\nexit 9\n")
    fake.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "extensions",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "Could not inspect the local extension installation" in result.stderr
    assert auth.read_text(encoding="utf-8") == '{"tokens":[]}\n'


def test_reset_refuses_foreign_rows_in_the_sandbox_install_registry(
    tmp_path: Path,
) -> None:
    """CWD-scoped status must not hide another project's ownership row."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    foreign_project = tmp_path / "foreign-project"
    foreign_project.mkdir()
    foreign_file = foreign_project / "preserve.txt"
    foreign_file.write_text("foreign\n", encoding="utf-8")
    artifact = target / ".forge/artifacts/preserve.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    registry = target / ".forge-home/installed.json"
    registry.write_text(
        json.dumps(
            {
                "version": 3,
                "installations": {
                    f"local:{foreign_project}": {
                        "scope": "local",
                        "mode": "copy",
                        "profile": "standard",
                        "project_path": str(foreign_project),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "installations outside walkthrough ownership" in reset.stderr
    assert f"local:{foreign_project}" in reset.stderr
    assert "Do not delete installed.json" in reset.stderr
    assert artifact.read_text(encoding="utf-8") == "{}\n"
    assert foreign_file.read_text(encoding="utf-8") == "foreign\n"
    assert json.loads(registry.read_text(encoding="utf-8"))["installations"]


@pytest.mark.parametrize("scope", ["user", "local"])
def test_reset_refuses_owned_row_ids_with_targets_outside_the_sandbox(
    tmp_path: Path,
    scope: str,
) -> None:
    """A familiar row id must not launder targets from a different home."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    foreign_backup = tmp_path / "foreign-settings-backup.json"
    foreign_backup.write_text('{"preserve":true}\n', encoding="utf-8")
    artifact = target / ".forge/artifacts/preserve.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    installation_id = "user" if scope == "user" else f"local:{target}"
    registry = target / ".forge-home/installed.json"
    registry.write_text(
        json.dumps(
            {
                "version": 3,
                "installations": {
                    installation_id: {
                        "scope": scope,
                        "mode": "copy",
                        "profile": "standard",
                        "project_path": None if scope == "user" else str(target),
                        "settings_backup_path": str(foreign_backup),
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "target outside its walkthrough boundary" in reset.stderr
    assert f"id='{installation_id}'" in reset.stderr
    assert artifact.read_text(encoding="utf-8") == "{}\n"
    assert foreign_backup.read_text(encoding="utf-8") == '{"preserve":true}\n'
    assert json.loads(registry.read_text(encoding="utf-8"))["installations"]


@pytest.mark.parametrize(
    "registry_bytes",
    [
        b"\xff",
        b'{"version":3,"installations":[]}',
    ],
    ids=["non-utf8", "invalid-row-container"],
)
def test_reset_refuses_an_unreadable_or_malformed_sandbox_install_registry(
    tmp_path: Path,
    registry_bytes: bytes,
) -> None:
    """Unknown registry state must block before reset discards evidence."""
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    artifact = target / ".forge/artifacts/preserve.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    registry = target / ".forge-home/installed.json"
    registry.write_bytes(registry_bytes)

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "Could not prove the sandbox extension registry is safe" in reset.stderr
    assert artifact.read_text(encoding="utf-8") == "{}\n"
    assert registry.read_bytes() == registry_bytes


def test_extension_cleanup_removes_fixed_source_and_sandbox_codex_state(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    greeting = target / "src/greeting.py"
    greeting.write_text("def greeting():\n    return 'hello'\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/greeting.py"], cwd=target, check=True)
    rollout = target / ".codex-user/sessions/rollout.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text("{}\n", encoding="utf-8")
    codex_home_inode = (target / ".codex-user").stat().st_ino
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "forge"
    fake.write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "extension status" ]]; then
  printf '%s\\n' '{"installations":[]}'
else
  exit 99
fi
""")
    fake.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    for _ in range(2):
        result = subprocess.run(
            [
                "bash",
                str(SCRIPTS / "run-in-repo.sh"),
                "bash",
                str(SCRIPTS / "cleanup-owned.sh"),
                "extensions",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, result.stderr

    assert not greeting.exists()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "src/greeting.py"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
    assert list((target / ".codex-user").iterdir()) == []
    assert (target / ".codex-user").stat().st_ino == codex_home_inode
    assert (target / ".codex-user").stat().st_mode & 0o777 == 0o700
    assert "should-survive-forge" in (target / ".claude/settings.local.json").read_text()


def test_extension_cleanup_clears_isolated_project_trust_without_touching_roots(
    tmp_path: Path,
) -> None:
    """Sandbox enrollment grants permission but owns nothing in an enrolled root."""

    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    foreign_root = tmp_path / "foreign-project"
    foreign_root.mkdir()
    foreign_file = foreign_root / "preserve.txt"
    foreign_file.write_text("foreign\n", encoding="utf-8")
    registry = target / ".forge-home/projects.json"
    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "projects": [
                    {
                        "canonical_path": str(target.resolve()),
                        "enrolled_at": "2026-09-02T00:00:00+00:00",
                        "enrollment_source": "enable",
                    },
                    {
                        "canonical_path": str(foreign_root.resolve()),
                        "enrolled_at": "2026-09-02T00:00:00+00:00",
                        "enrollment_source": "enable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    dispatcher = target / ".forge-home/bin/forge-hook"
    dispatcher.parent.mkdir(parents=True)
    dispatcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    dispatcher.chmod(0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "forge"
    fake.write_text("""#!/usr/bin/env bash
set -euo pipefail
if [[ "$1 $2" == "extension status" ]]; then
  printf '%s\\n' '{"installations":[]}'
else
  exit 99
fi
""")
    fake.chmod(0o755)
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    for _ in range(2):
        cleanup = subprocess.run(
            [
                "bash",
                str(SCRIPTS / "run-in-repo.sh"),
                "bash",
                str(SCRIPTS / "cleanup-owned.sh"),
                "extensions",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        assert cleanup.returncode == 0, cleanup.stderr

    assert not registry.exists()
    assert foreign_file.read_text(encoding="utf-8") == "foreign\n"
    assert dispatcher.is_file()


@pytest.mark.parametrize(
    "registry_bytes",
    [b"\xff", b'{"schema_version":2,"projects":[]}'],
    ids=["non-utf8", "newer-schema"],
)
def test_reset_refuses_malformed_sandbox_project_registry_before_runtime_cleanup(
    tmp_path: Path,
    registry_bytes: bytes,
) -> None:
    """Unknown trust state must survive while reset preserves runtime evidence."""

    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    artifact = target / ".forge/artifacts/preserve.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    registry = target / ".forge-home/projects.json"
    registry.write_bytes(registry_bytes)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "forge"
    fake.write_text("#!/usr/bin/env bash\nexit 99\n")
    fake.chmod(0o755)
    _write_answering_python(fake_bin)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    reset = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert reset.returncode == 1
    assert "Could not prove the sandbox project registry is safe" in reset.stderr
    assert artifact.read_text(encoding="utf-8") == "{}\n"
    assert registry.read_bytes() == registry_bytes


def test_sidecar_cleanup_refuses_same_name_container_from_another_project(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    forge = fake_bin / "forge"
    forge.write_text("#!/usr/bin/env bash\nprintf '%s\\n' '[]'\n")
    forge.chmod(0o755)
    _write_answering_python(fake_bin)
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WALKTHROUGH_DOCKER_LOG"
case "$1" in
  ps) printf '%s\n' forge-walkthrough-sidecar ;;
  inspect) printf '%s\n' '[{"Source":"/foreign/project","Destination":"/workspace"}]' ;;
  rm) exit 99 ;;
  *) exit 2 ;;
esac
""")
    docker.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_DOCKER_LOG"] = str(docker_log)
    env["WALKTHROUGH_SIDECAR_MAY_EXIST"] = "true"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPTS / "run-in-repo.sh"),
            "bash",
            str(SCRIPTS / "cleanup-owned.sh"),
            "runtime",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "not mounted from this walkthrough" in result.stderr
    assert "rm -f" not in docker_log.read_text(encoding="utf-8")


def test_reset_does_not_probe_docker_for_an_unattempted_sidecar_option(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    target = tmp_path / "walkthrough"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["FORGE_TEST_REPO"] = str(target)
    setup = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert setup.returncode == 0, setup.stderr

    progress = target / ".forge/walkthrough/progress.json"
    progress.write_text(json.dumps(_valid_progress_state()) + "\n", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$WALKTHROUGH_DOCKER_LOG"\nexit 99\n')
    docker.chmod(0o755)
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["WALKTHROUGH_DOCKER_LOG"] = str(docker_log)

    result = subprocess.run(
        ["bash", str(SCRIPTS / "setup-test-repo.sh"), "--reset"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not docker_log.exists()
