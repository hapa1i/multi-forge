#!/usr/bin/env python3
"""Report the answering distribution and verify an installed skill package tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

_MARKER_KEYS = {"schema_version", "producer", "runtime", "skill", "files"}
_MARKER_FILE_KEYS = {"path", "sha256", "mode"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _payload_digest(rows: list[tuple[str, str, int]]) -> str:
    payload = json.dumps(sorted(rows), separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _stat_fingerprint(info: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    """Return the stable identity fields used to detect in-place replacement."""
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _open_directory(path: str | Path, *, dir_fd: int | None = None) -> int | None:
    """Open one real directory without following its final path component."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags) if dir_fd is None else os.open(path, flags, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            return None
    except OSError:
        os.close(descriptor)
        return None
    return descriptor


def _read_regular_file(path: str | Path, *, dir_fd: int | None = None) -> tuple[bytes, int] | None:
    """Read one real file relative to a verified parent directory descriptor."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags) if dir_fd is None else os.open(path, flags, dir_fd=dir_fd)
    except OSError:
        return None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            content = handle.read()
        after = os.fstat(descriptor)
        if _stat_fingerprint(before) != _stat_fingerprint(after):
            return None
        return content, stat.S_IMODE(after.st_mode)
    except OSError:
        return None
    finally:
        os.close(descriptor)


def verify_skill_root(root: Path) -> tuple[str, str, bool, list[str]]:
    root_fd = _open_directory(root)
    if root_fd is None:
        return _payload_digest([]), _payload_digest([]), False, ["."]
    try:
        opened_root = os.fstat(root_fd)
        marker_read = _read_regular_file(".forge-package.json", dir_fd=root_fd)
        if marker_read is None:
            return _payload_digest([]), _payload_digest([]), False, [".forge-package.json"]
        marker_bytes, _ = marker_read

        marker = json.loads(marker_bytes)
        failures: list[str] = []
        if not isinstance(marker, dict) or set(marker) != _MARKER_KEYS:
            failures.append("marker_schema")
            marker = marker if isinstance(marker, dict) else {}
        schema_version = marker.get("schema_version")
        if type(schema_version) is not int or schema_version != 1 or marker.get("producer") != "multi-forge":
            failures.append("marker_identity")
        if marker.get("skill") != "walkthrough" or marker.get("runtime") != "claude_code":
            failures.append("skill_runtime")

        expected_paths: set[str] = set()
        payload_rows: list[tuple[str, str, int]] = []
        file_rows = marker.get("files", [])
        if not isinstance(file_rows, list) or not file_rows:
            failures.append("marker_files")
            file_rows = []
        for row in file_rows:
            if not isinstance(row, dict) or set(row) != _MARKER_FILE_KEYS:
                failures.append("invalid_file_row")
                continue
            relative = row.get("path")
            expected_sha256 = row.get("sha256")
            expected_mode = row.get("mode")
            if (
                not isinstance(relative, str)
                or not relative
                or not isinstance(expected_sha256, str)
                or _SHA256_RE.fullmatch(expected_sha256) is None
                or isinstance(expected_mode, bool)
                or not isinstance(expected_mode, int)
                or not 0 <= expected_mode <= 0o7777
            ):
                failures.append("invalid_file_row")
                continue
            parsed = PurePosixPath(relative)
            if (
                parsed.is_absolute()
                or relative.startswith("/")
                or "\\" in relative
                or any(part in {"", ".", ".."} for part in parsed.parts)
                or parsed.as_posix() != relative
            ):
                failures.append(relative)
                continue
            if relative in expected_paths:
                failures.append(relative)
                continue
            expected_paths.add(relative)
            payload_rows.append((relative, expected_sha256, expected_mode))

        if [row[0] for row in payload_rows] != sorted(row[0] for row in payload_rows):
            failures.append("marker_file_order")
        if "SKILL.md" not in expected_paths or ".forge-package.json" in expected_paths:
            failures.append("marker_files")

        expected_dirs = {
            parent.as_posix()
            for relative in expected_paths
            for parent in PurePosixPath(relative).parents
            if parent.as_posix() not in {"", "."}
        }
        actual_paths: set[str] = set()
        actual_dirs: set[str] = set()
        actual_payload: dict[str, tuple[str, int]] = {}
        marker_seen = False

        def walk(directory_fd: int, relative: PurePosixPath) -> None:
            nonlocal marker_seen
            try:
                before = os.fstat(directory_fd)
                with os.scandir(directory_fd) as entries:
                    child_names = sorted(entry.name for entry in entries)
            except OSError:
                failures.append(relative.as_posix() or ".")
                return

            for child_name in child_names:
                child_relative = relative / child_name
                key = child_relative.as_posix()
                try:
                    mode = os.stat(child_name, dir_fd=directory_fd, follow_symlinks=False).st_mode
                except OSError:
                    failures.append(key)
                    continue
                if stat.S_ISDIR(mode):
                    actual_dirs.add(key)
                    child_fd = _open_directory(child_name, dir_fd=directory_fd)
                    if child_fd is None:
                        failures.append(f"{key}/")
                        continue
                    try:
                        walk(child_fd, child_relative)
                    finally:
                        os.close(child_fd)
                elif stat.S_ISREG(mode):
                    if key == ".forge-package.json":
                        marker_seen = True
                    else:
                        actual_paths.add(key)
                    if key == ".forge-package.json" or key in expected_paths:
                        target_read = _read_regular_file(child_name, dir_fd=directory_fd)
                        if target_read is None:
                            failures.append(key)
                            continue
                        content, actual_mode = target_read
                        if key == ".forge-package.json":
                            if content != marker_bytes:
                                failures.append(key)
                        else:
                            actual_payload[key] = (hashlib.sha256(content).hexdigest(), actual_mode)
                else:
                    failures.append(key)

            try:
                after = os.fstat(directory_fd)
            except OSError:
                failures.append(relative.as_posix() or ".")
                return
            if _stat_fingerprint(before) != _stat_fingerprint(after):
                failures.append(relative.as_posix() or ".")

        walk(root_fd, PurePosixPath())
        if not marker_seen:
            failures.append(".forge-package.json")
        for relative, expected_sha256, expected_mode in payload_rows:
            if actual_payload.get(relative) != (expected_sha256, expected_mode):
                failures.append(relative)
        failures.extend(sorted(actual_paths - expected_paths))
        failures.extend(sorted(expected_paths - actual_paths))
        failures.extend(f"{path}/" for path in sorted(actual_dirs - expected_dirs))
        failures.extend(f"{path}/" for path in sorted(expected_dirs - actual_dirs))
        try:
            current_root = root.lstat()
        except OSError:
            failures.append(".")
        else:
            if (
                current_root.st_dev,
                current_root.st_ino,
                stat.S_IFMT(current_root.st_mode),
            ) != (
                opened_root.st_dev,
                opened_root.st_ino,
                stat.S_IFMT(opened_root.st_mode),
            ):
                failures.append(".")
        return (
            f"sha256:{hashlib.sha256(marker_bytes).hexdigest()}",
            _payload_digest(payload_rows),
            not failures,
            sorted(set(failures)),
        )
    finally:
        os.close(root_fd)


def answering_distribution() -> dict[str, object]:
    """Resolve metadata through the Forge launcher that answers on PATH."""
    launcher = shutil.which("forge")
    if launcher is None:
        raise RuntimeError("forge launcher is not on PATH")
    first_line = Path(launcher).open("rb").readline().decode("utf-8").strip()
    if not first_line.startswith("#!"):
        raise RuntimeError("forge launcher has no Python shebang")
    interpreter = shlex.split(first_line[2:])
    probe_code = """
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path

