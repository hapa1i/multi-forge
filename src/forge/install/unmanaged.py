"""Read-only detection and proof for unmanaged runtime skill packages.

Runtime skill directories are live discovery surfaces.  This module compares
their direct children with validated installer tracking and classifies entries
without adopting, repairing, or deleting them.  Cleanup callers may consume
only records whose full Forge provenance proof succeeds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Literal

from forge.core.paths import find_git_root, get_forge_home

from .models import InstalledManifest, InstallScope
from .skill_compiler import (
    FORGE_PACKAGE_PRODUCER,
    FORGE_PACKAGE_SCHEMA_VERSION,
    FORGE_PACKAGE_SENTINEL,
)
from .skill_planning import (
    CLAUDE_CODE_RUNTIME,
    CODEX_RUNTIME,
    forge_skill_name_universe,
    runtime_skill_root,
)
from .tracking import TrackingStore

RootKind = Literal["forge-writable", "visibility-only"]
PackageShape = Literal["complete", "partial", "invalid-target"]
PackageProvenance = Literal[
    "marked",
    "unmarked",
    "invalid-marker",
    "unsupported-marker",
    "modified",
]
CleanupScope = Literal["project", "all"]

_MARKER_KEYS = {"schema_version", "producer", "runtime", "skill", "files"}
_MARKER_FILE_KEYS = {"path", "sha256", "mode"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SkillScanRoot:
    """One runtime-visible skill root and Forge's authority over it."""

    runtime: str
    path: Path
    target_scopes: tuple[str, ...] = ()
    root_kind: RootKind = "forge-writable"
    cleanup_scope: CleanupScope | None = None
    project_root: Path | None = None
    report_entries: bool = True


@dataclass(frozen=True)
class UnmanagedSkillPackage:
    """One direct runtime-target entry not claimed by coherent tracking."""

    runtime: str
    skill: str
    target_dir: str
    target_scopes: tuple[str, ...]
    root_kind: RootKind
    shape: PackageShape
    provenance: PackageProvenance
    collision_dirs: tuple[str, ...]
    cleanup_eligible: bool
    cleanup_reason: str
    cleanup_scope: CleanupScope | None
    recovery: str | None

    def to_dict(self) -> dict[str, object]:
        """Return the fixed status-JSON record shape."""

        return {
            "runtime": self.runtime,
            "skill": self.skill,
            "target_dir": self.target_dir,
            "target_scopes": list(self.target_scopes),
            "root_kind": self.root_kind,
            "shape": self.shape,
            "provenance": self.provenance,
            "collision_dirs": list(self.collision_dirs),
            "cleanup_eligible": self.cleanup_eligible,
            "cleanup_reason": self.cleanup_reason,
            "cleanup_scope": self.cleanup_scope,
            "recovery": self.recovery,
        }


@dataclass(frozen=True)
class RuntimeSkillRootIssue:
    """One selected runtime root that could not be scanned safely."""

    runtime: str
    root_dir: str
    reason: str


@dataclass(frozen=True)
class UnmanagedSkillScan:
    """Package observations plus human-facing root scan failures."""

    packages: tuple[UnmanagedSkillPackage, ...]
    root_issues: tuple[RuntimeSkillRootIssue, ...]


@dataclass(frozen=True)
class _MarkerFile:
    path: PurePosixPath
    sha256: str
    mode: int


@dataclass(frozen=True)
class _Marker:
    runtime: str
    skill: str
    files: tuple[_MarkerFile, ...]


class _InvalidMarker(ValueError):
    pass


class _UnsupportedMarker(ValueError):
    pass


@dataclass(frozen=True)
class _TreeProof:
    eligible: bool
    reason: str
    shape: PackageShape


def canonical_package_path(path: Path) -> Path:
    """Resolve parent components while preserving the final path entry."""

    absolute = Path(os.path.abspath(path.expanduser()))
    return absolute.parent.resolve() / absolute.name


