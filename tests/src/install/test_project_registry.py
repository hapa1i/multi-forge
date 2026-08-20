"""Tests for the trusted project registry."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

import pytest

from forge.install import project_registry
from forge.install.project_registry import (
    PROJECT_REGISTRY_VERSION,
    ProjectRegistryCorruptedError,
    ProjectRegistryStore,
    diagnose_project_registry,
)


def test_enroll_canonicalizes_symlink_and_lookup_hits_inside_root(
    tmp_path: Path,
    directory_symlink: Callable[[Path, Path], Path],
) -> None:
    repo = tmp_path / "repo"
    (repo / ".forge").mkdir(parents=True)
    (repo / "src").mkdir()
    link = directory_symlink(repo, tmp_path / "repo-link")

    store = ProjectRegistryStore(tmp_path / "projects.json")
    result = store.enroll(link, "enable")

    assert result.created is True
    assert result.entry.canonical_path == str(repo.resolve())
    lookup = store.lookup_enrolled_root(repo / "src")
    assert lookup.enrolled is True
    assert lookup.enrolled_root == str(repo.resolve())


@pytest.mark.parametrize(
    "paths_refer_to_same_file",
    [True, False],
    ids=["case-insensitive-alias", "case-sensitive-distinct-roots"],
)
def test_case_variant_identity_follows_filesystem_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paths_refer_to_same_file: bool,
) -> None:
    trusted = tmp_path / "Repo"
    variant = tmp_path / "repo"
    monkeypatch.setattr(
        project_registry,
        "canonicalize_project_path",
        lambda path: str(Path(path).expanduser().absolute()),
    )
    monkeypatch.setattr(
        project_registry,
        "_same_existing_path",
        lambda _left, _right: paths_refer_to_same_file,
    )
    monkeypatch.setattr("forge.core.ops.context.find_forge_root", lambda _start: variant)
    store = ProjectRegistryStore(tmp_path / "projects.json")

    first = store.enroll(trusted, "enable")

    assert first.entry.canonical_path == str(trusted)
    assert store.contains_root(variant) is paths_refer_to_same_file

    lookup = store.lookup_enrolled_root(variant)
    assert lookup.enrolled is paths_refer_to_same_file
    assert lookup.enrolled_root == (str(trusted) if paths_refer_to_same_file else None)

    second = store.enroll(variant, "enable")
    assert second.created is not paths_refer_to_same_file
    assert len(store.read_strict().projects) == (1 if paths_refer_to_same_file else 2)


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
    path.write_text(
        json.dumps({"schema_version": PROJECT_REGISTRY_VERSION + 1, "projects": []}),
        encoding="utf-8",
    )
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
