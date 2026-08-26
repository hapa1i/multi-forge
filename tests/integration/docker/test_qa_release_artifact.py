"""Exact-wheel isolation contract for the release-QA image layer."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import uuid
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.qa"


def _wheel_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        return Parser().parsestr(archive.read(metadata_path).decode("utf-8"))["Version"]


def test_release_image_imports_only_the_exact_wheel(tmp_path: Path, forge_test_image: str | None) -> None:
    assert forge_test_image is not None, "release artifact isolation requires the Docker-host test lane"

    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    version = _wheel_version(wheel)
    image = f"forge-qa-artifact-test:{uuid.uuid4().hex[:12]}"

    build = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(DOCKERFILE),
            "--build-arg",
            f"BASE_IMAGE={forge_test_image}",
            "--build-arg",
            f"FORGE_WHEEL_NAME={wheel.name}",
            "--build-arg",
            f"FORGE_WHEEL_SHA256={digest}",
            "--build-arg",
            f"FORGE_VERSION={version}",
            "--build-arg",
            "FORGE_REV=artifact-test",
            "--build-arg",
            "RUNTIME_TRACK=test",
            "--build-arg",
            "CLAUDE_VERSION=test",
            "--build-arg",
            "CODEX_VERSION=test",
            "-t",
            image,
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, build.stderr

    probe_code = """
import importlib.metadata as metadata
import importlib.resources as resources
import json
import pathlib
import sys
import forge
from forge.install.installer import get_extensions_root

print(json.dumps({
    "version": metadata.version("multi-forge"),
    "forge_file": forge.__file__,
    "resource_root": str(resources.files("forge")),
    "extensions_root": str(get_extensions_root()),
    "sys_path": sys.path,
    "qa_resources": {
        path: (get_extensions_root() / "skills" / "qa" / path).is_file()
        for path in (
            "resources/checklist.md",
            "resources/coverage-map.md",
            "resources/execution-budget.json",
            "resources/report-template.md",
            "resources/runtime-matrix.json",
            "scripts/qa-artifact.py",
            "scripts/qa-run-metrics.py",
            "scripts/qa-selection.py",
            "scripts/start-container.sh",
            "scripts/walkthrough-state.py",
        )
    },
    "checklist_fragments": len(list((get_extensions_root() / "skills" / "qa" / "resources/checklist").glob("*.md"))),
}))
"""
    try:
        probe = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-w",
                "/workspace",
                image,
                "bash",
                "-c",
                'set -euo pipefail; test "$(command -v forge)" = /opt/forge-qa/bin/forge '
                "&& forge --version >/dev/null "
                "&& mv /forge/src/forge /forge/src/forge.unavailable "
                f"&& /opt/forge-qa/bin/python -I -c {shlex.quote(probe_code)}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert probe.returncode == 0, probe.stderr
        evidence = json.loads(probe.stdout)
        assert evidence["version"] == version
        assert evidence["forge_file"].startswith("/opt/forge-qa/")
        assert evidence["resource_root"].startswith("/opt/forge-qa/")
        assert evidence["extensions_root"].startswith("/opt/forge-qa/")
        assert all(not str(path).startswith("/forge") for path in evidence["sys_path"])
        assert all(evidence["qa_resources"].values())
        assert evidence["checklist_fragments"] == 21
    finally:
        subprocess.run(["docker", "rmi", image], capture_output=True, text=True, timeout=120)