def scan_unmanaged_skill_packages(
    roots: Iterable[SkillScanRoot],
    *,
    current_skill_names: Iterable[str],
    tracking: InstalledManifest | None = None,
    tracking_store: TrackingStore | None = None,
    forge_home: Path | None = None,
) -> tuple[UnmanagedSkillPackage, ...]:
    """Return untracked package records from selected runtime skill roots."""

    return scan_unmanaged_skill_state(
        roots,
        current_skill_names=current_skill_names,
        tracking=tracking,
        tracking_store=tracking_store,
        forge_home=forge_home,
    ).packages


def scan_unmanaged_skill_state(
    roots: Iterable[SkillScanRoot],
    *,
    current_skill_names: Iterable[str],
    tracking: InstalledManifest | None = None,
    tracking_store: TrackingStore | None = None,
    forge_home: Path | None = None,
) -> UnmanagedSkillScan:
    """Classify untracked packages and unsafe selected runtime roots.

    Passing ``tracking`` supplies a pre-validated snapshot shared with a
    caller's own plan/rendering.  Otherwise this operation owns exactly one
    ``TrackingStore.read``.  Missing tracking is an empty manifest; corrupt,
    unsupported, or unreadable tracking propagates from that existing reader.
    """

    if tracking is not None and tracking_store is not None:
        raise ValueError("tracking and tracking_store are mutually exclusive")
    manifest = tracking if tracking is not None else (tracking_store or TrackingStore()).read()
    managed_paths = _managed_package_paths(manifest)
    universe = forge_skill_name_universe(current_skill_names)
    normalized_roots = _merge_roots(roots)
    cache_namespace = canonical_package_path((forge_home or get_forge_home()) / "cache" / "compiled-skills" / "v1")

    observed_by_root: dict[tuple[str, Path], dict[str, Path]] = {}
    root_is_safe: dict[tuple[str, Path], bool] = {}
    root_issues: list[RuntimeSkillRootIssue] = []
    for root in normalized_roots:
        key = (root.runtime, root.path)
        entries, issue_reason = _observed_entries(root.path, universe)
        observed_by_root[key] = entries
        root_is_safe[key] = issue_reason is None
        if issue_reason is not None and root.report_entries:
            root_issues.append(
                RuntimeSkillRootIssue(
                    runtime=root.runtime,
                    root_dir=str(root.path),
                    reason=issue_reason,
                )
            )

    collisions = _collision_index(normalized_roots, observed_by_root, root_is_safe)
    records: list[UnmanagedSkillPackage] = []
    for root in normalized_roots:
        if not root.report_entries:
            continue
        key = (root.runtime, root.path)
        if not root_is_safe[key]:
            # A symlinked/non-directory target root cannot be traversed safely,
            # so no per-package observation can be made without violating the
            # lstat-first boundary.
            continue
        for skill, package_path in observed_by_root[key].items():
            canonical_target = canonical_package_path(package_path)
            if canonical_target in managed_paths:
                continue
            collision_dirs = tuple(
                str(path)
                for path in sorted(
                    (path for path in collisions.get((root.runtime, skill), ()) if path != canonical_target),
                    key=str,
                )
            )
            records.append(
                _classify_unmanaged_entry(
                    root,
                    package_path=canonical_target,
                    collision_dirs=collision_dirs,
                    cache_namespace=cache_namespace,
                )
            )
    return UnmanagedSkillScan(
        packages=tuple(sorted(records, key=lambda item: (item.runtime, item.skill, item.target_dir))),
        root_issues=tuple(root_issues),
    )


def revalidate_cleanup_candidate(
    record: UnmanagedSkillPackage,
    root: SkillScanRoot,
    *,
    current_skill_names: Iterable[str],
    tracking: InstalledManifest | None = None,
    tracking_store: TrackingStore | None = None,
    forge_home: Path | None = None,
) -> UnmanagedSkillPackage | None:
    """Freshly rescan one root and return its still-identical safe candidate."""

    rescanned = scan_unmanaged_skill_packages(
        (root,),
        current_skill_names=current_skill_names,
        tracking=tracking,
        tracking_store=tracking_store,
        forge_home=forge_home,
    )
    expected = canonical_package_path(Path(record.target_dir))
    return next(
        (
            candidate
            for candidate in rescanned
            if canonical_package_path(Path(candidate.target_dir)) == expected and candidate.cleanup_eligible
        ),
        None,
    )