distribution = metadata.distribution("multi-forge")
forge_spec = importlib.util.find_spec("forge")
if forge_spec is None or not forge_spec.submodule_search_locations:
    raise RuntimeError("answering Forge package has no resource root")
resource_root = Path(next(iter(forge_spec.submodule_search_locations))) / "_extensions" / "skills" / "walkthrough"
direct_url_text = distribution.read_text("direct_url.json")
direct_url = json.loads(direct_url_text) if direct_url_text else {}
editable = bool(
    isinstance(direct_url, dict)
    and isinstance(direct_url.get("dir_info"), dict)
    and direct_url["dir_info"].get("editable") is True
)
payload_present = resource_root.is_dir()
issue = "editable-install" if editable else (None if payload_present else "walkthrough-payload-missing")
rows = []
if issue is None:
    for path in resource_root.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            rows.append((path.relative_to(resource_root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode & 0o777))
payload_sha256 = None
if issue is None:
    payload = json.dumps(sorted(rows), separators=(",", ":")).encode("utf-8")
    payload_sha256 = "sha256:" + hashlib.sha256(payload).hexdigest()
print(json.dumps({
    "distribution": distribution.metadata["Name"],
    "version": distribution.version,
    "distribution_root": str(Path(distribution.locate_file("")).resolve()),
    "forge_module": str(Path(forge_spec.origin).resolve()) if forge_spec.origin else None,
    "answering_distribution_kind": "editable" if editable else "installed",
    "answering_distribution_issue": issue,
    "walkthrough_source_root": str(resource_root.resolve()),
    "walkthrough_payload_present": payload_present,
    "walkthrough_payload_sha256": payload_sha256,
}))
"""
    probe = subprocess.run(
        [
            *interpreter,
            "-c",
            probe_code,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(probe.stdout)
    result["forge_launcher"] = str(Path(launcher).resolve())
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-root", required=True, type=Path)
    args = parser.parse_args()

    try:
        distribution = answering_distribution()
        marker_digest, payload_digest, tree_matches, failures = verify_skill_root(args.skill_root)
    except (
        OSError,
        UnicodeError,
        ValueError,
        RuntimeError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps({"status": "error", "reason": type(exc).__name__}),
            file=sys.stderr,
        )
        return 2
    distribution_matches = distribution.get(
        "answering_distribution_issue"
    ) is None and payload_digest == distribution.get("walkthrough_payload_sha256")
    result = {
        **distribution,
        "skill_root": str(args.skill_root.absolute()),
        "package_marker_sha256": marker_digest,
        "installed_payload_sha256": payload_digest,
        "package_tree_matches_marker": tree_matches,
        "package_matches_answering_distribution": distribution_matches,
        "mismatches": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if tree_matches and distribution_matches else 1


if __name__ == "__main__":
    raise SystemExit(main())
