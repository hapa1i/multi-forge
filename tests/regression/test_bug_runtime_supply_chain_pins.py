"""Runtime installs must not drift to host versions or publish unverified binaries."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.fixtures import docker, runtime_versions

pytestmark = pytest.mark.regression
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def native_installer():
    spec = importlib.util.spec_from_file_location(
        "install_claude_native", REPO_ROOT / "docker/install-claude-native.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_docker_and_integration_defaults_match_reviewed_qa_track(monkeypatch):
    pins = json.loads(runtime_versions.RUNTIME_MATRIX.read_text())["tracks"]["pinned"]
    monkeypatch.delenv("CLAUDE_VERSION", raising=False)
    monkeypatch.delenv("CODEX_VERSION", raising=False)
    expected = (pins["claude"]["version"], pins["codex"]["version"])
    assert runtime_versions.integration_runtime_versions() == expected
    dockerfile = (REPO_ROOT / "docker/Dockerfile.forge").read_text()
    for name, version in zip(("CLAUDE_VERSION", "CODEX_VERSION"), expected):
        assert re.search(rf"^ARG {name}={re.escape(version)}$", dockerfile, re.MULTILINE)


def test_explicit_runtime_overrides_are_preserved():
    assert runtime_versions.integration_runtime_versions({"CLAUDE_VERSION": "2.1.294", "CODEX_VERSION": "latest"}) == (
        "2.1.294",
        "latest",
    )


@pytest.mark.parametrize("value", ["", "stable", "^2.1.0", "2.1.0;echo bad", "../latest"])
def test_nonexact_runtime_overrides_refuse(value):
    with pytest.raises(ValueError, match="CLAUDE_VERSION must be an exact version"):
        runtime_versions.integration_runtime_versions({"CLAUDE_VERSION": value})


def test_mutable_default_in_qa_matrix_refuses(monkeypatch, tmp_path):
    matrix = tmp_path / "matrix.json"
    matrix.write_text(json.dumps({"tracks": {"pinned": {"claude": {"version": "latest"}}}}))
    monkeypatch.setattr(runtime_versions, "RUNTIME_MATRIX", matrix)
    with pytest.raises(ValueError, match="exact claude version"):
        runtime_versions.integration_runtime_versions({})


@pytest.mark.parametrize("prepared", [False, True])
def test_latest_fixture_refreshes_once_and_reuses_runner_image(monkeypatch, tmp_path, prepared):
    image_name = "forge-claude-test:latest-codex-0.149.1"
    monkeypatch.setattr(docker, "CLAUDE_CODE_VERSION", "latest")
    monkeypatch.setattr(docker, "CODEX_CLI_VERSION", "0.149.1")
    monkeypatch.setattr(docker, "_find_repo_root", lambda: tmp_path)
    monkeypatch.setattr(docker, "_get_forge_revision", lambda root: "revision")
    monkeypatch.setattr(docker, "_get_image_revision", lambda image: "revision")
    monkeypatch.setattr(docker, "_image_exists", lambda image: True)
    monkeypatch.setattr(docker, "_require_runtime_image", lambda image: None)
    monkeypatch.setenv("FORGE_INTEGRATION_PREBUILT_IMAGE", image_name if prepared else "")
    (tmp_path / "docker").mkdir()
    (tmp_path / "docker/Dockerfile.forge").touch()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(docker.subprocess, "run", run)
    assert docker.forge_test_image.__wrapped__(True, False) == image_name
    assert len(calls) == (0 if prepared else 1)
    if not prepared:
        assert "--pull" in calls[0] and "--no-cache" in calls[0]


@pytest.mark.parametrize(
    "version,architecture",
    [("latest", "amd64"), ("2.1.246", "amd64"), ("2.1.245", "s390x")],
)
def test_native_unreviewed_version_or_platform_refuses_before_download(
    native_installer, monkeypatch, tmp_path, version, architecture
):
    def unexpected_download(*args, **kwargs):
        pytest.fail("Unreviewed native download was attempted")

    monkeypatch.setattr(native_installer.urllib.request, "urlopen", unexpected_download)
    destination = tmp_path / "native/claude"
    with pytest.raises(ValueError, match="No reviewed native Claude checksum"):
        native_installer.install(version, architecture, destination)
    assert not destination.parent.exists()


@pytest.mark.parametrize("tampered", [False, True])
def test_native_download_publishes_only_verified_bytes(native_installer, monkeypatch, tmp_path, tampered):
    expected = b"reviewed fixture executable"
    actual = b"replacement payload" if tampered else expected
    monkeypatch.setattr(
        native_installer,
        "CHECKSUMS",
        {"2.1.245": {"arm64": ("linux-arm64", hashlib.sha256(expected).hexdigest())}},
    )
    requests = []

    def download(url, **kwargs):
        requests.append(url)
        return io.BytesIO(actual)

    monkeypatch.setattr(native_installer.urllib.request, "urlopen", download)
    destination = tmp_path / "native/claude"
    destination.parent.mkdir()
    destination.write_bytes(b"previous installation")
    if tampered:
        with pytest.raises(ValueError, match="checksum mismatch"):
            native_installer.install("2.1.245", "arm64", destination)
        assert destination.read_bytes() == b"previous installation"
    else:
        native_installer.install("2.1.245", "arm64", destination)
        assert destination.read_bytes() == expected
        assert os.access(destination, os.X_OK)
    assert requests == ["https://downloads.claude.ai/claude-code-releases/2.1.245/linux-arm64/claude"]
    assert list(destination.parent.iterdir()) == [destination]
