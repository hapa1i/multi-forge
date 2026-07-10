"""Sidecar runtime-hook injection and host-persistence integration tests."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from forge.cli.main import _process_pending_work_best_effort
from forge.core.ops.claude_session import _stage_sidecar_hook_settings
from forge.core.paths import get_forge_home
from forge.core.workqueue import pending_work_dir
from forge.session import LAUNCH_MODE_SIDECAR, SessionStore, create_session_state
from forge.sidecar.docker import is_docker_available

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]


@pytest.fixture(scope="module", autouse=True)
def _require_docker() -> None:
    if not is_docker_available():
        pytest.fail("Docker not available. Start Docker and re-run the sidecar integration tests.")


def _write_env_file(values: dict[str, str]) -> str:
    fd, path = tempfile.mkstemp(prefix=".forge-sidecar-test-", suffix=".env")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")
    os.chmod(path, 0o600)
    return path


def _user_args() -> list[str]:
    if sys.platform != "linux":
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def _init_project(project: Path) -> None:
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@forge.local"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Forge Test"], cwd=project, check=True)
    (project / "README.md").write_text("# Sidecar hook test\n")
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)
    (project / ".claude").mkdir()


def _sidecar_shell(
    image: str,
    *,
    project: Path,
    sidecar_home: Path,
    session_name: str,
    command: str,
    stdin: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "run",
            "-i",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            *_user_args(),
            "-v",
            f"{project}:/workspace",
            "-v",
            f"{sidecar_home}:/root/.claude",
            "-e",
            "HOME=/root",
            "-e",
            "FORGE_SIDECAR=1",
            "-e",
            f"FORGE_SESSION={session_name}",
            "-e",
            "FORGE_FORGE_ROOT=/workspace",
            "-w",
            "/workspace",
            image,
            "-c",
            command,
        ],
        input=stdin,
        text=True,
        capture_output=True,
        timeout=30,
    )


def test_sidecar_image_exposes_forge_on_path(sidecar_image: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            sidecar_image,
            "-c",
            "command -v forge && forge --version",
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "/forge/.venv/bin/forge" in result.stdout


def test_entrypoint_merges_api_helper_into_hooks_idempotently(tmp_path: Path, sidecar_image: str) -> None:
    sidecar_home = tmp_path / "sidecar-home"
    sidecar_home.mkdir()
    _stage_sidecar_hook_settings(sidecar_home)

    fake_claude = tmp_path / "claude"
    fake_claude.write_text("#!/bin/sh\nexit 0\n")
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env_file = _write_env_file({"OPENROUTER_API_KEY": "test-only-dummy-key"})
    command = [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        "-v",
        f"{sidecar_home}:/root/.claude",
        "-v",
        f"{fake_claude}:/usr/local/bin/claude:ro",
        "--env-file",
        env_file,
        "-e",
        "HOME=/root",
        "-e",
        "FORGE_TEMPLATE=openrouter-kimi",
        sidecar_image,
    ]

    try:
        first = subprocess.run(command, text=True, capture_output=True, timeout=60)
        assert first.returncode == 0, first.stderr
        first_bytes = (sidecar_home / "settings.json").read_bytes()
        first_settings = json.loads(first_bytes)
        assert first_settings["apiKeyHelper"] == "/root/.claude/forge_api_key_helper.sh"
        assert first_settings["hooks"]

        second = subprocess.run(command, text=True, capture_output=True, timeout=60)
        assert second.returncode == 0, second.stderr
        assert (sidecar_home / "settings.json").read_bytes() == first_bytes
    finally:
        os.unlink(env_file)


@pytest.mark.slow
def test_real_claude_sidecar_hooks_persist_artifacts_and_host_queue(
    tmp_path: Path, sidecar_image: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        pytest.fail("OPENROUTER_API_KEY is required for the real-Claude sidecar hook test")

    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "host-forge-home"))

    project = tmp_path / "project"
    _init_project(project)
    session_name = "sidecar-hook-test"
    session_id = str(uuid.uuid4())
    state = create_session_state(
        session_name,
        proxy_template="openrouter-kimi",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(project),
        launch_mode=LAUNCH_MODE_SIDECAR,
    )
    state.forge_root = str(project)
    state.confirmed.claude_session_id = session_id
    SessionStore(str(project), session_name).write(state)
    (project / ".claude" / "settings.json").write_text(
        json.dumps({"statusLine": {"type": "command", "command": "forge status-line", "padding": 0}}) + "\n"
    )

    sidecar_home = project / ".forge" / "sidecar-home"
    sidecar_home.mkdir(parents=True)
    _stage_sidecar_hook_settings(sidecar_home)
    host_queue = pending_work_dir()
    host_queue.mkdir(parents=True, exist_ok=True)
    env_file = _write_env_file({"OPENROUTER_API_KEY": openrouter_key})
    command = [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        "-v",
        f"{project}:/workspace",
        "-v",
        f"{sidecar_home}:/root/.claude",
        "-v",
        f"{host_queue}:/root/.forge/pending-work",
        "--env-file",
        env_file,
        "-e",
        "HOME=/root",
        "-e",
        "FORGE_TEMPLATE=openrouter-kimi",
        "-e",
        f"FORGE_SESSION={session_name}",
        "-e",
        "FORGE_FORGE_ROOT=/workspace",
        "-e",
        f"FORGE_SIDECAR_HOST_FORGE_ROOT={project}",
        "-e",
        "FORGE_SIDECAR=1",
        "-e",
        "FORGE_LAUNCH_MODE=sidecar",
        "-w",
        "/workspace",
        sidecar_image,
        "--print",
        "--model",
        "haiku",
        "--session-id",
        session_id,
        "Reply with exactly: sidecar-ok",
    ]

    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=180)
    finally:
        os.unlink(env_file)

    assert result.returncode == 0, f"stdout={result.stdout[-2000:]!r}\nstderr={result.stderr[-2000:]!r}"
    manifest = json.loads(Path(SessionStore(str(project), session_name).manifest_path).read_text())
    confirmed = manifest["confirmed"]
    assert str(confirmed["confirmed_by"]).startswith("hook:")
    assert confirmed["transcript_path"]
    transcript_entries = confirmed["artifacts"]["transcripts"]
    assert transcript_entries
    copied = project / transcript_entries[-1]["copied_path"]
    assert copied.is_file()

    marker_files = sorted(host_queue.glob("*.json"))
    assert {path.name for path in marker_files} >= {f"{session_id}.json", f"idx-{session_id}.json"}
    for marker_file in marker_files:
        payload = json.loads(marker_file.read_text())["payload"]
        assert payload["worktree_path"] == str(project)
        assert payload["forge_root"] == str(project)

    direct = _sidecar_shell(
        sidecar_image,
        project=project,
        sidecar_home=sidecar_home,
        session_name=session_name,
        command="forge hook user-prompt-submit",
        stdin=json.dumps({"prompt": "%help", "transcript_path": ""}),
    )
    assert direct.returncode == 0, direct.stderr
    assert json.loads(direct.stdout)["decision"] == "block"

    status_line = _sidecar_shell(
        sidecar_image,
        project=project,
        sidecar_home=sidecar_home,
        session_name=session_name,
        command="forge status-line",
        stdin=json.dumps(
            {
                "workspace": {"current_dir": "/workspace"},
                "model": {"display_name": "Haiku", "id": "haiku"},
            }
        ),
    )
    assert status_line.returncode == 0, status_line.stderr
    assert status_line.stdout.strip()

    _process_pending_work_best_effort()
    assert not list(host_queue.glob("*.json")), f"host queue did not drain: {list(host_queue.glob('*.json'))}"
    assert get_forge_home() in host_queue.parents
