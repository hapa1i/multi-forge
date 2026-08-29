#!/usr/bin/env python3
"""Resolve and validate the immutable wheel/runtime identity for release QA."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

_DIST_NAME = "multi-forge"
_QA_SKILL_PREFIX = "forge/_extensions/skills/qa/"
_PACKAGE_SENTINEL = ".forge-package.json"
_SAFE_TAG_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class ArtifactError(ValueError):
    """Raised when a release-QA artifact identity cannot be proven."""


def _normalize_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _safe_tag_component(value: str) -> str:
    result = _SAFE_TAG_RE.sub("-", value).strip("-.")
    if not result:
        raise ArtifactError(f"value cannot form a Docker tag component: {value!r}")
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_digest(files: dict[str, bytes]) -> str:
    """Return a stable digest for a relative-path-to-content mapping."""
    digest = hashlib.sha256()
    for relative, content in sorted(files.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()


def _local_qa_skill_files(skill_root: Path) -> dict[str, bytes]:
    try:
        resolved = skill_root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ArtifactError(f"QA driver package does not exist: {skill_root}") from exc
    if not resolved.is_dir():
        raise ArtifactError(f"QA driver package is not a directory: {resolved}")

    files: dict[str, bytes] = {}
    try:
        for path in resolved.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(resolved).as_posix()
            if relative == _PACKAGE_SENTINEL or "__pycache__" in Path(relative).parts or relative.endswith(".pyc"):
                continue
            files[relative] = path.read_bytes()
    except OSError as exc:
        raise ArtifactError(f"cannot read QA driver package {resolved}: {exc}") from exc
    if not files:
        raise ArtifactError(f"QA driver package is empty: {resolved}")
    return files


def _wheel_qa_skill_files(wheel_path: Path) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            files = {
                name.removeprefix(_QA_SKILL_PREFIX): archive.read(name)
                for name in archive.namelist()
                if name.startswith(_QA_SKILL_PREFIX)
                and not name.endswith("/")
                and name.removeprefix(_QA_SKILL_PREFIX) != _PACKAGE_SENTINEL
            }
    except (OSError, zipfile.BadZipFile) as exc:
        raise ArtifactError(f"cannot read QA driver package from {wheel_path}: {exc}") from exc
    if not files:
        raise ArtifactError(f"wheel contains no packaged QA driver at {_QA_SKILL_PREFIX}")
    return files


def _qa_driver_digest(*, wheel_path: Path, skill_root: Path) -> str:
    local_files = _local_qa_skill_files(skill_root)
    wheel_files = _wheel_qa_skill_files(wheel_path)
    missing = sorted(wheel_files.keys() - local_files.keys())
    extra = sorted(local_files.keys() - wheel_files.keys())
    changed = sorted(
        relative
        for relative in wheel_files.keys() & local_files.keys()
        if wheel_files[relative] != local_files[relative]
    )
    if missing or extra or changed:
        details = []
        if missing:
            details.append(f"missing={','.join(missing[:3])}")
        if extra:
            details.append(f"extra={','.join(extra[:3])}")
        if changed:
            details.append(f"changed={','.join(changed[:3])}")
        raise ArtifactError(
            "QA driver package does not match the selected wheel "
            f"({'; '.join(details)}). Install or sync the selected wheel's local Claude assets, "
            "restart Claude Code, and rerun QA."
        )
    return _tree_digest(local_files)


def _wheel_metadata(path: Path) -> tuple[str, str]:
    try:
        with zipfile.ZipFile(path) as archive:
            metadata_paths = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(metadata_paths) != 1:
                raise ArtifactError(f"wheel must contain exactly one .dist-info/METADATA file: {path}")
            metadata = Parser().parsestr(archive.read(metadata_paths[0]).decode("utf-8"))
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ArtifactError(f"cannot read wheel metadata from {path}: {exc}") from exc

    name = metadata.get("Name", "").strip()
    version = metadata.get("Version", "").strip()
    if _normalize_distribution_name(name) != _DIST_NAME:
        raise ArtifactError(f"wheel distribution is {name!r}, expected {_DIST_NAME!r}")
    if not version:
        raise ArtifactError("wheel METADATA has no Version")

    filename_parts = path.name.split("-")
    if len(filename_parts) < 5 or filename_parts[0] != "multi_forge":
        raise ArtifactError(f"wheel filename is not a normalized multi-forge wheel: {path.name}")
    if filename_parts[1] != version:
        raise ArtifactError(f"wheel filename version {filename_parts[1]!r} does not match METADATA version {version!r}")
    return name, version


def _load_runtime_track(matrix_path: Path, runtime_track: str) -> dict[str, Any]:
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"cannot read runtime matrix {matrix_path}: {exc}") from exc

    if matrix.get("schema_version") != 1:
        raise ArtifactError(f"unsupported runtime-matrix schema: {matrix.get('schema_version')!r}")
    tracks = matrix.get("tracks")
    if not isinstance(tracks, dict) or runtime_track not in tracks:
        available = ", ".join(sorted(tracks)) if isinstance(tracks, dict) else "none"
        raise ArtifactError(f"unknown runtime track {runtime_track!r}; available: {available}")
    track = tracks[runtime_track]
    if not isinstance(track, dict):
        raise ArtifactError(f"runtime track {runtime_track!r} is not an object")
    if runtime_track == matrix.get("blocking_track") and track.get("blocking") is not True:
        raise ArtifactError(f"blocking runtime track {runtime_track!r} is not marked blocking")
    return track


def inspect_artifact(
    *,
    wheel_path: Path,
    matrix_path: Path,
    runtime_track: str,
    skill_root: Path,
) -> dict[str, Any]:
    """Return the validated wheel/runtime identity consumed by the QA harness."""
    if "\n" in str(wheel_path) or "\t" in str(wheel_path):
        raise ArtifactError("wheel path cannot contain tabs or newlines")
    try:
        resolved_wheel = wheel_path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise ArtifactError(f"wheel does not exist: {wheel_path}") from exc
    if not resolved_wheel.is_file() or resolved_wheel.suffix != ".whl":
        raise ArtifactError(f"artifact must be one wheel file: {resolved_wheel}")

    distribution, version = _wheel_metadata(resolved_wheel)
    digest = _sha256(resolved_wheel)
    qa_driver_sha256 = _qa_driver_digest(wheel_path=resolved_wheel, skill_root=skill_root)
    track = _load_runtime_track(matrix_path, runtime_track)

    try:
        claude_version = str(track["claude"]["version"])
        codex_version = str(track["codex"]["version"])
    except (KeyError, TypeError) as exc:
        raise ArtifactError(f"runtime track {runtime_track!r} does not name both client versions") from exc

    base_image = f"forge-claude-test:{_safe_tag_component(claude_version)}-codex-{_safe_tag_component(codex_version)}"
    release_tag = (
        f"{_safe_tag_component(version)}-sha-{digest[:12]}-{_safe_tag_component(runtime_track)}"
        f"-claude-{_safe_tag_component(claude_version)}-codex-{_safe_tag_component(codex_version)}"
    )
    if len(release_tag) > 128:
        raise ArtifactError(f"release image tag is longer than Docker's 128-character limit: {release_tag}")

    identity = {
        "wheel_path": str(resolved_wheel),
        "wheel_dir": str(resolved_wheel.parent),
        "wheel_filename": resolved_wheel.name,
        "distribution": distribution,
        "forge_version": version,
        "sha256": digest,
        "runtime_track": runtime_track,
        "runtime_track_blocking": bool(track.get("blocking")),
        "claude_version": claude_version,
        "codex_version": codex_version,
        "base_image": base_image,
        "release_image": f"forge-qa-release:{release_tag}",
    }
    identity["qa_driver_sha256"] = qa_driver_sha256
    return identity


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--skill-root", type=Path, required=True)
    parser.add_argument("--runtime-track", default="pinned")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        identity = inspect_artifact(
            wheel_path=args.wheel,
            matrix_path=args.matrix,
            runtime_track=args.runtime_track,
            skill_root=args.skill_root,
        )
    except ArtifactError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(identity, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
