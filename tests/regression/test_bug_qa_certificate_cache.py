"""Ignored Docker certificate bytes must participate in the runtime cache identity."""

import re
import shutil
import subprocess

import pytest

from tests.src.skills.test_qa_start_container import (
    QA_SKILL_ROOT,
    SCRIPT,
    _base_env,
    _fresh_container_docker,
    _wheel,
)

pytestmark = pytest.mark.regression


def test_certificate_rotation_and_removal_change_build_identity(tmp_path):
    repo = tmp_path / "checkout"
    (repo / "docker/certs").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "multi-forge"\n')
    for name in ("Dockerfile.forge", "Dockerfile.qa"):
        shutil.copyfile(QA_SKILL_ROOT.parents[2] / "docker" / name, repo / "docker" / name)
    wheel = _wheel(tmp_path)
    log = tmp_path / "docker.log"
    env = _base_env(tmp_path, _fresh_container_docker(log))
    identities = []
    cert = repo / "docker/certs/company.crt"
    for content in (None, "first synthetic CA", "rotated synthetic CA", None):
        if content is None:
            cert.unlink(missing_ok=True)
        else:
            cert.write_text(content)
        log.unlink(missing_ok=True)
        result = subprocess.run(
            ["bash", str(SCRIPT), "--wheel", str(wheel)], cwd=repo, env=env, capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
        identities.append(re.findall(r"FORGE_REV=(\S+)", log.read_text())[0])
    assert identities[0] == identities[3]
    assert len(set(identities[:3])) == 3