def cleanup_proof_fingerprint(package_path: Path) -> str | None:
    """Snapshot one package tree without following any symlinked entry.

    The structured unmanaged record intentionally exposes only the stable
    12-field status contract.  Cleanup keeps this separate, private proof so
    it can reject a coherently re-marked replacement that would otherwise
    still classify as eligible during the pre-delete rescan.
    """

    package_path = canonical_package_path(package_path)
    digest = hashlib.sha256()

    def metadata(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_nlink,
            info.st_uid,
            info.st_gid,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def add_row(*values: object) -> None:
        digest.update(json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")

    def walk(directory: Path, relative: PurePosixPath) -> bool:
        try:
            before = directory.lstat()
        except OSError:
            return False
        if not stat.S_ISDIR(before.st_mode):
            return False
        add_row("directory", relative.as_posix(), *metadata(before))
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError:
            return False

        for entry in entries:
            child = directory / entry.name
            child_relative = relative / entry.name
            try:
                first = entry.stat(follow_symlinks=False)
            except OSError:
                return False
            if stat.S_ISDIR(first.st_mode):
                if not walk(child, child_relative):
                    return False
                continue
            if stat.S_ISREG(first.st_mode):
                try:
                    content_digest = hashlib.sha256(child.read_bytes()).hexdigest()
                    second = child.lstat()
                except OSError:
                    return False
                if metadata(first) != metadata(second) or not stat.S_ISREG(second.st_mode):
                    return False
                add_row("file", child_relative.as_posix(), *metadata(first), content_digest)
                continue
            if stat.S_ISLNK(first.st_mode):
                try:
                    raw_target = os.readlink(child)
                    second = child.lstat()
                except OSError:
                    return False
                if metadata(first) != metadata(second) or not stat.S_ISLNK(second.st_mode):
                    return False
                add_row("symlink", child_relative.as_posix(), *metadata(first), raw_target)
                continue
            return False

        try:
            after = directory.lstat()
        except OSError:
            return False
        return metadata(before) == metadata(after) and stat.S_ISDIR(after.st_mode)

    return digest.hexdigest() if walk(package_path, PurePosixPath()) else None


def codex_skill_visibility_roots(
    project_root: Path | None,
    *,
    user_home: Path | None = None,
    include_cwd: bool = True,
    admin_root: Path = Path("/etc/codex/skills"),
) -> tuple[Path, ...]:
    """Return Codex's user, applicable ancestor-project, and admin roots."""

    roots: list[Path] = [(user_home or Path.home()) / ".agents" / "skills"]
    anchors = [anchor for anchor in (project_root, Path.cwd() if include_cwd else None) if anchor is not None]
    for anchor in anchors:
        resolved = anchor.resolve()
        git_root = find_git_root(resolved)
        stop = git_root or resolved
        current = resolved
        while True:
            roots.append(current / ".agents" / "skills")
            if current == stop or current == current.parent:
                break
            current = current.parent
    roots.append(admin_root)
    return tuple(dict.fromkeys(canonical_package_path(root) for root in roots))


def runtime_skill_scan_roots(
    scope_roots: Iterable[tuple[InstallScope, Path | None]],
    *,
    user_home: Path,
    claude_home: Path,
    additional_codex_visibility_roots: Iterable[Path] = (),
    report_visibility_entries: bool = False,
) -> tuple[SkillScanRoot, ...]:
    """Build writable and Codex visibility roots for status, planning, or GC."""

    roots: list[SkillScanRoot] = []
    codex_contexts: list[Path | None] = []
    for scope, project_root in scope_roots:
        cleanup_scope: CleanupScope = "all" if scope == InstallScope.USER else "project"
        roots.append(
            SkillScanRoot(
                runtime=CLAUDE_CODE_RUNTIME,
                path=runtime_skill_root(
                    CLAUDE_CODE_RUNTIME,
                    scope,
                    user_home=user_home,
                    claude_home=claude_home,
                    project_root=project_root,
                ),
                target_scopes=(scope.value,),
                cleanup_scope=cleanup_scope,
                project_root=project_root,
            )
        )
        if scope not in {InstallScope.USER, InstallScope.PROJECT}:
            continue
        roots.append(
            SkillScanRoot(
                runtime=CODEX_RUNTIME,
                path=runtime_skill_root(
                    CODEX_RUNTIME,
                    scope,
                    user_home=user_home,
                    claude_home=claude_home,
                    project_root=project_root,
                ),
                target_scopes=(scope.value,),
                cleanup_scope=cleanup_scope,
                project_root=project_root,
            )
        )
        codex_contexts.append(project_root)

    visibility_paths: set[Path] = set(additional_codex_visibility_roots)
    for project_root in codex_contexts:
        visibility_paths.update(
            codex_skill_visibility_roots(
                project_root,
                user_home=user_home,
                include_cwd=project_root is None,
            )
        )
    roots.extend(
        SkillScanRoot(
            runtime=CODEX_RUNTIME,
            path=path,
            root_kind="visibility-only",
            report_entries=report_visibility_entries,
        )
        for path in visibility_paths
    )
    return _merge_roots(roots)


def _managed_package_paths(manifest: InstalledManifest) -> frozenset[Path]:
    return frozenset(
        canonical_package_path(Path(package.target_dir))
        for installation in manifest.installations.values()
        for package in installation.skill_packages
    )


def _merge_roots(roots: Iterable[SkillScanRoot]) -> tuple[SkillScanRoot, ...]:
    merged: dict[tuple[str, Path], SkillScanRoot] = {}
    for raw_root in roots:
        path = canonical_package_path(raw_root.path)
        normalized = replace(
            raw_root,
            path=path,
            target_scopes=tuple(sorted(set(raw_root.target_scopes))),
            project_root=raw_root.project_root.resolve() if raw_root.project_root is not None else None,
        )
        key = (normalized.runtime, path)
        existing = merged.get(key)
        if existing is None:
            merged[key] = normalized
            continue
        cleanup_scopes: set[CleanupScope] = {
            scope for scope in (existing.cleanup_scope, normalized.cleanup_scope) if scope is not None
        }
        if len(cleanup_scopes) > 1:
            raise ValueError(f"Conflicting cleanup scopes for runtime skill root {path}")
        project_roots = {root for root in (existing.project_root, normalized.project_root) if root is not None}
        if len(project_roots) > 1:
            raise ValueError(f"Conflicting project owners for runtime skill root {path}")
        merged[key] = SkillScanRoot(
            runtime=normalized.runtime,
            path=path,
            target_scopes=tuple(sorted(set(existing.target_scopes) | set(normalized.target_scopes))),
            root_kind=(
                "forge-writable"
                if "forge-writable" in {existing.root_kind, normalized.root_kind}
                else "visibility-only"
            ),
            cleanup_scope=next(iter(cleanup_scopes), None),
            project_root=next(iter(project_roots), None),
            report_entries=existing.report_entries or normalized.report_entries,
        )
    return tuple(sorted(merged.values(), key=lambda item: (item.runtime, str(item.path))))


def _observed_entries(root: Path, universe: frozenset[str]) -> tuple[dict[str, Path], str | None]:
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        return {}, None
    except OSError as exc:
        return {}, f"could not be inspected: {exc.strerror or exc}"
    if not stat.S_ISDIR(root_mode):
        return {}, "is not a real directory"

    observed: dict[str, Path] = {}
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                package_path = root / entry.name
                try:
                    entry_mode = entry.stat(follow_symlinks=False).st_mode
                except (FileNotFoundError, OSError):
                    if entry.name in universe:
                        observed[entry.name] = package_path
                    continue
                marker_present = stat.S_ISDIR(entry_mode) and _lexists(package_path / FORGE_PACKAGE_SENTINEL)
                if entry.name in universe or marker_present:
                    observed[entry.name] = package_path
    except OSError as exc:
        return {}, f"could not be scanned: {exc.strerror or exc}"
    return dict(sorted(observed.items())), None


def _collision_index(
    roots: tuple[SkillScanRoot, ...],
    observed_by_root: dict[tuple[str, Path], dict[str, Path]],
    root_is_safe: dict[tuple[str, Path], bool],
) -> dict[tuple[str, str], tuple[Path, ...]]:
    collisions: dict[tuple[str, str], set[Path]] = {}
    for root in roots:
        key = (root.runtime, root.path)
        if not root_is_safe[key]:
            continue
        for skill, package_path in observed_by_root[key].items():
            collisions.setdefault((root.runtime, skill), set()).add(canonical_package_path(package_path))
    return {key: tuple(sorted(paths, key=str)) for key, paths in collisions.items()}


def _classify_unmanaged_entry(
    root: SkillScanRoot,
    *,
    package_path: Path,
    collision_dirs: tuple[str, ...],
    cache_namespace: Path,
) -> UnmanagedSkillPackage:
    try:
        package_mode = package_path.lstat().st_mode
    except OSError as exc:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape="invalid-target",
            provenance="unmarked",
            cleanup_reason=f"package entry could not be inspected: {exc}",
        )
    if not stat.S_ISDIR(package_mode):
        return _record(
            root,
            package_path,
            collision_dirs,
            shape="invalid-target",
            provenance="unmarked",
            cleanup_reason="package entry is not a real directory",
        )

    shape: PackageShape = "complete" if _is_usable_package(package_path) else "partial"
    marker_path = package_path / FORGE_PACKAGE_SENTINEL
    try:
        marker_mode = marker_path.lstat().st_mode
    except FileNotFoundError:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape=shape,
            provenance="unmarked",
            cleanup_reason="package has no Forge provenance sentinel",
        )
    except OSError as exc:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape=shape,
            provenance="invalid-marker",
            cleanup_reason=f"Forge provenance sentinel could not be inspected: {exc}",
        )
    if not stat.S_ISREG(marker_mode):
        return _record(
            root,
            package_path,
            collision_dirs,
            shape="invalid-target",
            provenance="invalid-marker",
            cleanup_reason="Forge provenance sentinel is not a regular file",
        )

    try:
        marker = _read_marker(marker_path, expected_runtime=root.runtime, expected_skill=package_path.name)
    except _UnsupportedMarker as exc:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape=shape,
            provenance="unsupported-marker",
            cleanup_reason=str(exc),
        )
    except _InvalidMarker as exc:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape=shape,
            provenance="invalid-marker",
            cleanup_reason=str(exc),
        )

    proof = _prove_package_tree(package_path, marker, cache_namespace=cache_namespace)
    if not proof.eligible:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape=proof.shape,
            provenance="modified",
            cleanup_reason=proof.reason,
        )
    if root.root_kind != "forge-writable" or root.cleanup_scope is None:
        return _record(
            root,
            package_path,
            collision_dirs,
            shape=proof.shape,
            provenance="marked",
            cleanup_reason="package is visible but its runtime root is not Forge-writable",
        )

    recovery = _cleanup_recovery(root, package_path)
    return UnmanagedSkillPackage(
        runtime=root.runtime,
        skill=package_path.name,
        target_dir=str(package_path),
        target_scopes=root.target_scopes,
        root_kind=root.root_kind,
        shape=proof.shape,
        provenance="marked",
        collision_dirs=collision_dirs,
        cleanup_eligible=True,
        cleanup_reason="sentinel, package contents, paths, and absent tracking were verified",
        cleanup_scope=root.cleanup_scope,
        recovery=recovery,
    )


