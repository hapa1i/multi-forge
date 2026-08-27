from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "start-container.sh"
HEAD_REV = "1111111111111111111111111111111111111111"


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _wheel(tmp_path: Path, *, filename_version: str = "0.9.4", metadata_version: str = "0.9.4") -> Path:
    wheel = tmp_path / f"multi_forge-{filename_version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"multi_forge-{metadata_version}.dist-info/METADATA",
            f"Name: multi-forge\nVersion: {metadata_version}\n",
        )
    return wheel


def _base_env(tmp_path: Path, docker_body: str) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_exec(bin_dir / "docker", docker_body)
    _write_exec(
        bin_dir / "git",
        'args="$*"\n'
        'case "$args" in\n'
        '  *"--is-inside-work-tree"*) exit 0 ;;\n'
        f'  *"rev-parse HEAD"*) echo "{HEAD_REV}" ;;\n'
        '  *"status --porcelain"*) : ;;\n'
        "  *) : ;;\n"
        "esac\n",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FORGE_HOME": str(tmp_path / "forge-home"),
            "CODEX_API_KEY": "test-codex-key",
            "OPENROUTER_API_KEY": "test-key",
            "FORGE_QA_WORKFLOW_MODELS": "wfm",
            "FORGE_QA_WORKFLOW_MODEL_A": "wfa",
            "FORGE_QA_WORKFLOW_MODEL_B": "wfb",
        }
    )
    return env


def _run(tmp_path: Path, args: list[str], docker_body: str = 'test "$1" = info\n') -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=tmp_path,
        env=_base_env(tmp_path, docker_body),
        capture_output=True,
        text=True,
    )


def _running_container_docker(
    wheel: Path,
    *,
    runtime_track: str = "pinned",
    profile: str = "openrouter",
    artifact_mode: str = "prebuilt",
    wheel_path: str | None = None,
    codex_auth_mode: str = "api-key",
) -> str:
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    image = f"forge-qa-release:0.9.4-sha-{digest[:12]}-pinned-claude-2.1.245-codex-0.149.1"
    recorded_wheel_path = wheel_path or str(wheel.resolve())
    return (
        'sub="$1"; args="$*"\n'
        'case "$sub" in\n'
        "  info) exit 0 ;;\n"
        '  ps) echo "container-id" ;;\n'
        "  inspect)\n"
        '    case "$args" in\n'
        f'      *org.opencontainers.image.revision*) printf "{HEAD_REV}" ;;\n'
        f'      *io.multi-forge.qa.wheel-sha256*) printf "{digest}" ;;\n'
        '      *io.multi-forge.qa.forge-version*) printf "0.9.4" ;;\n'
        f'      *io.multi-forge.qa.runtime-track*) printf "{runtime_track}" ;;\n'
        '      *io.multi-forge.qa.claude-version*) printf "2.1.245" ;;\n'
        '      *io.multi-forge.qa.codex-version*) printf "0.149.1" ;;\n'
        f'      *io.multi-forge.qa.provider-profile*) printf "{profile}" ;;\n'
        f'      *io.multi-forge.qa.artifact-mode*) printf "{artifact_mode}" ;;\n'
        f'      *io.multi-forge.qa.wheel-path*) printf "%s" {recorded_wheel_path!r} ;;\n'
        f'      *io.multi-forge.qa.codex-auth-mode*) printf "{codex_auth_mode}" ;;\n'
        f'      *Config.Image*) printf "%s" {image!r} ;;\n'
        "      *) : ;;\n"
        "    esac ;;\n"
        "  exec)\n"
        '    case "$args" in\n'
        '      *"claude --version"*) printf "2.1.245 (Claude Code)\\n" ;;\n'
        '      *"codex --version"*) printf "codex-cli 0.149.1\\n" ;;\n'
        '      *"FORGE_QA_PROVIDER_PROFILE"*) printf "openrouter" ;;\n'
        '      *"FORGE_QA_WORKFLOW_MODELS"*) printf "wfm" ;;\n'
        '      *"FORGE_QA_WORKFLOW_MODEL_A"*) printf "wfa" ;;\n'
        '      *"FORGE_QA_WORKFLOW_MODEL_B"*) printf "wfb" ;;\n'
        "      *) : ;;\n"
        "    esac ;;\n"
        "  *) : ;;\n"
        "esac\n"
    )


