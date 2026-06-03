"""Regression: QA start-container.sh must not reuse a stale running container.

Bug: the running-container reuse path in
``.claude``/``src/skills/qa/scripts/start-container.sh`` exited 0 before any
image-revision check. A container built from an image older than the current
checkout was therefore reused indefinitely, so ``/forge:qa`` silently validated
stale code (e.g. a proxy build predating the system-role 422 fix) while
reporting success.

Fix: compute ``FORGE_REV`` before the reuse fast-path and refuse to reuse a
running container whose baked ``org.opencontainers.image.revision`` label does
not equal ``FORGE_REV``, pointing the user at ``--reset``.

Affected: src/skills/qa/scripts/start-container.sh
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "start-container.sh"

HEAD_REV = "1111111111111111111111111111111111111111"
OLD_REV = "0000000000000000000000000000000000000000"


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_stubs(bin_dir: Path, image_rev: str) -> None:
    """Stub git/docker/claude so the script reaches the reuse staleness guard.

    git reports a clean work tree at HEAD_REV; docker reports a *running*
    forge-qa container whose image revision label is ``image_rev``.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)

    _write_exec(
        bin_dir / "claude",
        'echo "9.9.9 (stub)"\n',
    )

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

    # Running container; image revision == image_rev. The exec branch answers the
    # profile/workflow/credential probes so a *fresh* container can fully reuse.
    _write_exec(
        bin_dir / "docker",
        'sub="$1"; args="$*"\n'
        'case "$sub" in\n'
        "  info) exit 0 ;;\n"
        '  ps) echo "deadbeefcafe" ;;\n'
        f'  inspect) echo "{image_rev}" ;;\n'
        "  exec)\n"
        '    case "$args" in\n'
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
    bin_dir = tmp_path / "bin"
    _make_stubs(bin_dir, image_rev)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["OPENROUTER_API_KEY"] = "test-key"
    # Pin workflow vars (provider block uses :=) so the reuse equality checks are
    # decoupled from the real default model names.
    env["FORGE_QA_WORKFLOW_MODELS"] = "wfm"
    env["FORGE_QA_WORKFLOW_MODEL_A"] = "wfa"
    env["FORGE_QA_WORKFLOW_MODEL_B"] = "wfb"

    return subprocess.run(
        ["bash", str(SCRIPT)],
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
