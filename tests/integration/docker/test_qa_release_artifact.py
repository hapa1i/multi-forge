"""Exact-wheel isolation contract for the release-QA image layer."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.release_artifact import WheelArtifact, build_qa_image

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.qa"
QA_SKILL_ROOT = REPO_ROOT / "src" / "skills" / "qa"


def test_release_image_imports_only_the_exact_wheel(release_wheel: WheelArtifact, forge_test_image: str | None) -> None:
    assert forge_test_image is not None, "release artifact isolation requires the Docker-host test lane"

    wheel, version = release_wheel.path, release_wheel.version

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

    image = build_qa_image(release_wheel, forge_test_image)

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
