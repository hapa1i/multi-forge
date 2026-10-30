"""Wheel-installed workers reject native delegation against offline, real CLI fixtures."""

import json
import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from forge.core.reactive.reviewer_runtime import MIN_REVIEWER_VERSION
from tests.fixtures.release_artifact import WheelArtifact, build_qa_image
from tests.fixtures.runtime_versions import integration_runtime_versions

pytestmark = [pytest.mark.integration, pytest.mark.docker_host]
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def worker_artifact(release_wheel: WheelArtifact, forge_test_image: str | None) -> Iterator[tuple[WheelArtifact, str]]:
    """Install the shared wheel with the native-worker image's runtime metadata."""
    assert forge_test_image is not None, "Native worker probes require the Docker-host lane"
    claude_version, codex_version = integration_runtime_versions()
    image = build_qa_image(
        release_wheel,
        forge_test_image,
        runtime_track="worker-probe",
        claude_version=claude_version,
        codex_version=codex_version,
    )
    try:
        yield release_wheel, image
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True, text=True, timeout=120)


def _probe(image: str, artifact: WheelArtifact, directory: Path, *args: str) -> dict:
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
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(completed.stdout)
    evidence["wheel_sha256"] = artifact.sha256
    evidence["wheel_name"] = artifact.path.name
    path = directory / "worker-native-evidence.json"
    path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Worker native evidence: {path}")
    assert evidence["forge_file"].startswith("/opt/forge-qa/")
    assert artifact.path.name.startswith(f"multi_forge-{evidence['forge_version']}-")
    return evidence


def _assert_claude_worker(probe: dict) -> None:
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
    assert probe["argv"].count("--settings") == 1
    assert probe["argv"].count("--disable-slash-commands") == 1


def test_worker_native_controls_from_clean_wheel(tmp_path: Path, worker_artifact):
    artifact, image = worker_artifact
    evidence = _probe(image, artifact, tmp_path)
    claude_version, codex_version = integration_runtime_versions()
    for probe in evidence["probes"]:
        if probe["runtime"] == "claude":
            if claude_version != "latest":
                assert probe["version"].split()[0] == claude_version
            if probe["mode"] == "legacy":
                assert "Skill" in probe["tools"] and probe["child_transcripts"] > 0
                assert probe["auto_memory_prompt"]
                continue
            _assert_claude_worker(probe)
        else:
            if codex_version != "latest":
                assert probe["version"] == f"codex-cli {codex_version}"
            tools = set(probe["advertised_tools"]) | set(probe["discovered_tools"])
            if probe["mode"] == "root":
                assert "multi_agent_v1.spawn_agent" in tools
                assert any("agent_id" in output for output in probe["tool_outputs"])
                continue
            assert not any(name.endswith("spawn_agent") for name in tools)
            assert any("unsupported call" in output and "spawn_agent" in output for output in probe["tool_outputs"])
            assert {
                "agents.enabled=false",
                "memories.use_memories=false",
                "memories.generate_memories=false",
            }.issubset(probe["argv"])
            assert probe["argv"][probe["argv"].index("--disable") + 1] == "multi_agent"
    resume = evidence["parallel_resume"]
    assert resume["source_sha256_before"] == resume["source_sha256_after"]
    assert len(set(resume["worker_session_ids"]) - {resume["source_session_id"]}) == 2


def test_guarded_worker_with_inherited_helper_from_clean_wheel(tmp_path: Path, worker_artifact):
    artifact, base_image = worker_artifact
    # The general QA pin predates the reviewer's isolation flags. Exercise an admitted binary separately.
    version = os.environ.get("FORGE_AUTH_TEST_CLAUDE_VERSION", MIN_REVIEWER_VERSION)
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(
        f"FROM {base_image}\n"
        f"RUN npm install --prefix /opt/worker-reviewer @anthropic-ai/claude-code@{version}\n"
        "ENV PATH=/opt/worker-reviewer/node_modules/.bin:$PATH\n"
    )
    image = f"forge-worker-reviewer-test:{uuid.uuid4().hex[:12]}"
    try:
        built = subprocess.run(
            ["docker", "build", "-t", image, str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert built.returncode == 0, built.stderr
        evidence = _probe(image, artifact, tmp_path, "reviewer")
        (probe,) = evidence["probes"]
        assert probe["version"].split()[0] == version
        _assert_claude_worker(probe)
        settings = json.loads(probe["argv"][probe["argv"].index("--settings") + 1])
        assert settings["apiKeyHelper"] == 'eval "$FORGE_REVIEWER_API_KEY_HELPER"'
        assert "fixture-not-a-provider-key" not in " ".join(probe["argv"])
    finally:
        subprocess.run(["docker", "image", "rm", image], capture_output=True, text=True, timeout=120)
