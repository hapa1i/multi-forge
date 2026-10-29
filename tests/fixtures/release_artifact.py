"""Build one constrained wheel and install its exact bytes into the release-QA image."""

from __future__ import annotations

import hashlib
import subprocess
import uuid
import zipfile
from dataclasses import dataclass
from email.parser import Parser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class WheelArtifact:
    path: Path
    sha256: str
    version: str


def build_wheel(directory: Path) -> WheelArtifact:
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
            str(directory),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert built.returncode == 0, built.stderr
    (wheel,) = directory.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        metadata_path = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        version = Parser().parsestr(archive.read(metadata_path).decode())["Version"]
    return WheelArtifact(wheel, hashlib.sha256(wheel.read_bytes()).hexdigest(), version)


def build_qa_image(
    artifact: WheelArtifact,
    base_image: str,
    *,
    runtime_track: str = "test",
    claude_version: str = "test",
    codex_version: str = "test",
    forge_rev: str = "artifact-test",
) -> str:
    image = f"forge-qa-artifact-test:{uuid.uuid4().hex[:12]}"
    arguments = {
        "BASE_IMAGE": base_image,
        "FORGE_WHEEL_NAME": artifact.path.name,
        "FORGE_WHEEL_SHA256": artifact.sha256,
        "FORGE_VERSION": artifact.version,
        "FORGE_REV": forge_rev,
        "RUNTIME_TRACK": runtime_track,
        "CLAUDE_VERSION": claude_version,
        "CODEX_VERSION": codex_version,
    }
    command = ["docker", "build", "-f", str(REPO / "docker/Dockerfile.qa")]
    for name, value in arguments.items():
        command.extend(["--build-arg", f"{name}={value}"])
    built = subprocess.run(
        [*command, "-t", image, str(artifact.path.parent)], capture_output=True, text=True, timeout=600
    )
    assert built.returncode == 0, built.stderr
    return image