def _fresh_container_docker(log_path: Path) -> str:
    context_log = log_path.with_suffix(".context")
    return (
        f'printf "%s\\n" "$*" >> {str(log_path)!r}\n'
        'sub="$1"; args="$*"\n'
        'case "$sub" in\n'
        "  info) exit 0 ;;\n"
        "  ps) exit 0 ;;\n"
        '  image) test "${2:-}" != inspect ;;\n'
        "  build)\n"
        '    case "$args" in\n'
        "      *Dockerfile.qa*)\n"
        '        for context in "$@"; do :; done\n'
        '        context_files=("$context"/*)\n'
        f'        printf "%s\\n" "$context" "${{#context_files[@]}}" "${{context_files[0]##*/}}" > {str(context_log)!r} ;;\n'
        "      *) : ;;\n"
        "    esac\n"
        "    exit 0 ;;\n"
        "  run|rm|rmi|stop) exit 0 ;;\n"
        "  exec)\n"
        '    case " $args " in *" -i "*) cat >/dev/null ;; esac\n'
        '    case "$args" in\n'
        '      *"claude --version"*) printf "2.1.245 (Claude Code)\\n" ;;\n'
        '      *"codex --version"*) printf "codex-cli 0.149.1\\n" ;;\n'
        "      *) : ;;\n"
        "    esac ;;\n"
        "  *) : ;;\n"
        "esac\n"
    )


def test_unknown_flag_fails_before_docker_use(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        ["--not-a-real-option"],
        docker_body='echo "docker must not run" >&2; exit 99\n',
    )

    assert result.returncode == 1
    assert "Unknown argument" in result.stderr
    assert "docker must not run" not in result.stderr


def test_missing_and_malformed_wheels_fail_before_container_reuse(
    tmp_path: Path,
) -> None:
    missing = _run(tmp_path, ["--wheel", str(tmp_path / "missing.whl")])
    malformed_path = tmp_path / "multi_forge-0.9.4-py3-none-any.whl"
    malformed_path.write_text("not a zip", encoding="utf-8")
    malformed = _run(tmp_path, ["--wheel", str(malformed_path)])

    assert missing.returncode == 2
    assert "wheel does not exist" in missing.stderr
    assert malformed.returncode == 2
    assert "cannot read wheel metadata" in malformed.stderr


def test_filename_metadata_version_mismatch_fails(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, filename_version="0.9.4", metadata_version="1.0.0")
    result = _run(tmp_path, ["--wheel", str(wheel)])

    assert result.returncode == 2
    assert "does not match METADATA version" in result.stderr


