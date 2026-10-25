"""Wheel-installed workers reject native delegation against offline, real CLI fixtures."""

import hashlib
import json
import subprocess
import uuid
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest

from tests.fixtures.runtime_versions import integration_runtime_versions

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]
REPO = Path(__file__).resolve().parents[3]


def test_worker_native_controls_from_clean_wheel(tmp_path: Path, forge_test_image: str | None):
    assert forge_test_image is not None, "Native worker probes require the Docker-host lane"
    built = subprocess.run(
        [
            "uv",
            "build",
            "--wheel",
            "--python",
            ">=3.11,<3.14",
            "--build-constraints",
            "requirements/build.txt",
            "--require-hashes",
            "--out-dir",
            str(tmp_path),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr
    (wheel,) = tmp_path.glob("*.whl")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        version = Parser().parsestr(archive.read(metadata_path).decode())["Version"]
    claude_version, codex_version = integration_runtime_versions()
    image = f"forge-worker-probe:{uuid.uuid4().hex[:12]}"
    # Reuse release QA's hash-checked install. Only the subsequent runtime probes are offline.
    build = subprocess.run(
        [
            "docker",
            "build",
            "-f",
            str(REPO / "docker/Dockerfile.qa"),
            "--build-arg",
            f"BASE_IMAGE={forge_test_image}",
            "--build-arg",
            f"FORGE_WHEEL_NAME={wheel.name}",
            "--build-arg",
            f"FORGE_WHEEL_SHA256={digest}",
            "--build-arg",
            f"FORGE_VERSION={version}",
            "--build-arg",
            "RUNTIME_TRACK=worker-probe",
            "--build-arg",
            f"CLAUDE_VERSION={claude_version}",
            "--build-arg",
            f"CODEX_VERSION={codex_version}",
            "-t",
            image,
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert build.returncode == 0, build.stderr
    try:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--mount",
                f"type=bind,src={REPO / 'tests/fixtures/worker_native_probe.py'},dst=/probe.py,readonly",
                "--entrypoint",
                "/opt/forge-qa/bin/python",
                image,
                "-I",
                "/probe.py",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(completed.stdout)
    evidence["wheel_sha256"] = digest
    evidence["wheel_name"] = wheel.name
    (tmp_path / "worker-native-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Worker native evidence: {tmp_path / 'worker-native-evidence.json'}")
    assert evidence["forge_file"].startswith("/opt/forge-qa/")
    assert wheel.name.startswith(f"multi_forge-{evidence['forge_version']}-")
    for probe in evidence["probes"]:
        if probe["runtime"] == "claude":
            if claude_version != "latest":
                assert probe["version"].split()[0] == claude_version
            if probe["mode"] == "legacy":
                assert "Skill" in probe["tools"] and probe["child_transcripts"] > 0
                assert probe["auto_memory_prompt"]
                continue
            assert not {"Agent", "Workflow", "SendMessage", "Skill"} & set(probe["tools"])
            assert probe["child_transcripts"] == 0
            assert not probe["auto_memory_prompt"], "settings.env must not re-enable worker auto-memory"
            assert any("No such tool available" in output or "denied" in output for output in probe["tool_outputs"])
            assert probe["environment"] == {
                "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "0",
                "CLAUDE_CODE_FORK_SUBAGENT": "0",
                "CLAUDE_CODE_DISABLE_WORKFLOWS": "1",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            }
            assert ("--bare" in probe["argv"]) is probe["bare"]
        else:
            if codex_version != "latest":
                assert probe["version"] == f"codex-cli {codex_version}"
            if probe["mode"] == "root":
                assert "multi_agent_v1.spawn_agent" in probe["discovered_tools"]
                assert any("agent_id" in output for output in probe["tool_outputs"])
                continue
            assert "spawn_agent" not in probe["tools"]
            assert not probe["discovered_tools"]
            assert any("unsupported call" in output and "spawn_agent" in output for output in probe["tool_outputs"])
            assert {
                "agents.enabled=false",
                "memories.use_memories=false",
                "memories.generate_memories=false",
            }.issubset(probe["argv"])
