"""A user-installed QA driver must resolve Docker inputs from the action checkout."""

import shutil
import subprocess

import pytest

from tests.src.skills.test_qa_start_container import (
    QA_SKILL_ROOT,
    _base_env,
    _fresh_container_docker,
    _wheel,
)

pytestmark = pytest.mark.regression


def test_installed_skill_uses_current_source_checkout(tmp_path):
    wheel = _wheel(tmp_path)
    skill = tmp_path / "home/.claude/skills/qa"
    shutil.copytree(QA_SKILL_ROOT, skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    repo = QA_SKILL_ROOT.parents[2]
    env = _base_env(tmp_path, _fresh_container_docker(tmp_path / "docker.log"))
    result = subprocess.run(
        ["bash", str(skill / "scripts/start-container.sh"), "--wheel", str(wheel)],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert str(repo / "docker/Dockerfile.forge") in (tmp_path / "docker.log").read_text()
