"""Regression: every Docker test runner must select the same runtime image identity."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression

REPO_ROOT = Path(__file__).resolve().parents[2]
SHELL_RUNNERS = (
    REPO_ROOT / "scripts" / "test-integration.sh",
    REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "start-container.sh",
)
PYTHON_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "docker.py"
FORGE_DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.forge"
EXPECTED_SHELL_TAG = "forge-claude-test:${CLAUDE_VERSION}-codex-${CODEX_VERSION}"


def _shell_assignment(source: str, name: str) -> str:
    match = re.search(rf'^{name}="([^"]+)"$', source, flags=re.MULTILINE)
    assert match is not None, f"missing {name} assignment"
    return match.group(1)


def test_shell_runners_share_codex_versioned_image_contract() -> None:
    for runner in SHELL_RUNNERS:
        source = runner.read_text(encoding="utf-8")
        assert _shell_assignment(source, "IMAGE_NAME") == EXPECTED_SHELL_TAG, runner
        assert "CODEX_VERSION=\"$(codex --version 2>/dev/null | awk '{print $NF}')\"" in source, runner
        assert '--build-arg "CODEX_VERSION=$CODEX_VERSION"' in source, runner


def test_python_fixture_uses_the_same_codex_versioned_identity() -> None:
    source = PYTHON_FIXTURE.read_text(encoding="utf-8")
    assert 'f"forge-claude-test:{CLAUDE_CODE_VERSION}-codex-{CODEX_CLI_VERSION}"' in source
    assert 'f"CODEX_VERSION={CODEX_CLI_VERSION}"' in source


def test_dockerfile_example_uses_the_canonical_image_tag_shape() -> None:
    source = FORGE_DOCKERFILE.read_text(encoding="utf-8")
    example = re.search(
        r"--build-arg CLAUDE_VERSION=(?P<claude>[\w.-]+) \\\n"
        r"#\s+--build-arg CODEX_VERSION=(?P<codex>[\w.-]+) -t "
        r"forge-claude-test:(?P=claude)-codex-(?P=codex) \.",
        source,
    )
    assert example is not None
