"""Tests for the release-QA wheel identity helper."""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "qa-artifact.py"
MATRIX = REPO_ROOT / "src" / "skills" / "qa" / "resources" / "runtime-matrix.json"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("forge_qa_artifact", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


QA_ARTIFACT = _load_script()


def _wheel(tmp_path: Path, *, filename_version: str = "1.0.0", metadata_version: str = "1.0.0") -> Path:
    wheel = tmp_path / f"multi_forge-{filename_version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"multi_forge-{metadata_version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: multi-forge\nVersion: {metadata_version}\n",
        )
    return wheel


def test_pinned_identity_uses_exact_wheel_and_distinct_release_namespace(
    tmp_path: Path,
) -> None:
    wheel = _wheel(tmp_path)
    identity = QA_ARTIFACT.inspect_artifact(wheel_path=wheel, matrix_path=MATRIX, runtime_track="pinned")

    assert identity["wheel_path"] == str(wheel.resolve())
    assert identity["forge_version"] == "1.0.0"
    assert len(identity["sha256"]) == 64
    assert identity["claude_version"] == "2.1.245"
    assert identity["codex_version"] == "0.149.1"
    assert identity["base_image"] == "forge-claude-test:2.1.245-codex-0.149.1"
    assert identity["release_image"].startswith("forge-qa-release:1.0.0-sha-")
    assert identity["release_image"] != identity["base_image"]
    assert identity["runtime_track_blocking"] is True


def test_latest_track_is_explicitly_non_blocking(tmp_path: Path) -> None:
    identity = QA_ARTIFACT.inspect_artifact(
        wheel_path=_wheel(tmp_path),
        matrix_path=MATRIX,
        runtime_track="latest",
    )

    assert identity["runtime_track_blocking"] is False
    assert identity["claude_version"] == "latest"
    assert identity["codex_version"] == "latest"
    assert "-latest-" in identity["release_image"]


@pytest.mark.parametrize("candidate", ["missing.whl", "not-a-wheel.txt"])
def test_missing_or_non_wheel_artifact_fails(tmp_path: Path, candidate: str) -> None:
    path = tmp_path / candidate
    if path.suffix != ".whl":
        path.write_text("not a wheel", encoding="utf-8")

    with pytest.raises(QA_ARTIFACT.ArtifactError):
        QA_ARTIFACT.inspect_artifact(wheel_path=path, matrix_path=MATRIX, runtime_track="pinned")


def test_filename_and_metadata_versions_must_match(tmp_path: Path) -> None:
    with pytest.raises(QA_ARTIFACT.ArtifactError, match="does not match"):
        QA_ARTIFACT.inspect_artifact(
            wheel_path=_wheel(tmp_path, filename_version="1.0.0", metadata_version="1.0.1"),
            matrix_path=MATRIX,
            runtime_track="pinned",
        )


def test_unknown_runtime_track_fails(tmp_path: Path) -> None:
    with pytest.raises(QA_ARTIFACT.ArtifactError, match="unknown runtime track"):
        QA_ARTIFACT.inspect_artifact(
            wheel_path=_wheel(tmp_path),
            matrix_path=MATRIX,
            runtime_track="nightly",
        )


def test_cli_emits_one_json_object(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    wheel = _wheel(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT),
            "--wheel",
            str(wheel),
            "--matrix",
            str(MATRIX),
            "--runtime-track",
            "pinned",
        ],
    )

    assert QA_ARTIFACT.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["wheel_filename"] == wheel.name
