"""Regression: walkthrough cleanup must target only fixed owned resources."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "src/skills/walkthrough/scripts"


def _write_answering_python(fake_bin: Path) -> None:
    """Let a fake Forge launcher expose the interpreter used by this test run."""

    python = fake_bin / "python"
    python.write_text(f'#!/usr/bin/env bash\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
    python.chmod(0o755)


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
  printf '%s\\n' '[{"name":"walkthrough-demo"},{"name":"foreign-session"}]'
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
    docker_log = tmp_path / "docker.log"
    docker = fake_bin / "docker"
    docker.write_text("""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$WALKTHROUGH_DOCKER_LOG"
case "$1" in
  ps) printf '%s\n' forge-walkthrough-sidecar ;;
  inspect) printf '%s\n' /foreign/project ;;
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
    progress.write_text(
        '{"vars":{"RUN_OPTIONS":"codex=false,sidecar=true","SIDECAR_MAY_EXIST":"false"}}\n',
        encoding="utf-8",
    )
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
