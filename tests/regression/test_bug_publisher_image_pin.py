"""Publishing must retain OIDC and attestations when pinning the official container."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def publishing_job() -> dict[str, Any]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
    return workflow["jobs"]["publish"]


def test_publisher_uses_immutable_official_container(publishing_job: dict[str, Any]) -> None:
    step = next(step for step in publishing_job["steps"] if step["name"] == "Publish to PyPI")
    assert re.fullmatch(r"docker://ghcr\.io/pypa/gh-action-pypi-publish@sha256:[0-9a-f]{64}", step["uses"])
    assert "run" not in step
    assert "with" not in step  # Preserve the image's official entrypoint instead of overriding it.


def test_container_inputs_preserve_trusted_publishing_and_attestations(publishing_job: dict[str, Any]) -> None:
    step = next(step for step in publishing_job["steps"] if step["name"] == "Publish to PyPI")
    assert publishing_job["permissions"] == {"id-token": "write"}
    assert publishing_job["environment"] == "pypi"
    # The container reads these environment variables; the composite action no longer supplies defaults.
    assert step["env"] == {
        "INPUT_USER": "__token__",
        "INPUT_PASSWORD": "",
        "INPUT_REPOSITORY_URL": "https://upload.pypi.org/legacy/",
        "INPUT_PACKAGES_DIR": "dist",
        "INPUT_VERIFY_METADATA": "true",
        "INPUT_SKIP_EXISTING": "false",
        "INPUT_VERBOSE": "true",
        "INPUT_PRINT_HASH": "true",
        "INPUT_ATTESTATIONS": "true",
    }