def test_unknown_runtime_track_and_missing_codex_auth_fail(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    unknown_track = _run(tmp_path, ["--wheel", str(wheel), "--runtime-track", "future"])
    missing_auth = _run(tmp_path, ["--wheel", str(wheel), "--codex-auth", str(tmp_path / "auth.json")])

    assert unknown_track.returncode == 2
    assert "unknown runtime track" in unknown_track.stderr
    assert missing_auth.returncode == 2
    assert "Codex auth source is not a regular file" in missing_auth.stderr


def test_runtime_track_and_provider_profile_mismatches_block_reuse(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)
    wrong_track = _run(
        tmp_path,
        ["--wheel", str(wheel)],
        _running_container_docker(wheel, runtime_track="latest"),
    )
    wrong_profile = _run(
        tmp_path,
        ["--wheel", str(wheel)],
        _running_container_docker(wheel, profile="remote-litellm"),
    )

    assert wrong_track.returncode == 3
    assert "stale runtime track" in wrong_track.stderr
    assert wrong_profile.returncode == 3
    assert "stale provider profile" in wrong_profile.stderr


@pytest.mark.parametrize(
    ("artifact_mode", "wheel_path", "codex_auth_mode", "expected_error"),
    [
        ("development-build", None, "api-key", "stale artifact mode"),
        ("prebuilt", "different.whl", "api-key", "stale wheel path"),
        ("prebuilt", None, "explicit-file", "stale Codex auth mode"),
    ],
)
def test_release_evidence_identity_mismatches_block_reuse(
    tmp_path: Path,
    artifact_mode: str,
    wheel_path: str | None,
    codex_auth_mode: str,
    expected_error: str,
) -> None:
    wheel = _wheel(tmp_path)
    recorded_wheel_path = str(tmp_path / wheel_path) if wheel_path else None
    result = _run(
        tmp_path,
        ["--wheel", str(wheel)],
        _running_container_docker(
            wheel,
            artifact_mode=artifact_mode,
            wheel_path=recorded_wheel_path,
            codex_auth_mode=codex_auth_mode,
        ),
    )

    assert result.returncode == 3
    assert expected_error in result.stderr
    if artifact_mode == "development-build":
        assert "Development QA runs are single-invocation" in result.stderr


def test_pinned_runtime_observation_mismatch_blocks_reuse(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    docker_body = _running_container_docker(wheel).replace(
        'printf "codex-cli 0.149.1\\n"',
        'printf "codex-cli 0.150.0\\n"',
    )

    result = _run(tmp_path, ["--wheel", str(wheel)], docker_body)

    assert result.returncode == 3
    assert "Codex runtime mismatch" in result.stderr


def test_dirty_revision_hash_prevents_reuse_across_different_worktrees(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)
    old_dirty_rev = f"{HEAD_REV}-dirty-000000000000"
    docker_body = _running_container_docker(wheel).replace(HEAD_REV, old_dirty_rev)
    env = _base_env(tmp_path, docker_body)
    bin_dir = Path(env["PATH"].split(":", 1)[0])
    _write_exec(
        bin_dir / "git",
        'args="$*"\n'
        'case "$args" in\n'
        '  *"--is-inside-work-tree"*) exit 0 ;;\n'
        f'  *"rev-parse HEAD"*) echo "{HEAD_REV}" ;;\n'
        '  *"status --porcelain"*) printf " M src/example.py\\n" ;;\n'
        '  *"diff --binary HEAD --"*) printf "changed content" ;;\n'
        '  *"ls-files --others --exclude-standard -z"*) : ;;\n'
        "  *) : ;;\n"
        "esac\n",
    )

    result = subprocess.run(
        ["bash", str(SCRIPT), "--wheel", str(wheel)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 3
    assert "stale repository revision" in result.stderr
    assert old_dirty_rev in result.stderr


def test_latest_track_requires_a_fresh_runtime_container(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)

    result = _run(
        tmp_path,
        ["--wheel", str(wheel), "--runtime-track", "latest"],
        _running_container_docker(wheel),
    )

    assert result.returncode == 3
    assert "does not reuse" in result.stderr
    assert "--reset" in result.stderr


def test_successful_reuse_records_artifact_and_observed_runtime_identity(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)

    result = _run(tmp_path, ["--wheel", str(wheel)], _running_container_docker(wheel))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "forge-qa"
    identity_path = tmp_path / "forge-home" / "manual-testing" / "qa" / "artifact.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    assert identity["artifact"]["path"] == str(wheel.resolve())
    assert identity["artifact"]["mode"] == "prebuilt"
    assert identity["runtime"]["blocking"] is True
    assert identity["runtime"]["claude"] == {
        "pin": "2.1.245",
        "observed": "2.1.245 (Claude Code)",
    }
    assert identity["runtime"]["codex"] == {
        "pin": "0.149.1",
        "observed": "codex-cli 0.149.1",
    }
    assert identity["runtime"]["codex_auth_mode"] == "api-key"


def test_fresh_pinned_build_uses_nonempty_argument_lists_under_nounset(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    docker_log = tmp_path / "docker.log"

    result = _run(tmp_path, ["--wheel", str(wheel)], _fresh_container_docker(docker_log))

    assert result.returncode == 0, result.stderr
    build_calls = [line for line in docker_log.read_text(encoding="utf-8").splitlines() if line.startswith("build ")]
    assert len(build_calls) == 2
    assert "Dockerfile.forge" in build_calls[0]
    assert "Dockerfile.qa" in build_calls[1]
    assert all("--no-cache" not in line and "--pull" not in line for line in build_calls)
    context_path, file_count, filename = docker_log.with_suffix(".context").read_text(encoding="utf-8").splitlines()
    release_context = Path(context_path)
    assert release_context.parent == tmp_path / "forge-home" / "manual-testing" / "qa" / "artifacts"
    assert release_context != wheel.parent
    assert (file_count, filename) == ("1", wheel.name)
    assert not release_context.exists()


def test_status_reports_complete_release_identity(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)

    result = _run(tmp_path, ["--status"], _running_container_docker(wheel))

    assert result.returncode == 0
    for field in (
        "Repository revision:",
        "Wheel path:",
        "Wheel SHA-256:",
        "Artifact mode:",
        "Runtime track:",
        "Claude version:",
        "Codex version:",
        "Codex auth mode:",
        "QA provider profile:",
        "Image:",
    ):
        assert field in result.stderr


def test_duplicate_and_conflicting_start_flags_fail_before_docker_use(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)
    docker_body = 'echo "docker must not run" >&2; exit 99\n'

    duplicate = _run(
        tmp_path,
        ["--wheel", str(wheel), "--wheel", str(wheel)],
        docker_body=docker_body,
    )
    conflicting = _run(tmp_path, ["--stop", "--status"], docker_body=docker_body)
    stop_with_start = _run(
        tmp_path,
        ["--stop", "--provider-profile", "openrouter"],
        docker_body=docker_body,
    )

    assert duplicate.returncode == 1
    assert "only once" in duplicate.stderr
    assert conflicting.returncode == 1
    assert "mutually exclusive" in conflicting.stderr
    assert stop_with_start.returncode == 1
    assert "apply only when starting" in stop_with_start.stderr
    assert "docker must not run" not in duplicate.stderr + conflicting.stderr + stop_with_start.stderr


def test_default_build_rejects_ambiguous_wheel_output(tmp_path: Path) -> None:
    source_wheel = _wheel(tmp_path)
    env = _base_env(tmp_path, 'test "$1" = info\n')
    env["TEST_WHEEL"] = str(source_wheel)
    _write_exec(
        Path(env["PATH"].split(":", 1)[0]) / "uv",
        'out=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "--out-dir" ]; then out="$2"; shift 2; else shift; fi\n'
        "done\n"
        'cp "$TEST_WHEEL" "$out/one.whl"\n'
        'cp "$TEST_WHEEL" "$out/two.whl"\n',
    )

    result = subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, env=env, capture_output=True, text=True)

    assert result.returncode == 2
    assert "must produce exactly one artifact; found 2" in result.stderr
