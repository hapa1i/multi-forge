"""Acquire the explicitly approved, bounded A2 local inventory into a private directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import dacite

from forge.core.runtime.codex_review_source import directory_fd
from forge.session.active import ActiveSessionIndex
from forge.session.exceptions import InvalidSessionNameError
from forge.session.identity import make_scoped_key
from forge.session.validation import validate_name

REPOSITORY = Path("/Users/habib/workspace/multi-forge")
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_MANIFESTS = 24
MAX_PER_RUNTIME = 3
MAX_NATIVE_BYTES = 20 * 1024 * 1024
SCHEMA_VERSION = 1
AVAILABILITY_ACTION_WINDOW = {
    "start_inclusive": "2026-10-01T00:00:00Z",
    "end_exclusive": "2026-10-18T00:00:00Z",
}


class Refusal(ValueError):
    """Carry a bounded reason code; private paths and source text never enter CLI errors."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def no_symlinks(path: Path, *, allow_missing: bool = False) -> None:
    """Check every component without resolving an untrusted symlink."""
    if not path.is_absolute() or ".." in path.parts:
        raise Refusal("unsafe_path")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise Refusal("missing_path") from None
        if stat.S_ISLNK(info.st_mode):
            raise Refusal("symlink_component")


def read_regular(path: Path, limit: int) -> tuple[bytes, dict[str, int]]:
    """Read once with a strict bound and refuse changed identity, size or timestamps."""
    try:
        with directory_fd(path.parent) as parent:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise Refusal("non_regular_or_linked_file")
                if before.st_size > limit:
                    raise Refusal("file_size_limit")
                raw = stream.read(limit + 1)
                finished = os.fstat(stream.fileno())
            after = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(after.st_mode):
                raise Refusal("symlink_component")
    except FileNotFoundError:
        raise Refusal("missing_path") from None
    except OSError:
        raise Refusal("unreadable_or_symlinked_file") from None

    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    identity = tuple(getattr(before, field) for field in fields)
    if any(tuple(getattr(info, field) for field in fields) != identity for info in (finished, after)):
        raise Refusal("changed_read")
    if len(raw) != before.st_size or len(raw) > limit:
        raise Refusal("file_size_limit")
    return raw, dict(zip(fields, identity, strict=True))


def parse_json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise Refusal("duplicate_json_key")
            result[key] = value
        return result

    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise Refusal("invalid_json") from None
    if not isinstance(data, dict):
        raise Refusal("unsupported_json_shape")
    return data


def timestamp(value: Any) -> float:
    if not isinstance(value, str):
        raise Refusal("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.timestamp()
    except (ValueError, OverflowError):
        raise Refusal("invalid_timestamp") from None


def verified_worktrees(repository: Path) -> set[str]:
    """Use only Git worktree metadata, never history or source contents."""
    no_symlinks(repository)
    result = subprocess.run(
        ["git", "-C", str(repository), "worktree", "list", "--porcelain", "-z"],
        capture_output=True,
        check=False,
        timeout=10,
    )
    if result.returncode or len(result.stdout) > MAX_INDEX_BYTES:
        raise Refusal("worktree_metadata_unavailable")
    try:
        paths = {part[9:].decode("utf-8") for part in result.stdout.split(b"\0") if part.startswith(b"worktree ")}
    except UnicodeError:
        raise Refusal("invalid_worktree_metadata") from None
    if str(repository) not in paths:
        raise Refusal("repository_identity_unverified")
    return paths


def _index(path: Path) -> tuple[dict[str, Any], str]:
    raw, _ = read_regular(path, MAX_INDEX_BYTES)
    data = parse_json(raw)
    if (
        set(data) != {"version", "sessions"}
        or type(data["version"]) is not int
        or data["version"] != 1
        or not isinstance(data["sessions"], dict)
    ):
        raise Refusal("unsupported_index_schema")
    if any(not isinstance(key, str) or not isinstance(row, dict) for key, row in data["sessions"].items()):
        raise Refusal("unsupported_index_row")
    return data["sessions"], digest(raw)


def _name(key: str, root: str) -> str:
    name = key.split("|", 1)[0]
    try:
        validate_name(name)
    except InvalidSessionNameError:
        raise Refusal("invalid_session_identity") from None
    if key != make_scoped_key(name, root):
        raise Refusal("ambiguous_session_identity")
    return name


def _native_id(value: Any) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError):
        raise Refusal("unconfirmed_native_identity") from None
    return value


