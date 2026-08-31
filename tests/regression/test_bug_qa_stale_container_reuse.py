"""Regression: QA start-container.sh must not reuse a stale running container.

Bug: the running-container reuse path in
``.claude``/``src/skills/qa/scripts/start-container.sh`` exited 0 before any
image-revision check. A container built from an image older than the current
checkout was therefore reused indefinitely, so ``/qa`` silently validated
stale code (e.g. a proxy build predating the system-role 422 fix) while
reporting success.

Fix: compute ``FORGE_REV`` before the reuse fast-path and refuse to reuse a
running container whose baked ``org.opencontainers.image.revision`` label does
not equal ``FORGE_REV``, pointing the user at ``--reset``.

Affected: src/skills/qa/scripts/start-container.sh
"""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "start-container.sh"
QA_SKILL_ROOT = REPO_ROOT / "src" / "skills" / "qa"

HEAD_REV = "1111111111111111111111111111111111111111"
OLD_REV = "0000000000000000000000000000000000000000"


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_wheel(tmp_path: Path) -> Path:
    wheel = tmp_path / "multi_forge-0.9.4-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "multi_forge-0.9.4.dist-info/METADATA",
            "Name: multi-forge\nVersion: 0.9.4\n",
        )
        for path in sorted(
            path
            for path in QA_SKILL_ROOT.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        ):
            relative = path.relative_to(QA_SKILL_ROOT).as_posix()
            archive.writestr(f"forge/_extensions/skills/qa/{relative}", path.read_bytes())
    return wheel


def _qa_driver_digest(wheel: Path) -> str:
    prefix = "forge/_extensions/skills/qa/"
    with zipfile.ZipFile(wheel) as archive:
        files = {
            name.removeprefix(prefix): archive.read(name)
            for name in archive.namelist()
            if name.startswith(prefix) and not name.endswith("/") and not name.endswith("/.forge-package.json")
        }
    digest = hashlib.sha256()
    for relative, content in sorted(files.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def _make_stubs(bin_dir: Path, image_rev: str, wheel: Path) -> None:
    """Stub git/docker/claude so the script reaches the reuse staleness guard.

    git reports a clean work tree at HEAD_REV; docker reports a *running*
    forge-qa container whose image revision label is ``image_rev``.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)

    _write_exec(
        bin_dir / "git",
        'args="$*"\n'
        'case "$args" in\n'
        '  *"--is-inside-work-tree"*) exit 0 ;;\n'
        f'  *"rev-parse HEAD"*) echo "{HEAD_REV}" ;;\n'
        '  *"status --porcelain"*) : ;;\n'  # clean tree -> no output
        "  *) : ;;\n"
        "esac\n",
    )

    wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    driver_sha = _qa_driver_digest(wheel)
    release_image = f"forge-qa-release:0.9.4-sha-{wheel_sha[:12]}-pinned-claude-2.1.245-codex-0.149.1"
    wheel_path = str(wheel.resolve())

    # Running container. The inspect branch supplies the complete release-QA
    # identity; the exec branch answers profile/workflow/credential probes.
    _write_exec(
        bin_dir / "docker",
        'sub="$1"; args="$*"\n'
        'case "$sub" in\n'
        "  info) exit 0 ;;\n"
        '  ps) echo "deadbeefcafe" ;;\n'
        "  inspect)\n"
        '    case "$args" in\n'
        f'      *org.opencontainers.image.revision*) printf "{image_rev}" ;;\n'
        f'      *io.multi-forge.qa.wheel-sha256*) printf "{wheel_sha}" ;;\n'
        f'      *io.multi-forge.qa.driver-sha256*) printf "{driver_sha}" ;;\n'
        '      *io.multi-forge.qa.forge-version*) printf "0.9.4" ;;\n'
        '      *io.multi-forge.qa.runtime-track*) printf "pinned" ;;\n'
        '      *io.multi-forge.qa.claude-version*) printf "2.1.245" ;;\n'
        '      *io.multi-forge.qa.codex-version*) printf "0.149.1" ;;\n'
        '      *io.multi-forge.qa.provider-profile*) printf "openrouter" ;;\n'
        '      *io.multi-forge.qa.artifact-mode*) printf "prebuilt" ;;\n'
        f'      *io.multi-forge.qa.wheel-path*) printf "%s" {wheel_path!r} ;;\n'
        '      *io.multi-forge.qa.codex-auth-mode*) printf "api-key" ;;\n'
        f'      *Config.Image*) printf "%s" {release_image!r} ;;\n'
        "      *) : ;;\n"
        "    esac ;;\n"
        "  exec)\n"
        '    case "$args" in\n'
        '      *"claude --version"*) printf "2.1.245 (Claude Code)\\n" ;;\n'
        '      *"codex --version"*) printf "codex-cli 0.149.1\\n" ;;\n'
        '      *FORGE_QA_PROVIDER_PROFILE*) printf "openrouter" ;;\n'
        '      *FORGE_QA_WORKFLOW_MODEL_A*) printf "wfa" ;;\n'
        '      *FORGE_QA_WORKFLOW_MODEL_B*) printf "wfb" ;;\n'
        '      *FORGE_QA_WORKFLOW_MODELS*) printf "wfm" ;;\n'
        "      *) : ;;\n"  # credential `test -n` probe etc. -> exit 0
        "    esac ;;\n"
        "  *) : ;;\n"
        "esac\n",
    )


def _run(tmp_path: Path, image_rev: str) -> subprocess.CompletedProcess[str]:
    wheel = _make_wheel(tmp_path)
    bin_dir = tmp_path / "bin"
    _make_stubs(bin_dir, image_rev, wheel)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["OPENROUTER_API_KEY"] = "test-key"
    env["CODEX_API_KEY"] = "test-codex-key"
    # Pin workflow vars (provider block uses :=) so the reuse equality checks are
    # decoupled from the real default model names.
    env["FORGE_QA_WORKFLOW_MODELS"] = "wfm"
    env["FORGE_QA_WORKFLOW_MODEL_A"] = "wfa"
    env["FORGE_QA_WORKFLOW_MODEL_B"] = "wfb"

    return subprocess.run(
        ["bash", str(SCRIPT), "--wheel", str(wheel)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
    )


def test_stale_running_container_is_rejected(tmp_path: Path) -> None:
    """A running container whose image predates HEAD must NOT be reused."""
    result = _run(tmp_path, image_rev=OLD_REV)

    assert result.returncode == 3, result.stderr
    assert "stale" in result.stderr.lower()
    assert "--reset" in result.stderr
    # The pre-fix bug printed this and exited 0 instead.
    assert "Reusing running container" not in result.stderr


def test_current_running_container_is_reused(tmp_path: Path) -> None:
    """A running container at HEAD must still reuse (no over-correction)."""
    result = _run(tmp_path, image_rev=HEAD_REV)

    assert result.returncode == 0, result.stderr
    assert "Reusing running container" in result.stderr
    assert "stale" not in result.stderr.lower()
    assert result.stdout.strip() == "forge-qa"
