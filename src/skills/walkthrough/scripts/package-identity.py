#!/usr/bin/env python3
"""Report the answering distribution and verify an installed skill package tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_digest(rows: list[tuple[str, str, int]]) -> str:
    payload = json.dumps(sorted(rows), separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def verify_skill_root(root: Path) -> tuple[str, str, bool, list[str]]:
    marker_path = root / ".forge-package.json"
    marker_bytes = marker_path.read_bytes()
    marker = json.loads(marker_bytes)
    failures: list[str] = []
    if marker.get("schema_version") != 1 or marker.get("producer") != "multi-forge":
        failures.append("marker_identity")
    if marker.get("skill") != "walkthrough" or marker.get("runtime") != "claude_code":
        failures.append("skill_runtime")

    expected_paths: set[str] = set()
    payload_rows: list[tuple[str, str, int]] = []
    file_rows = marker.get("files", [])
    if not isinstance(file_rows, list):
        failures.append("marker_files")
        file_rows = []
    for row in file_rows:
        if not isinstance(row, dict):
            failures.append("invalid_file_row")
            continue
        relative = row.get("path")
        expected_sha256 = row.get("sha256")
        expected_mode = row.get("mode")
        if not isinstance(relative, str) or not isinstance(expected_sha256, str) or not isinstance(expected_mode, int):
            failures.append("invalid_file_row")
            continue
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or any(part in {"", ".", ".."} for part in parsed.parts):
            failures.append(relative)
            continue
        if relative in expected_paths:
            failures.append(relative)
            continue
        expected_paths.add(relative)
        payload_rows.append((relative, expected_sha256, expected_mode))
        target = root.joinpath(*parsed.parts)
        try:
            metadata = target.lstat()
        except OSError:
            failures.append(relative)
            continue
        if not stat.S_ISREG(metadata.st_mode):
            failures.append(relative)
            continue
        if _sha256(target) != expected_sha256 or stat.S_IMODE(metadata.st_mode) != expected_mode:
            failures.append(relative)

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if (path.is_file() or path.is_symlink()) and path.name != ".forge-package.json"
    }
    failures.extend(sorted(actual_paths - expected_paths))
    failures.extend(sorted(expected_paths - actual_paths))
    return (
        f"sha256:{hashlib.sha256(marker_bytes).hexdigest()}",
        _payload_digest(payload_rows),
        not failures,
        sorted(set(failures)),
    )


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
        marker_digest, payload_digest, tree_matches, failures = verify_skill_root(args.skill_root.resolve())
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
        "skill_root": str(args.skill_root.resolve()),
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
