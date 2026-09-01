"""Exact-wheel isolation contract for the release-QA image layer."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import uuid
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.qa"
QA_SKILL_ROOT = REPO_ROOT / "src" / "skills" / "qa"


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

    driver_probe = subprocess.run(
        [
            sys.executable,
            str(QA_SKILL_ROOT / "scripts" / "qa-artifact.py"),
            "--wheel",
            str(wheel),
            "--matrix",
            str(QA_SKILL_ROOT / "resources" / "runtime-matrix.json"),
            "--skill-root",
            str(QA_SKILL_ROOT),
            "--runtime-track",
            "pinned",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert driver_probe.returncode == 0, driver_probe.stderr
    driver_identity = json.loads(driver_probe.stdout)
    assert len(driver_identity["qa_driver_sha256"]) == 64

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
    dispatcher_probe = """
import json
import pathlib

metadata = json.loads(pathlib.Path("/root/.forge/runtime.json").read_text())
doctor = json.loads(pathlib.Path("/tmp/forge-doctor.json").read_text())
print(json.dumps({
    "metadata_launcher": metadata["forge_binary_path"],
    "doctor_launcher": doctor["hook_dispatcher"]["forge_binary_path"],
    "dispatcher": metadata["dispatcher_path"],
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
                'set -euo pipefail; test "$(command -v forge)" = /usr/local/bin/forge '
                '&& test "$(readlink /usr/local/bin/forge)" = /opt/forge-qa/bin/forge '
                '&& test "$DISABLE_AUTOUPDATER" = 1 '
                "&& forge --version >/dev/null "
                "&& forge extension enable --scope user --profile minimal --with hooks,skills --without commands "
                "> /tmp/forge-enable.log "
                "&& grep -qx 'name: smoke-test' /root/.claude/skills/smoke-test/SKILL.md "
                "&& forge extension doctor --json > /tmp/forge-doctor.json "
                "&& mv /forge/src/forge /forge/src/forge.unavailable "
                f"&& /opt/forge-qa/bin/python -I -c {shlex.quote(probe_code)} "
                f"&& /opt/forge-qa/bin/python -I -c {shlex.quote(dispatcher_probe)} "
                "&& (set +e; FORGE_AUTHORITY_MARKER='{}' /root/.forge/bin/forge-hook authority-check "
                '> /tmp/forge-hook-probe.log 2>&1; status=$?; test "$status" -ne 127)',
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert probe.returncode == 0, probe.stderr
        evidence, dispatcher = [json.loads(line) for line in probe.stdout.splitlines()]
        assert evidence["version"] == version
        assert evidence["forge_file"].startswith("/opt/forge-qa/")
        assert evidence["resource_root"].startswith("/opt/forge-qa/")
        assert evidence["extensions_root"].startswith("/opt/forge-qa/")
        assert all(not str(path).startswith("/forge") for path in evidence["sys_path"])
        assert all(evidence["qa_resources"].values())
        assert evidence["checklist_fragments"] == 21
        assert dispatcher["metadata_launcher"] == "/usr/local/bin/forge"
        assert dispatcher["doctor_launcher"] == "/usr/local/bin/forge"
        assert dispatcher["dispatcher"] == "/root/.forge/bin/forge-hook"
    finally:
        subprocess.run(["docker", "rmi", image], capture_output=True, text=True, timeout=120)
