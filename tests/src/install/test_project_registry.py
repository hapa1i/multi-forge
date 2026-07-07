"""Tests for the trusted project registry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from forge.install.project_registry import (
    PROJECT_REGISTRY_VERSION,
    ProjectRegistryCorruptedError,
    ProjectRegistryStore,
    diagnose_project_registry,
)


def test_enroll_canonicalizes_symlink_and_lookup_hits_inside_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".forge").mkdir(parents=True)
    (repo / "src").mkdir()
    link = tmp_path / "repo-link"
    try:
        link.symlink_to(repo, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    store = ProjectRegistryStore(tmp_path / "projects.json")
    result = store.enroll(link, "enable")

    assert result.created is True
    assert result.entry.canonical_path == str(repo.resolve())
    lookup = store.lookup_enrolled_root(repo / "src")
    assert lookup.enrolled is True
    assert lookup.enrolled_root == str(repo.resolve())


def test_case_variant_lookup_key_unifies(tmp_path: Path) -> None:
    repo = tmp_path / "Repo"
    repo.mkdir()
    store = ProjectRegistryStore(tmp_path / "projects.json")

    store.enroll(repo, "enable")

    assert store.contains_root(str(repo).swapcase())


def test_relative_and_trailing_paths_are_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(tmp_path)
    store = ProjectRegistryStore(tmp_path / "projects.json")

    first = store.enroll(Path("repo"), "enable")
    second = store.enroll(Path("repo/"), "enable")

    assert first.created is True
    assert second.created is False
    assert len(store.read_strict().projects) == 1


def test_strict_read_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"schema_version": PROJECT_REGISTRY_VERSION + 1, "projects": []}), encoding="utf-8")
    store = ProjectRegistryStore(path)

    with pytest.raises(ProjectRegistryCorruptedError, match="incompatible schema_version"):
        store.read_strict()


def test_hook_read_fails_open_with_degraded_reason(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text("{not json", encoding="utf-8")
    store = ProjectRegistryStore(path)

    result = store.read_for_hook()

    assert result.enrolled_roots == ()
    assert result.degraded is not None


def test_stale_roots_are_reported_without_pruning(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    store = ProjectRegistryStore(tmp_path / "projects.json")
    store.enroll(repo, "enable")
    shutil.rmtree(repo)

    stale = store.stale_roots()
    diag = diagnose_project_registry(store.path)

    assert stale == (str(repo.resolve()),)
    assert diag.status == "stale_roots"
    assert diag.stale_roots == stale


def test_doctor_reports_corrupt_registry_with_reset_path(tmp_path: Path) -> None:
    path = tmp_path / "projects.json"
    path.write_text("{not json", encoding="utf-8")

    diag = diagnose_project_registry(path)

    assert diag.status == "corrupt"
    assert diag.error is not None
    assert diag.advice is not None
    assert "forge extension enable" in diag.advice
