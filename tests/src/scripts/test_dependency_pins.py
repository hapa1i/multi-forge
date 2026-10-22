"""Constraint exports must fail on graph drift rather than silently re-resolve."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("dependency_pins", ROOT / "scripts/check-dependency-pins.py")
assert SPEC is not None and SPEC.loader is not None
PINS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PINS)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for filename in ("pyproject.toml", "uv.lock", ".python-version"):
        shutil.copyfile(ROOT / filename, tmp_path / filename)
    shutil.copytree(ROOT / "requirements", tmp_path / "requirements")
    return tmp_path


def test_committed_exports_match_reviewed_lock(project: Path) -> None:
    assert PINS.check(project) == []


def test_changed_runtime_constraint_is_rejected_and_can_be_regenerated(project: Path) -> None:
    runtime = project / "requirements/runtime.txt"
    runtime.write_text(runtime.read_text().replace("litellm==1.102.0", "litellm==1.107.0"))
    assert PINS.check(project) == ["requirements/runtime.txt"]
    PINS.check(project, write=True)
    assert PINS.check(project) == []
    assert "litellm==1.102.0" in runtime.read_text()


def test_changed_build_hash_is_rejected(project: Path) -> None:
    build = project / "requirements/build.txt"
    build.write_text(build.read_text().replace("--hash=sha256:", "--hash=sha256:0", 1))
    assert PINS.check(project) == ["requirements/build.txt"]


def test_build_backend_must_match_locked_group(project: Path) -> None:
    metadata = project / "pyproject.toml"
    metadata.write_text(metadata.read_text().replace('requires = ["hatchling==1.32.4"]', 'requires = ["hatchling"]'))
    with pytest.raises(ValueError, match="build-system.requires"):
        PINS.check(project)


def test_stale_lock_is_not_updated(project: Path) -> None:
    metadata = project / "pyproject.toml"
    metadata.write_text(metadata.read_text().replace("litellm==1.102.0", "litellm==1.107.0"))
    before = (project / "uv.lock").read_bytes()
    with pytest.raises(subprocess.CalledProcessError):
        PINS.check(project)
    assert (project / "uv.lock").read_bytes() == before


def test_project_build_constraints_cannot_drop_transitive_pin(project: Path) -> None:
    metadata = project / "pyproject.toml"
    metadata.write_text(metadata.read_text().replace('    "trove-classifiers==2026.9.21.13",\n', ""))
    # Keep the edited project and lock in agreement to reach the export consistency check.
    lock = project / "uv.lock"
    lock.write_text(lock.read_text().replace('    { name = "trove-classifiers", specifier = "==2026.9.21.13" },\n', ""))
    with pytest.raises(ValueError, match="build-constraint-dependencies"):
        PINS.check(project)
