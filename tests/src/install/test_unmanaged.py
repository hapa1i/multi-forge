"""Unmanaged runtime skill package detection and cleanup-proof tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from forge.install.exceptions import TrackingCorruptedError
from forge.install.models import Installation, InstalledManifest, InstalledSkillPackage
from forge.install.skill_compiler import FORGE_PACKAGE_SENTINEL
from forge.install.tracking import TrackingStore
from forge.install.unmanaged import (
    SkillScanRoot,
    canonical_package_path,
    revalidate_cleanup_candidate,
    scan_unmanaged_skill_packages,
    scan_unmanaged_skill_state,
)

CURRENT_SKILLS = {"understand"}
SENTINEL_FIELDS = {
    "schema_version",
    "producer",
    "runtime",
    "skill",
    "files",
}
RECORD_FIELDS = {
    "runtime",
    "skill",
    "target_dir",
    "target_scopes",
    "root_kind",
    "shape",
    "provenance",
    "collision_dirs",
    "cleanup_eligible",
    "cleanup_reason",
    "cleanup_scope",
    "recovery",
}


def _root(
    path: Path,
    *,
    runtime: str = "codex",
    scopes: tuple[str, ...] = ("user",),
    root_kind: str = "forge-writable",
    cleanup_scope: str | None = "all",
    project_root: Path | None = None,
    report_entries: bool = True,
) -> SkillScanRoot:
    return SkillScanRoot(
        runtime=runtime,
        path=path,
        target_scopes=scopes,
        root_kind=root_kind,  # type: ignore[arg-type]
        cleanup_scope=cleanup_scope,  # type: ignore[arg-type]
        project_root=project_root,
        report_entries=report_entries,
    )


def _payload_row(path: str, content: bytes, mode: int = 0o644) -> dict[str, object]:
    return {
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "mode": mode,
    }


def _write_marker(
    package: Path,
    *,
    runtime: str = "codex",
    skill: str | None = None,
    rows: list[dict[str, object]] | None = None,
    schema_version: int = 1,
    extra: dict[str, object] | None = None,
) -> Path:
    payload: dict[str, object] = {
        "schema_version": schema_version,
        "producer": "multi-forge",
        "runtime": runtime,
        "skill": skill or package.name,
        "files": rows or [],
    }
    if extra:
        payload.update(extra)
    marker = package / FORGE_PACKAGE_SENTINEL
    marker.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return marker


def _write_copy_package(
    root: Path,
    skill: str = "understand",
    *,
    runtime: str = "codex",
    content: bytes = b"---\nname: understand\n---\n",
) -> Path:
    package = root / skill
    package.mkdir(parents=True)
    payload = package / "SKILL.md"
    payload.write_bytes(content)
    payload.chmod(0o644)
    _write_marker(package, runtime=runtime, rows=[_payload_row("SKILL.md", content)])
    return package


def _scan(
    roots: tuple[SkillScanRoot, ...],
    *,
    forge_home: Path,
    tracking: InstalledManifest | None = None,
) -> tuple:
    return scan_unmanaged_skill_packages(
        roots,
        current_skill_names=CURRENT_SKILLS,
        tracking=tracking or InstalledManifest(),
        forge_home=forge_home,
    )


def test_reports_historical_name_and_ignores_unknown_unmarked_directory(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    historical = skill_root / "walkthrough"
    historical.mkdir(parents=True)
    (historical / "SKILL.md").write_text("historical\n", encoding="utf-8")
    unknown = skill_root / "operator-owned"
    unknown.mkdir()
    (unknown / "SKILL.md").write_text("user\n", encoding="utf-8")

    records = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert [(record.skill, record.provenance) for record in records] == [("walkthrough", "unmarked")]
    assert records[0].shape == "complete"
    assert records[0].cleanup_eligible is False
    assert "Remove or rename" in (records[0].recovery or "")


def test_reports_unknown_name_when_real_directory_has_sentinel(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    package = _write_copy_package(skill_root, "retired-name")

    records = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert len(records) == 1
    assert records[0].target_dir == str(package)
    assert records[0].provenance == "marked"


def test_marked_copy_package_is_cleanup_eligible_with_fixed_record_shape(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    package = _write_copy_package(skill_root)

    (record,) = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert set(record.to_dict()) == RECORD_FIELDS
    assert record.target_dir == str(package)
    assert record.shape == "complete"
    assert record.provenance == "marked"
    assert record.cleanup_eligible is True
    assert record.cleanup_scope == "all"
    assert "forge clean --scope all --verbose" in (record.recovery or "")
    assert "--yes" in (record.recovery or "")


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("edit", "digest mismatch"),
        ("extra-file", "unlisted operator.txt"),
        ("extra-directory", "unlisted directories operator"),
        ("mode", "mode mismatch"),
    ],
)
def test_modified_marked_package_is_report_only(tmp_path: Path, mutation: str, reason: str) -> None:
    skill_root = tmp_path / "skills"
    package = _write_copy_package(skill_root)
    if mutation == "edit":
        (package / "SKILL.md").write_text("changed\n", encoding="utf-8")
    elif mutation == "extra-file":
        (package / "operator.txt").write_text("keep\n", encoding="utf-8")
    elif mutation == "extra-directory":
        (package / "operator").mkdir()
    else:
        (package / "SKILL.md").chmod(0o600)

    (record,) = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert record.provenance == "modified"
    assert record.cleanup_eligible is False
    assert reason in record.cleanup_reason
    assert "Remove or rename" in (record.recovery or "")


@pytest.mark.parametrize(
    ("payload", "provenance", "reason"),
    [
        ("not json", "invalid-marker", "invalid Forge provenance sentinel"),
        ({"schema_version": 2}, "unsupported-marker", "unsupported Forge provenance sentinel schema 2"),
        ({"unexpected": True}, "invalid-marker", "fields"),
    ],
)
def test_strict_marker_failures_are_report_only(
    tmp_path: Path,
    payload: object,
    provenance: str,
    reason: str,
) -> None:
    skill_root = tmp_path / "skills"
    package = _write_copy_package(skill_root)
    marker = package / FORGE_PACKAGE_SENTINEL
    if isinstance(payload, str):
        marker.write_text(payload, encoding="utf-8")
    else:
        current = json.loads(marker.read_text(encoding="utf-8"))
        current.update(payload)
        marker.write_text(json.dumps(current), encoding="utf-8")

    (record,) = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert record.provenance == provenance
    assert record.cleanup_eligible is False
    assert reason in record.cleanup_reason


@pytest.mark.parametrize("marker_kind", ["directory", "symlink", "fifo"])
def test_non_regular_marker_is_an_invalid_target(tmp_path: Path, marker_kind: str) -> None:
    skill_root = tmp_path / "skills"
    package = _write_copy_package(skill_root)
    marker = package / FORGE_PACKAGE_SENTINEL
    marker.unlink()
    if marker_kind == "directory":
        marker.mkdir()
    elif marker_kind == "symlink":
        external = tmp_path / "marker.json"
        external.write_text("{}\n", encoding="utf-8")
        marker.symlink_to(external)
    else:
        os.mkfifo(marker)

    (record,) = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert record.shape == "invalid-target"
    assert record.provenance == "invalid-marker"
    assert record.cleanup_eligible is False
    assert "not a regular file" in record.cleanup_reason


def test_symlink_in_manifest_directory_position_is_an_invalid_target(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    package = skill_root / "understand"
    resources = package / "resources"
    resources.mkdir(parents=True)
    skill_content = b"skill\n"
    resource_content = b"resource\n"
    (package / "SKILL.md").write_bytes(skill_content)
    (package / "SKILL.md").chmod(0o644)
    (resources / "guide.md").write_bytes(resource_content)
    _write_marker(
        package,
        rows=[
            _payload_row("SKILL.md", skill_content),
            _payload_row("resources/guide.md", resource_content),
        ],
    )
    external = tmp_path / "operator-resources"
    external.mkdir()
    (external / "guide.md").write_bytes(resource_content)
    for child in resources.iterdir():
        child.unlink()
    resources.rmdir()
    resources.symlink_to(external, target_is_directory=True)

    (record,) = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert record.shape == "invalid-target"
    assert record.provenance == "modified"
    assert record.cleanup_eligible is False
    assert "symlink" in record.cleanup_reason


@pytest.mark.parametrize("entry_kind", ["file", "symlink", "fifo"])
def test_known_name_unsafe_entry_is_visible_but_never_cleanable(tmp_path: Path, entry_kind: str) -> None:
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    entry = skill_root / "understand"
    if entry_kind == "file":
        entry.write_text("blocker\n", encoding="utf-8")
    elif entry_kind == "symlink":
        target = tmp_path / "elsewhere"
        target.mkdir()
        entry.symlink_to(target, target_is_directory=True)
    else:
        os.mkfifo(entry)

    (record,) = _scan((_root(skill_root),), forge_home=tmp_path / "forge")

    assert record.shape == "invalid-target"
    assert record.cleanup_eligible is False
    assert "not a real directory" in record.cleanup_reason


def test_symlinked_scan_root_is_not_traversed(tmp_path: Path) -> None:
    real_root = tmp_path / "real"
    _write_copy_package(real_root)
    linked_root = tmp_path / "skills"
    linked_root.symlink_to(real_root, target_is_directory=True)

    scan = scan_unmanaged_skill_state(
        (_root(linked_root),),
        current_skill_names=CURRENT_SKILLS,
        tracking=InstalledManifest(),
        forge_home=tmp_path / "forge",
    )

    assert scan.packages == ()
    assert len(scan.root_issues) == 1
    assert scan.root_issues[0].runtime == "codex"
    assert scan.root_issues[0].root_dir == str(linked_root)
    assert scan.root_issues[0].reason == "is not a real directory"


def test_managed_exact_canonical_target_is_omitted(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    skill_root = real_parent / "skills"
    package = _write_copy_package(skill_root)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    claimed = linked_parent / "skills" / "understand"
    manifest = InstalledManifest(
        installations={
            "user": Installation(
                scope="user",
                mode="copy",
                profile="standard",
                skill_packages=[
                    InstalledSkillPackage(
                        runtime="codex",
                        skill="understand",
                        target_dir=str(claimed),
                        file_paths=[str(claimed / "SKILL.md")],
                    )
                ],
            )
        }
    )

    records = _scan((_root(skill_root),), forge_home=tmp_path / "forge", tracking=manifest)

    assert canonical_package_path(claimed) == package
    assert records == ()


def test_physical_root_merges_scopes_and_collision_evidence_is_separate(tmp_path: Path) -> None:
    writable = tmp_path / "project" / ".agents" / "skills"
    collision = tmp_path / "ancestor" / ".agents" / "skills"
    _write_copy_package(writable)
    duplicate = collision / "understand"
    duplicate.mkdir(parents=True)
    (duplicate / "SKILL.md").write_text("duplicate\n", encoding="utf-8")

    records = _scan(
        (
            _root(
                writable,
                scopes=("project",),
                cleanup_scope="project",
                project_root=tmp_path / "project",
            ),
            _root(
                writable,
                scopes=("local",),
                cleanup_scope="project",
                project_root=tmp_path / "project",
            ),
            _root(
                collision,
                scopes=(),
                root_kind="visibility-only",
                cleanup_scope=None,
                report_entries=False,
            ),
        ),
        forge_home=tmp_path / "forge",
    )

    assert len(records) == 1
    assert records[0].target_scopes == ("local", "project")
    assert records[0].collision_dirs == (str(duplicate),)
    assert records[0].cleanup_eligible is True
    assert records[0].cleanup_scope == "project"


def test_visibility_only_marked_package_is_never_cleanup_eligible(tmp_path: Path) -> None:
    skill_root = tmp_path / "admin"
    _write_copy_package(skill_root)

    (record,) = _scan(
        (_root(skill_root, scopes=(), root_kind="visibility-only", cleanup_scope=None),),
        forge_home=tmp_path / "forge",
    )

    assert record.root_kind == "visibility-only"
    assert record.provenance == "marked"
    assert record.cleanup_eligible is False
    assert record.cleanup_scope is None


def test_partial_visibility_entry_still_contributes_collision_evidence(tmp_path: Path) -> None:
    writable = tmp_path / "project" / ".agents" / "skills"
    visibility = tmp_path / "ancestor" / ".agents" / "skills"
    _write_copy_package(writable)
    partial = visibility / "understand"
    partial.mkdir(parents=True)

    (record,) = _scan(
        (
            _root(writable, scopes=("project",), cleanup_scope="project", project_root=tmp_path / "project"),
            _root(
                visibility,
                scopes=(),
                root_kind="visibility-only",
                cleanup_scope=None,
                report_entries=False,
            ),
        ),
        forge_home=tmp_path / "forge",
    )

    assert record.collision_dirs == (str(partial),)


def test_live_cache_symlink_package_is_cleanup_eligible(tmp_path: Path) -> None:
    forge_home = tmp_path / "forge"
    content = b"cache payload\n"
    digest = "a" * 64
    cache_package = forge_home / "cache" / "compiled-skills" / "v1" / "codex" / "understand" / digest
    cache_package.mkdir(parents=True)
    cached_payload = cache_package / "SKILL.md"
    cached_payload.write_bytes(content)
    cached_payload.chmod(0o644)
    package = tmp_path / "skills" / "understand"
    package.mkdir(parents=True)
    (package / "SKILL.md").symlink_to(cached_payload)
    _write_marker(package, rows=[_payload_row("SKILL.md", content)])

    (record,) = _scan((_root(package.parent),), forge_home=forge_home)

    assert record.provenance == "marked"
    assert record.shape == "complete"
    assert record.cleanup_eligible is True


def test_live_cache_link_that_resolves_outside_cache_is_report_only(tmp_path: Path) -> None:
    forge_home = tmp_path / "forge"
    content = b"operator payload\n"
    digest = "e" * 64
    external = tmp_path / "operator"
    external.mkdir()
    (external / "SKILL.md").write_bytes(content)
    (external / "SKILL.md").chmod(0o644)
    cache_skill = forge_home / "cache" / "compiled-skills" / "v1" / "codex" / "understand"
    cache_skill.mkdir(parents=True)
    (cache_skill / digest).symlink_to(external, target_is_directory=True)
    package = tmp_path / "skills" / "understand"
    package.mkdir(parents=True)
    (package / "SKILL.md").symlink_to(cache_skill / digest / "SKILL.md")
    _write_marker(package, rows=[_payload_row("SKILL.md", content)])

    (record,) = _scan((_root(package.parent),), forge_home=forge_home)

    assert record.provenance == "modified"
    assert record.cleanup_eligible is False
    assert "resolves outside" in record.cleanup_reason


def test_cache_reset_dangling_links_are_partial_but_cleanup_eligible(tmp_path: Path) -> None:
    forge_home = tmp_path / "forge"
    digest = "b" * 64
    cache_package = forge_home / "cache" / "compiled-skills" / "v1" / "codex" / "understand" / digest
    package = tmp_path / "skills" / "understand"
    (package / "resources").mkdir(parents=True)
    skill_content = b"skill\n"
    resource_content = b"resource\n"
    (package / "SKILL.md").symlink_to(cache_package / "SKILL.md")
    (package / "resources" / "guide.md").symlink_to(cache_package / "resources" / "guide.md")
    _write_marker(
        package,
        rows=[
            _payload_row("SKILL.md", skill_content),
            _payload_row("resources/guide.md", resource_content),
        ],
    )

    (record,) = _scan((_root(package.parent),), forge_home=forge_home)

    assert record.provenance == "marked"
    assert record.shape == "partial"
    assert record.cleanup_eligible is True


@pytest.mark.parametrize("failure", ["external", "mixed-cache-roots"])
def test_unproven_symlink_package_is_report_only(tmp_path: Path, failure: str) -> None:
    forge_home = tmp_path / "forge"
    package = tmp_path / "skills" / "understand"
    package.mkdir(parents=True)
    content = b"skill\n"
    if failure == "external":
        target = tmp_path / "operator" / "SKILL.md"
    else:
        target = forge_home / "cache" / "compiled-skills" / "v1" / "codex" / "understand" / ("c" * 64) / "SKILL.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    target.chmod(0o644)
    (package / "SKILL.md").symlink_to(target)
    rows = [_payload_row("SKILL.md", content)]
    if failure == "mixed-cache-roots":
        second = forge_home / "cache" / "compiled-skills" / "v1" / "codex" / "understand" / ("d" * 64)
        (package / "extra.md").symlink_to(second / "extra.md")
        rows.append(_payload_row("extra.md", b"extra\n"))
    _write_marker(package, rows=rows)

    (record,) = _scan((_root(package.parent),), forge_home=forge_home)

    assert record.cleanup_eligible is False
    assert record.provenance == "modified"
    assert "outside" in record.cleanup_reason or "one compiled Forge package" in record.cleanup_reason


def test_revalidation_rejects_content_drift(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    package = _write_copy_package(skill_root)
    root = _root(skill_root)
    (record,) = _scan((root,), forge_home=tmp_path / "forge")
    (package / "SKILL.md").write_text("drift\n", encoding="utf-8")

    result = revalidate_cleanup_candidate(
        record,
        root,
        current_skill_names=CURRENT_SKILLS,
        tracking=InstalledManifest(),
        forge_home=tmp_path / "forge",
    )

    assert result is None


def test_tracking_store_is_read_once_and_corruption_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_root = tmp_path / "skills"
    _write_copy_package(skill_root)
    tracking_path = tmp_path / "installed.json"
    tracking_path.write_text("not json", encoding="utf-8")
    store = TrackingStore(tracking_path)
    calls = 0
    original_read = store.read

    def counted_read() -> InstalledManifest:
        nonlocal calls
        calls += 1
        return original_read()

    monkeypatch.setattr(store, "read", counted_read)

    with pytest.raises(TrackingCorruptedError):
        scan_unmanaged_skill_packages(
            (_root(skill_root),),
            current_skill_names=CURRENT_SKILLS,
            tracking_store=store,
            forge_home=tmp_path / "forge",
        )
    assert calls == 1


def test_scanner_rejects_two_tracking_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        scan_unmanaged_skill_packages(
            (),
            current_skill_names=CURRENT_SKILLS,
            tracking=InstalledManifest(),
            tracking_store=TrackingStore(tmp_path / "installed.json"),
            forge_home=tmp_path / "forge",
        )


def test_sentinel_fixture_uses_the_strict_document_shape(tmp_path: Path) -> None:
    package = _write_copy_package(tmp_path / "skills")
    payload = json.loads((package / FORGE_PACKAGE_SENTINEL).read_text(encoding="utf-8"))

    assert set(payload) == SENTINEL_FIELDS