def _metadata(key: str, row: dict[str, Any], worktrees: set[str], active: dict[str, Any], home: Path) -> dict[str, Any]:
    root = row.get("forge_root") or row.get("worktree_path")
    checkout = row.get("checkout_root") or row.get("worktree_path")
    if root not in worktrees or checkout not in worktrees:
        raise Refusal("unverified_worktree_membership")
    name = _name(key, root)
    for path in (Path(root), Path(checkout)):
        no_symlinks(path)
    if key in active:
        raise Refusal("active_registry_entry")
    native_ids = {row.get("claude_session_id"), row.get("codex_thread_id")} - {None}
    if any(entry.get("claude_session_id") in native_ids for entry in active.values()):
        raise Refusal("active_native_identity")
    manifest_path = Path(root) / ".forge/sessions" / name / "forge.session.json"
    raw, _ = read_regular(manifest_path, MAX_MANIFEST_BYTES)
    manifest = parse_json(raw)
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] not in (1, 2, 3, 4, 5):
        raise Refusal("unsupported_manifest_schema")
    if manifest.get("name") != name or manifest.get("forge_root") != root:
        raise Refusal("manifest_identity_mismatch")
    worktree = manifest.get("worktree")
    if worktree is not None and (not isinstance(worktree, dict) or worktree.get("path") != checkout):
        raise Refusal("manifest_worktree_mismatch")
    intent = manifest.get("intent")
    confirmed = manifest.get("confirmed")
    if not isinstance(intent, dict) or not isinstance(confirmed, dict):
        raise Refusal("unsupported_manifest_shape")
    launch = intent.get("launch") or {}
    if not isinstance(launch, dict):
        raise Refusal("unsupported_launch_shape")
    if launch.get("mode", "host") != "host" or confirmed.get("is_sandboxed", False) is not False:
        raise Refusal("sidecar_or_unknown_launch")
    runtime = launch.get("runtime", "claude_code")
    if runtime not in ("claude_code", "codex"):
        raise Refusal("unsupported_runtime")
    if runtime == "claude_code":
        native_id = _native_id(confirmed.get("claude_session_id"))
        native_path = confirmed.get("transcript_path")
        cwd = confirmed.get("claude_project_root")
        if cwd != checkout:
            raise Refusal("unconfirmed_native_cwd")
        if row.get("claude_session_id") != native_id or row.get("codex_thread_id"):
            raise Refusal("index_native_identity_mismatch")
        # Encode the recorded, confirmed launch cwd lexically; resolving it would admit a different source path.
        expected = home / ".claude/projects" / cwd.replace("/", "-").replace(".", "-").replace("_", "-")
        expected = expected / f"{native_id}.jsonl"
    else:
        codex = confirmed.get("codex")
        if not isinstance(codex, dict):
            raise Refusal("unconfirmed_native_identity")
        native_id = _native_id(codex.get("thread_id"))
        native_path = codex.get("rollout_path")
        cwd = checkout
        if row.get("codex_thread_id") != native_id or row.get("claude_session_id"):
            raise Refusal("index_native_identity_mismatch")
        expected = None
    return {
        "canonical_identity": key,
        "repository": row["project_root"],
        "runtime": runtime,
        "last_accessed_at": row["last_accessed_at"],
        "worktree": checkout,
        "forge_root": root,
        "active": False,
        "native_id": native_id,
        "native_path": native_path if isinstance(native_path, str) else None,
        "expected_claude_path": str(expected) if expected else None,
        "expected_cwd": cwd,
        "manifest_sha256": digest(raw),
        "manifest_path": str(manifest_path),
    }