def _record(
    root: SkillScanRoot,
    package_path: Path,
    collision_dirs: tuple[str, ...],
    *,
    shape: PackageShape,
    provenance: PackageProvenance,
    cleanup_reason: str,
) -> UnmanagedSkillPackage:
    return UnmanagedSkillPackage(
        runtime=root.runtime,
        skill=package_path.name,
        target_dir=str(package_path),
        target_scopes=root.target_scopes,
        root_kind=root.root_kind,
        shape=shape,
        provenance=provenance,
        collision_dirs=collision_dirs,
        cleanup_eligible=False,
        cleanup_reason=cleanup_reason,
        cleanup_scope=None,
        recovery=f"Remove or rename {package_path} before retrying; Forge cannot prove it is safe to clean.",
    )


def _cleanup_recovery(root: SkillScanRoot, package_path: Path) -> str:
    if root.cleanup_scope == "all":
        preview = "forge clean --scope all --verbose"
    else:
        project_root = root.project_root or root.path.parent.parent
        preview = f"cd {shlex.quote(str(project_root))} && forge clean --scope project --verbose"
    return (
        f"{package_path} is verified untracked Forge output. Preview with `{preview}`, "
        f"apply with `{preview} --yes`, then retry the extension command."
    )


def render_unmanaged_conflict_recovery(
    duplicate_dirs: Iterable[Path],
    records_by_path: Mapping[Path, UnmanagedSkillPackage],
    *,
    operation: str,
    project_root: Path | None,
) -> str | None:
    """Render per-path installer recovery without weakening duplicate safety."""

    steps: list[str] = []
    for raw_path in duplicate_dirs:
        path = canonical_package_path(raw_path)
        record = records_by_path.get(path)
        if record is None:
            continue
        if record.cleanup_eligible and record.cleanup_scope == "all":
            preview = "forge clean --scope all --verbose"
        elif record.cleanup_eligible and record.cleanup_scope == "project" and project_root is not None:
            preview = f"cd {shlex.quote(str(project_root))} && forge clean --scope project --verbose"
        else:
            steps.append(
                f"Remove or rename {path}, then rerun the original `forge extension {operation}` command; "
                "Forge cannot prove this entry is safe to clean."
            )
            continue
        steps.append(
            f"{path} is verified untracked Forge output. Preview with `{preview}`, apply with `{preview} --yes`, "
            f"then rerun the original `forge extension {operation}` command."
        )
    return " ".join(steps) or None


