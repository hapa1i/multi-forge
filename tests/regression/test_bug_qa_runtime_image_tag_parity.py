"""Regression: editable runners align while release QA has a non-colliding identity."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_RUNNER = REPO_ROOT / "scripts" / "test-integration.sh"
QA_RUNNER = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "start-container.sh"
QA_ARTIFACT = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "qa-artifact.py"
PYTHON_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "docker.py"
FORGE_DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.forge"
EXPECTED_SHELL_TAG = "forge-claude-test:${CLAUDE_VERSION}-codex-${CODEX_VERSION}"


def _shell_assignment(source: str, name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', source, flags=re.MULTILINE)
    assert match is not None, f"missing {name} assignment"
    return match.group(1)


def test_editable_integration_runners_share_codex_versioned_image_contract() -> None:
    source = INTEGRATION_RUNNER.read_text(encoding="utf-8")
    assert _shell_assignment(source, "IMAGE_NAME") == EXPECTED_SHELL_TAG
    assert "CODEX_VERSION=\"$(codex --version 2>/dev/null | awk '{print $NF}')\"" in source
    assert '--build-arg "CODEX_VERSION=$CODEX_VERSION"' in source


def test_python_fixture_uses_the_same_codex_versioned_identity() -> None:
    source = PYTHON_FIXTURE.read_text(encoding="utf-8")
    assert 'f"forge-claude-test:{CLAUDE_CODE_VERSION}-codex-{CODEX_CLI_VERSION}"' in source
    assert 'f"CODEX_VERSION={CODEX_CLI_VERSION}"' in source


def test_wheel_qa_deliberately_uses_a_distinct_artifact_identity() -> None:
    runner = QA_RUNNER.read_text(encoding="utf-8")
    artifact = QA_ARTIFACT.read_text(encoding="utf-8")

    assert "runtime-matrix.json" in runner
    assert 'BASE_IMAGE_NAME="$(json_field "$artifact_json" base_image)"' in runner
    assert 'IMAGE_NAME="$(json_field "$artifact_json" release_image)"' in runner
    assert '--build-arg "BASE_IMAGE=$BASE_IMAGE_NAME"' in runner
    assert '--build-arg "FORGE_WHEEL_SHA256=$WHEEL_SHA256"' in runner
    assert '--build-arg "RUNTIME_TRACK=$RUNTIME_TRACK"' in runner
    assert "forge-qa-release:" in artifact
    assert "forge-claude-test:" in artifact


def test_dockerfile_example_uses_the_canonical_image_tag_shape() -> None:
    source = FORGE_DOCKERFILE.read_text(encoding="utf-8")
    example = re.search(
        r"--build-arg CLAUDE_VERSION=(?P<claude>[\w.-]+) \\\n"
        r"#\s+--build-arg CODEX_VERSION=(?P<codex>[\w.-]+) -t "
        r"forge-claude-test:(?P=claude)-codex-(?P=codex) \.",
        source,
    )
    assert example is not None