def inventory_metadata(
    repository: Path,
    home: Path,
    worktrees: set[str],
    *,
    expected_hashes: tuple[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select metadata before reading any native source; cap matching manifest candidates at 24."""
    return _inventory_metadata(repository, home, worktrees, expected_hashes=expected_hashes)


def inventory_availability(repository: Path, home: Path, worktrees: set[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Check availability within the same 24-candidate cohort before allocating runtime slots; read no native content."""
    return _inventory_metadata(repository, home, worktrees, availability_first=True)


def _inventory_metadata(
    repository: Path,
    home: Path,
    worktrees: set[str],
    *,
    expected_hashes: tuple[str, str] | None = None,
    availability_first: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    index, index_sha = _index(home / ".forge/sessions/index.json")
    active, active_sha = _index(home / ".forge/sessions/active.json")
    if expected_hashes is not None and (index_sha, active_sha) != expected_hashes:
        raise Refusal("metadata_snapshot_changed")
    try:
        parsed_active = dacite.from_dict(
            data_class=ActiveSessionIndex,
            data={"version": 1, "sessions": active},
            config=dacite.Config(strict=True),
        )
        for key, entry in parsed_active.sessions.items():
            root = entry.forge_root or entry.worktree_path
            _name(key, root)
            timestamp(entry.started_at)
            if entry.launch_mode not in ("host", "sidecar"):
                raise Refusal("uncertain_active_registry")
            pid = entry.launcher_pid
            if pid is not None and (type(pid) is not int or not 0 < pid < 2**31):
                raise Refusal("uncertain_active_registry")
    except (dacite.DaciteError, TypeError, ValueError):
        raise Refusal("uncertain_active_registry") from None
    matching = [(key, row) for key, row in index.items() if row.get("project_root") == str(repository)]
    refusals: Counter[str] = Counter()
    valid = []
    for key, row in matching:
        try:
            valid.append((timestamp(row.get("last_accessed_at")), key, row))
        except Refusal as exc:
            refusals[str(exc)] += 1
    valid.sort(key=lambda value: (-value[0], value[1]))
    metadata = []
    dispositions: dict[str, dict[str, Any]] = {}
    for rank, (_, key, row) in enumerate(valid[:MAX_MANIFESTS], 1):
        if availability_first:
            dispositions[key] = {"candidate_id": f"candidate-{rank:02d}", "index_identity_sha256": digest(key.encode())}
        try:
            metadata.append(_metadata(key, row, worktrees, active, home))
        except (Refusal, OSError, TypeError):
            # Type errors are corrupt metadata, not permission to infer a replacement identity.
            reason = sys_exception_reason()
            refusals[reason] += 1
            if availability_first:
                dispositions[key].update(status="excluded", stage="metadata", reason=reason)
    duplicate_ids = {
        row["native_id"] for row in metadata if sum(other["native_id"] == row["native_id"] for other in metadata) > 1
    }
    selected: list[dict[str, Any]] = []
    runtime_counts: Counter[str] = Counter()
    available_counts: Counter[str] = Counter()
    source_refusals: Counter[str] = Counter()
    path_checks = 0
    for row in metadata:
        disposition = dispositions.get(row["canonical_identity"], {})
        if row["native_id"] in duplicate_ids:
            refusals["duplicate_native_identity"] += 1
            disposition.update(status="excluded", stage="metadata", reason="duplicate_native_identity")
            continue
        if availability_first:
            path_checks += 1
            disposition.update(runtime=row["runtime"], manifest_sha256=row["manifest_sha256"])
            try:
                row = {**row, "source": admit_source(row, home)}
            except (Refusal, OSError):
                reason = sys_exception_reason()
                source_refusals[reason] += 1
                disposition.update(status="excluded", stage="availability", reason=reason)
                continue
            available_counts[row["runtime"]] += 1
        if runtime_counts[row["runtime"]] < MAX_PER_RUNTIME:
            runtime_counts[row["runtime"]] += 1
            selected.append({"session_id": f"session-{len(selected) + 1:02d}", "family_id": "family-unknown", **row})
            disposition.update(
                status="selected", stage="allocation", session_id=selected[-1]["session_id"], reason=None
            )
        else:
            disposition.update(status="excluded", stage="allocation", reason="runtime_selection_limit")
    summary = {
        "stage": "metadata",
        "schema_version": SCHEMA_VERSION,
        "matching_index_rows": len(matching),
        "metadata_candidates_within_cap": min(len(valid), MAX_MANIFESTS),
        "metadata_candidates_beyond_cap": max(0, len(valid) - MAX_MANIFESTS),
        "eligible_metadata_rows": len(metadata) - sum(row["native_id"] in duplicate_ids for row in metadata),
        "selected_sessions": len(selected),
        "selected_by_runtime": dict(runtime_counts),
        "metadata_exclusions": dict(sorted(refusals.items())),
        "native_files_read": 0,
        "native_bytes_read": 0,
        "named_actions_selected": 0,
        "quality_accepted": False,
    }
    if availability_first:
        summary.update(
            stage="availability_metadata",
            selection="availability_first_within_fixed_recency_cohort",
            prospective_action_window=dict(AVAILABILITY_ACTION_WINDOW),
            action_window_verified=False,
            native_paths_checked=path_checks,
            available_sources_by_runtime=dict(available_counts),
            available_sources=sum(available_counts.values()),
            source_exclusions=dict(sorted(source_refusals.items())),
            available_sources_beyond_runtime_cap=sum(available_counts.values()) - len(selected),
            selected_source_bytes_by_metadata=sum(row["source"]["size"] for row in selected),
            runtime_shortfalls={
                runtime: MAX_PER_RUNTIME - runtime_counts[runtime] for runtime in ("claude_code", "codex")
            },
            native_header_identity_verified=False,
            completed_turns_verified=False,
            native_actions_admitted=False,
            runtime_admitted=False,
        )
    ledger = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "repository": str(repository),
        "home": str(home),
        "index_sha256": index_sha,
        "active_index_sha256": active_sha,
        "extractor_sha256": digest(Path(__file__).read_bytes()),
        "selected": selected,
        "summary": summary,
    }
    if availability_first:
        ledger["candidates"] = list(dispositions.values())
        ledger["selection_bias"] = (
            "Availability filtering favors retained local sources; missing sources imply no action count."
        )
    return summary, ledger


def sys_exception_reason() -> str:
    """Avoid exposing exception messages from filesystem and arbitrary metadata values."""
    import sys

    exc = sys.exception()
    return str(exc) if isinstance(exc, Refusal) else "malformed_or_unreadable_metadata"


def admit_source(row: dict[str, Any], home: Path) -> dict[str, Any]:
    """Inspect only the selected confirmed source; never discover a substitute."""
    raw_path = row["native_path"]
    if not isinstance(raw_path, str) or not raw_path:
        raise Refusal("missing_confirmed_native_path")
    source = Path(raw_path)
    if not source.is_absolute():
        source = Path(row["forge_root"]) / source
    if ".." in source.parts:
        raise Refusal("unsafe_path")
    artifact_root = (
        Path(row["forge_root"]) / ".forge/artifacts" / row["canonical_identity"].split("|", 1)[0] / "transcripts"
    )
    if not source.is_relative_to(artifact_root):
        if row["runtime"] == "claude_code":
            if str(source) != row["expected_claude_path"]:
                raise Refusal("custom_or_unconfirmed_native_store")
        else:
            base = home / ".codex/sessions"
            if not source.is_relative_to(base):
                raise Refusal("custom_or_unconfirmed_native_store")
            relative = source.relative_to(base)
            if len(relative.parts) != 4 or not re.fullmatch(
                r"rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-" + re.escape(row["native_id"]) + r"\.jsonl",
                source.name,
            ):
                raise Refusal("unconfirmed_rollout_filename")
    no_symlinks(source)
    info = source.stat()
    if not stat.S_ISREG(info.st_mode):
        raise Refusal("non_regular_file")
    if info.st_size > MAX_NATIVE_BYTES:
        raise Refusal("native_file_size_limit")
    return {"path": str(source), "size": info.st_size, "device": info.st_dev, "inode": info.st_ino}


def validate_selection(ledger: dict[str, Any]) -> None:
    """Reject edited cap/identity fields before inspecting any source path."""
    selected = ledger.get("selected")
    if not isinstance(selected, list) or len(selected) > 6 or any(not isinstance(row, dict) for row in selected):
        raise Refusal("metadata_selection_limit")
    if any(row.get("runtime") not in ("claude_code", "codex") for row in selected):
        raise Refusal("unsupported_runtime")
    if any(count > MAX_PER_RUNTIME for count in Counter(row["runtime"] for row in selected).values()):
        raise Refusal("metadata_selection_limit")
    for field in ("session_id", "native_id", "canonical_identity"):
        values = [row.get(field) for row in selected]
        if any(not isinstance(value, str) for value in values) or len(set(values)) != len(values):
            raise Refusal("duplicate_or_missing_selected_identity")
    for row in selected:
        if row.get("repository") != ledger.get("repository") or row.get("active") is not False:
            raise Refusal("metadata_scope_mismatch")
        _name(row["canonical_identity"], row["forge_root"])
        _native_id(row["native_id"])
        if row.get("expected_cwd") != row.get("worktree"):
            raise Refusal("unconfirmed_native_cwd")
        if row["runtime"] == "claude_code":
            cwd = row["expected_cwd"]
            expected = (
                Path(ledger["home"]) / ".claude/projects" / cwd.replace("/", "-").replace(".", "-").replace("_", "-")
            )
            if row.get("expected_claude_path") != str(expected / f"{row['native_id']}.jsonl"):
                raise Refusal("unconfirmed_native_path")


def inspect_sources(ledger: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Freeze source-level admissions before parsing any transcript records."""
    validate_selection(ledger)
    refusals: Counter[str] = Counter()
    admitted = []
    for row in ledger["selected"]:
        try:
            admitted.append({**row, "source": admit_source(row, Path(ledger["home"]))})
        except (Refusal, OSError):
            refusals[sys_exception_reason()] += 1
    summary = {
        **ledger["summary"],
        "stage": "source_metadata",
        "source_files_admitted_by_metadata": len(admitted),
        "source_bytes_admitted_by_metadata": sum(row["source"]["size"] for row in admitted),
        "source_exclusions": dict(sorted(refusals.items())),
    }
    return summary, {"metadata": ledger, "admitted": admitted, "summary": summary}


def private_write(path: Path, value: Any) -> None:
    raw = (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--metadata", action="store_true")
    group.add_argument(
        "--availability-first", action="store_true", help="Check only confirmed path metadata before allocation"
    )
    group.add_argument("--inspect-sources", type=Path)
    group.add_argument("--recheck-metadata", type=Path, help="Re-evaluate only an unchanged prior index snapshot")
    args = parser.parse_args()
    try:
        temporary_root = Path(tempfile.gettempdir()).resolve()
        if args.metadata or args.availability_first:
            prefix = "jev-a2-availability-" if args.availability_first else "jev-a2-feasibility-"
            directory = Path(tempfile.mkdtemp(prefix=prefix, dir=temporary_root))
            collect = inventory_availability if args.availability_first else inventory_metadata
            summary, ledger = collect(REPOSITORY, Path.home(), verified_worktrees(REPOSITORY))
            stem = "availability" if args.availability_first else "metadata"
            private_write(directory / f"{stem}-private.json", ledger)
            private_write(directory / f"{stem}-summary.json", summary)
        else:
            directory = args.inspect_sources or args.recheck_metadata
            # Retain access to ledgers created before the platform temporary root was used.
            if directory.parent not in {temporary_root, Path("/private/tmp")} or not directory.name.startswith(
                "jev-a2-feasibility-"
            ):
                raise Refusal("unapproved_output_directory")
            no_symlinks(directory)
            if directory.stat().st_mode & 0o777 != 0o700:
                raise Refusal("output_directory_not_private")
            corrected = args.inspect_sources and (directory / "metadata-corrected-private.json").exists()
            metadata_name = "metadata-corrected-private.json" if corrected else "metadata-private.json"
            metadata, _ = read_regular(directory / metadata_name, MAX_INDEX_BYTES)
            stored = parse_json(metadata)
            if stored.get("repository") != str(REPOSITORY) or stored.get("home") != str(Path.home()):
                raise Refusal("metadata_scope_mismatch")
            if args.recheck_metadata:
                hashes = (stored["index_sha256"], stored["active_index_sha256"])
                summary, ledger = inventory_metadata(
                    REPOSITORY, Path.home(), verified_worktrees(REPOSITORY), expected_hashes=hashes
                )
                private_write(directory / "metadata-corrected-private.json", ledger)
                private_write(directory / "metadata-corrected-summary.json", summary)
            else:
                allowed_worktrees = verified_worktrees(REPOSITORY)
                if any(
                    row.get("forge_root") not in allowed_worktrees or row.get("worktree") not in allowed_worktrees
                    for row in stored.get("selected", [])
                ):
                    raise Refusal("unverified_worktree_membership")
                summary, ledger = inspect_sources(stored)
                suffix = "-corrected" if corrected else ""
                private_write(directory / f"sources{suffix}-private.json", ledger)
                private_write(directory / f"sources{suffix}-summary.json", summary)
        print(json.dumps({"private_directory": str(directory), **summary}, indent=2))
    except (Refusal, OSError, subprocess.SubprocessError):
        parser.error(sys_exception_reason())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
