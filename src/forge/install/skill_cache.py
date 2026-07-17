"""Stable content-addressed cache for compiled runtime skill packages."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from forge.core.paths import get_forge_home
from forge.core.state import atomic_write_bytes, atomic_write_text, file_lock_for_target, get_lock_path_for_target

from .skill_compiler import CompiledSkillPackage

_CACHE_FORMAT = b"forge-compiled-skill-v1\0"


def compiled_skill_digest(package: CompiledSkillPackage) -> str:
    """Return a deterministic digest over package identity, paths, modes, and bytes."""

    digest = hashlib.sha256(_CACHE_FORMAT)
    _update_digest(digest, package.runtime.value.encode())
    _update_digest(digest, package.name.encode())
    for package_file in sorted(package.files, key=lambda item: item.path.as_posix()):
        _update_digest(digest, package_file.path.as_posix().encode())
        _update_digest(digest, package_file.mode.to_bytes(4, "big"))
        _update_digest(digest, package_file.content)
    return digest.hexdigest()


def _update_digest(digest: "hashlib._Hash", value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def compiled_skill_cache_dir(package: CompiledSkillPackage, *, forge_home: Path | None = None) -> Path:
    """Return the stable cache directory without creating it."""

    root = forge_home or get_forge_home()
    return (
        root
        / "cache"
        / "compiled-skills"
        / "v1"
        / package.runtime.value
        / package.name
        / compiled_skill_digest(package)
    )


def materialize_compiled_skill(package: CompiledSkillPackage, *, forge_home: Path | None = None) -> Path:
    """Atomically materialize package files and return their stable cache root."""

    root = forge_home or get_forge_home()
    package_root = compiled_skill_cache_dir(package, forge_home=root)
    marker = package_root / ".complete"
    expected_digest = compiled_skill_digest(package)
    _prepare_cache_directories(package, package_root=package_root, forge_home=root)
    _prepare_cache_lock(get_lock_path_for_target(marker))
    with file_lock_for_target(target_path=marker, timeout_s=5.0):
        # Recheck after acquiring the lock so a stale cache-directory symlink cannot
        # redirect validation or package writes outside Forge's cache.
        _prepare_cache_directories(package, package_root=package_root, forge_home=root)
        if _cache_is_current(package, package_root, marker, expected_digest):
            return package_root
        for package_file in sorted(package.files, key=lambda item: item.path.as_posix()):
            target = package_root.joinpath(*package_file.path.parts)
            atomic_write_bytes(target, package_file.content, mode=package_file.mode)
        atomic_write_text(marker, expected_digest + "\n", mode=0o644)
    return package_root


def _prepare_cache_directories(
    package: CompiledSkillPackage,
    *,
    package_root: Path,
    forge_home: Path,
) -> None:
    """Create cache parents without retaining symlinked or non-directory components."""

    forge_home.mkdir(parents=True, exist_ok=True)
    current = forge_home
    for part in package_root.relative_to(forge_home).parts:
        current /= part
        _repair_cache_directory(current)

    package_parents = {
        parent
        for package_file in package.files
        for parent in _package_file_parents(package_root, package_file.path.parts[:-1])
    }
    for parent in sorted(package_parents, key=lambda path: (len(path.parts), str(path))):
        _repair_cache_directory(parent)


def _package_file_parents(package_root: Path, parts: tuple[str, ...]) -> tuple[Path, ...]:
    parents: list[Path] = []
    current = package_root
    for part in parts:
        current /= part
        parents.append(current)
    return tuple(parents)


def _repair_cache_directory(path: Path) -> None:
    while True:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            try:
                path.mkdir()
            except FileExistsError:
                continue
            return
        if stat.S_ISDIR(mode):
            return
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def _prepare_cache_lock(path: Path) -> None:
    """Remove a stale symlink instead of letting the lock open follow it."""

    while True:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISREG(mode):
            return
        if not stat.S_ISLNK(mode):
            raise OSError(f"compiled skill cache lock is not a regular file: {path}")
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        return


def _cache_is_current(
    package: CompiledSkillPackage,
    package_root: Path,
    marker: Path,
    expected_digest: str,
) -> bool:
    try:
        if marker.is_symlink():
            return False
        if marker.read_text(encoding="utf-8").strip() != expected_digest:
            return False
        for package_file in package.files:
            cached = package_root.joinpath(*package_file.path.parts)
            if cached.is_symlink() or not cached.is_file():
                return False
            if cached.read_bytes() != package_file.content:
                return False
            if stat.S_IMODE(cached.stat().st_mode) != package_file.mode:
                return False
    except OSError:
        return False
    return True


__all__ = [
    "compiled_skill_cache_dir",
    "compiled_skill_digest",
    "materialize_compiled_skill",
]