def _read_marker(path: Path, *, expected_runtime: str, expected_skill: str) -> _Marker:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise _InvalidMarker(f"invalid Forge provenance sentinel: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != _MARKER_KEYS:
        raise _InvalidMarker("invalid Forge provenance sentinel object or fields")
    schema_version = raw["schema_version"]
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise _InvalidMarker("invalid Forge provenance sentinel schema_version")
    if schema_version > FORGE_PACKAGE_SCHEMA_VERSION:
        raise _UnsupportedMarker(f"unsupported Forge provenance sentinel schema {schema_version}")
    if schema_version != FORGE_PACKAGE_SCHEMA_VERSION:
        raise _InvalidMarker(f"invalid Forge provenance sentinel schema {schema_version}")
    if raw["producer"] != FORGE_PACKAGE_PRODUCER:
        raise _InvalidMarker("Forge provenance sentinel producer does not match multi-forge")
    if raw["runtime"] != expected_runtime or raw["skill"] != expected_skill:
        raise _InvalidMarker("Forge provenance sentinel runtime or skill identity does not match its target")
    files = raw["files"]
    if not isinstance(files, list) or not files:
        raise _InvalidMarker("Forge provenance sentinel files must be a non-empty array")

    parsed: list[_MarkerFile] = []
    seen: set[PurePosixPath] = set()
    for row in files:
        if not isinstance(row, dict) or set(row) != _MARKER_FILE_KEYS:
            raise _InvalidMarker("invalid Forge provenance sentinel file row")
        raw_path = row["path"]
        digest = row["sha256"]
        mode = row["mode"]
        if not isinstance(raw_path, str) or _marker_path_problem(raw_path):
            raise _InvalidMarker(f"invalid Forge provenance sentinel path: {raw_path!r}")
        relative = PurePosixPath(raw_path)
        if relative in seen:
            raise _InvalidMarker(f"duplicate Forge provenance sentinel path: {raw_path}")
        seen.add(relative)
        if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise _InvalidMarker(f"invalid Forge provenance sentinel digest for {raw_path}")
        if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
            raise _InvalidMarker(f"invalid Forge provenance sentinel mode for {raw_path}")
        parsed.append(_MarkerFile(path=relative, sha256=digest, mode=mode))
    if [item.path.as_posix() for item in parsed] != sorted(item.path.as_posix() for item in parsed):
        raise _InvalidMarker("Forge provenance sentinel files are not sorted")
    if PurePosixPath("SKILL.md") not in seen or PurePosixPath(FORGE_PACKAGE_SENTINEL) in seen:
        raise _InvalidMarker("Forge provenance sentinel must list SKILL.md and exclude itself")
    return _Marker(runtime=expected_runtime, skill=expected_skill, files=tuple(parsed))


def _marker_path_problem(raw: str) -> bool:
    path = PurePosixPath(raw)
    return (
        not raw
        or raw == "."
        or path.is_absolute()
        or raw.startswith("/")
        or "\\" in raw
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != raw
    )


def _prove_package_tree(package_path: Path, marker: _Marker, *, cache_namespace: Path) -> _TreeProof:
    expected_files = {item.path.as_posix(): item for item in marker.files}
    expected_leaves = {*expected_files, FORGE_PACKAGE_SENTINEL}
    expected_dirs = {
        parent.as_posix() for item in marker.files for parent in item.path.parents if parent.as_posix() not in {"", "."}
    }
    actual_leaves: dict[str, tuple[Path, int]] = {}
    actual_dirs: set[str] = set()
    unsafe_reason: str | None = None

    def walk(directory: Path, relative: PurePosixPath) -> None:
        nonlocal unsafe_reason
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            unsafe_reason = f"package tree could not be read safely: {exc}"
            return
        for entry in entries:
            if unsafe_reason is not None:
                return
            child_relative = relative / entry.name
            child_path = directory / entry.name
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError as exc:
                unsafe_reason = f"package entry could not be inspected safely: {exc}"
                return
            key = child_relative.as_posix()
            if stat.S_ISDIR(mode):
                actual_dirs.add(key)
                walk(child_path, child_relative)
            elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
                actual_leaves[key] = (child_path, mode)
            else:
                unsafe_reason = f"package contains unsafe filesystem entry: {key}"

    walk(package_path, PurePosixPath())
    if unsafe_reason is not None:
        return _TreeProof(False, unsafe_reason, "invalid-target")
    unsafe_links = sorted(
        relative
        for relative, (_path, mode) in actual_leaves.items()
        if stat.S_ISLNK(mode) and relative not in expected_files
    )
    if unsafe_links:
        return _TreeProof(
            False,
            "package contains symlink where only a real directory or listed payload is allowed: "
            + ", ".join(unsafe_links),
            "invalid-target",
        )
    if set(actual_leaves) != expected_leaves:
        missing = sorted(expected_leaves - set(actual_leaves))
        extra = sorted(set(actual_leaves) - expected_leaves)
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unlisted " + ", ".join(extra))
        shape: PackageShape = "partial" if missing and not extra else "complete"
        return _TreeProof(False, "package tree differs from sentinel: " + "; ".join(detail), shape)
    if actual_dirs != expected_dirs:
        missing_dirs = sorted(expected_dirs - actual_dirs)
        extra_dirs = sorted(actual_dirs - expected_dirs)
        detail = []
        if missing_dirs:
            detail.append("missing directories " + ", ".join(missing_dirs))
        if extra_dirs:
            detail.append("unlisted directories " + ", ".join(extra_dirs))
        return _TreeProof(
            False,
            "package directory tree differs from sentinel: " + "; ".join(detail),
            "complete",
        )

    cache_roots: set[Path] = set()
    dangling = False
    for relative, expected in expected_files.items():
        path, mode = actual_leaves[relative]
        if stat.S_ISREG(mode):
            try:
                content = path.read_bytes()
                file_mode = stat.S_IMODE(path.stat().st_mode)
            except OSError as exc:
                return _TreeProof(
                    False,
                    f"payload {relative} could not be verified: {exc}",
                    "complete",
                )
            if hashlib.sha256(content).hexdigest() != expected.sha256:
                return _TreeProof(False, f"payload digest mismatch: {relative}", "complete")
            if file_mode != expected.mode:
                return _TreeProof(False, f"payload mode mismatch: {relative}", "complete")
            continue
        if not stat.S_ISLNK(mode):
            return _TreeProof(False, f"payload has unsafe type: {relative}", "invalid-target")
        try:
            raw_target = os.readlink(path)
        except OSError as exc:
            return _TreeProof(
                False,
                f"payload link could not be read: {relative}: {exc}",
                "invalid-target",
            )
        lexical_target = _lexical_link_target(path, raw_target)
        cache_root = _cache_package_root(lexical_target, expected.path, cache_namespace, marker)
        if cache_root is None:
            return _TreeProof(
                False,
                f"payload link is outside the expected Forge cache package: {relative}",
                "invalid-target",
            )
        cache_roots.add(cache_root)
        try:
            resolved_target = path.resolve(strict=True)
            target_mode = resolved_target.stat().st_mode
        except FileNotFoundError:
            dangling = True
            continue
        except OSError as exc:
            return _TreeProof(
                False,
                f"payload link could not be resolved: {relative}: {exc}",
                "invalid-target",
            )
        if not stat.S_ISREG(target_mode):
            return _TreeProof(
                False,
                f"payload link target is not a regular file: {relative}",
                "invalid-target",
            )
        try:
            resolved_target.relative_to(cache_namespace.resolve(strict=True))
        except (OSError, ValueError):
            return _TreeProof(
                False,
                f"payload link resolves outside the current Forge cache: {relative}",
                "invalid-target",
            )
        try:
            content = resolved_target.read_bytes()
        except OSError as exc:
            return _TreeProof(
                False,
                f"payload link target could not be read: {relative}: {exc}",
                "invalid-target",
            )
        if hashlib.sha256(content).hexdigest() != expected.sha256:
            return _TreeProof(False, f"payload link digest mismatch: {relative}", "complete")
        if stat.S_IMODE(target_mode) != expected.mode:
            return _TreeProof(False, f"payload link mode mismatch: {relative}", "complete")
    if len(cache_roots) > 1:
        return _TreeProof(
            False,
            "payload links do not reconstruct one compiled Forge package",
            "invalid-target",
        )
    return _TreeProof(True, "verified", "partial" if dangling else "complete")


def _cache_package_root(
    target: Path,
    relative: PurePosixPath,
    cache_namespace: Path,
    marker: _Marker,
) -> Path | None:
    try:
        target_relative = target.relative_to(cache_namespace)
    except ValueError:
        return None
    suffix = relative.parts
    if not suffix or len(target_relative.parts) <= len(suffix):
        return None
    if tuple(target_relative.parts[-len(suffix) :]) != suffix:
        return None
    root_relative = target_relative.parts[: -len(suffix)]
    if len(root_relative) != 3:
        return None
    runtime, skill, digest = root_relative
    if runtime != marker.runtime or skill != marker.skill or _SHA256_RE.fullmatch(digest) is None:
        return None
    return cache_namespace.joinpath(*root_relative)


def _lexical_link_target(path: Path, raw_target: str) -> Path:
    target = Path(raw_target)
    if not target.is_absolute():
        target = path.parent / target
    return Path(os.path.abspath(target))


def _is_usable_package(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode):
            return False
        skill_mode = (path / "SKILL.md").lstat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(skill_mode) or (stat.S_ISLNK(skill_mode) and (path / "SKILL.md").is_file())


def _lexists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


__all__ = [
    "CleanupScope",
    "PackageProvenance",
    "PackageShape",
    "RootKind",
    "SkillScanRoot",
    "UnmanagedSkillPackage",
    "canonical_package_path",
    "cleanup_proof_fingerprint",
    "codex_skill_visibility_roots",
    "revalidate_cleanup_candidate",
    "runtime_skill_scan_roots",
    "scan_unmanaged_skill_packages",
]
