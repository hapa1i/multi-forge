"""Bounded raw worktree snapshots for an already-applied Codex turn.

Git only enumerates paths and repository identity. We never stage into an index
or invoke clean/process filters, hooks, external diff, textconv, or fsmonitor.
Immutable private blobs preserve dirty starting contents without touching the
user's index or object store. Unsupported changes remain explicit omissions.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import selectors
import stat
import subprocess
import time
from pathlib import Path
from typing import Any

from forge.core.state import atomic_write_bytes, file_lock_for_target

MAX_FILES = 6000
MAX_FILE_BYTES = 1_000_000
MAX_SNAPSHOT_BYTES = 64_000_000
MAX_MANIFEST_BYTES = 4_000_000
MAX_STORAGE_BYTES = 200_000_000
MAX_EVIDENCE_BYTES = 24_000
CAPTURE_SECONDS = 7.0


def digest(value: object) -> str:
    """Hash a canonical JSON identity, including omissions and metadata."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def capture(root: Path, storage: Path, *, deadline: float) -> dict[str, Any]:
    """Persist a bounded immutable snapshot; return only its small reference."""
    expires = min(deadline, time.monotonic() + CAPTURE_SECONDS)
    root = root.resolve(strict=True)
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    if storage.is_symlink():
        raise ValueError("Unsafe review evidence storage")
    with file_lock_for_target(target_path=storage / "capture", timeout_s=1):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_OPTIONAL_LOCKS="0",
        )

        def git(*args: str) -> bytes:
            left = expires - time.monotonic()
            if left <= 0:
                raise TimeoutError("Turn evidence capture exceeded its deadline")
            return _git_output(root, env, args, expires)

        top = Path(os.fsdecode(git("rev-parse", "--show-toplevel")).strip()).resolve()
        if top != root:
            raise ValueError("Stop evidence requires the executor worktree root")
        git_dir = Path(os.fsdecode(git("rev-parse", "--absolute-git-dir")).strip()).resolve()
        head = git("rev-parse", "HEAD").decode().strip()
        # Index stat-cache refreshes do not change staged content. Compare the
        # semantic entries (mode, object, stage, path), never raw index bytes.
        index_entries = git("ls-files", "--stage", "-z")
        index_digest = hashlib.sha256(index_entries).hexdigest()
        staged = index_entries.split(b"\0")
        tracked: dict[str, str] = {}
        omissions: list[str] = []
        for entry in staged:
            if not entry:
                continue
            meta, raw_name = entry.split(b"\t", 1)
            mode, _, stage = meta.decode().split()
            tracked_path = os.fsdecode(raw_name)
            if stage != "0":
                omissions.append("unmerged_index")
            tracked[tracked_path] = mode
        untracked = [os.fsdecode(p) for p in git("ls-files", "--others", "--exclude-standard", "-z").split(b"\0") if p]
        paths = sorted(set(tracked) | set(untracked))
        # Only Forge-owned root state is excluded; ordinary dirty project files remain evidence.
        paths = [p for p in paths if p.split("/", 1)[0] != ".forge"]
        if len(paths) > MAX_FILES:
            omissions.append("file_count_limit")
            paths = paths[:MAX_FILES]
        existing = list(storage.iterdir())
        usage = sum(p.stat().st_size for p in existing if p.is_file() and not p.is_symlink())
        if usage > MAX_STORAGE_BYTES:
            raise ValueError("Review evidence storage limit reached")
        files: dict[str, dict[str, Any]] = {}
        total = 0
        for name in paths:
            if time.monotonic() >= expires:
                omissions.append("capture_deadline")
                break
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe repository path")
            path = root / relative
            if any(p.is_symlink() for p in path.parents if p != root and p.is_relative_to(root)):
                files[name] = {"unsupported": "symlink_parent"}
                continue
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue  # A pre-existing deletion is part of the baseline.
            item: dict[str, Any] = {
                "mode": stat.S_IMODE(info.st_mode),
                "size": info.st_size,
            }
            if stat.S_ISLNK(info.st_mode):
                item.update(unsupported="symlink", target=os.readlink(path))
            elif tracked.get(name) == "160000" or not stat.S_ISREG(info.st_mode):
                item.update(unsupported="submodule_or_special_file", mtime_ns=info.st_mtime_ns)
            elif info.st_size > MAX_FILE_BYTES or total + info.st_size > MAX_SNAPSHOT_BYTES:
                item.update(unsupported="byte_limit", mtime_ns=info.st_mtime_ns)
            else:
                data = _read_regular(path, MAX_FILE_BYTES)
                after = path.stat(follow_symlinks=False)
                if (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ):
                    omissions.append("concurrent_capture_change")
                total += len(data)
                sha = hashlib.sha256(data).hexdigest()
                item["digest"] = sha
                try:
                    data.decode("utf-8")
                    if b"\0" in data:
                        item["unsupported"] = "binary"
                except UnicodeError:
                    item["unsupported"] = "binary"
                blob = storage / (sha + ".blob")
                if not blob.exists():
                    if usage + len(data) > MAX_STORAGE_BYTES:
                        raise ValueError("Review evidence storage limit reached")
                    atomic_write_bytes(blob, data)
                    blob.chmod(0o600)
                    usage += len(data)
            files[name] = item
        if git("rev-parse", "HEAD").decode().strip() != head:
            omissions.append("head_changed_during_capture")
        latest_index = hashlib.sha256(git("ls-files", "--stage", "-z")).hexdigest()
        if index_digest != latest_index:
            omissions.append("index_changed_during_capture")
        snapshot = {
            "schema": 1,
            "root": str(root),
            "git_dir": str(git_dir),
            "head": head,
            "index_digest": index_digest,
            "files": files,
            "omissions": sorted(set(omissions)),
        }
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise ValueError("Review snapshot manifest exceeds its byte limit")
        sha = hashlib.sha256(encoded).hexdigest()
        atomic_write_bytes(storage / (sha + ".snapshot"), encoded)
        (storage / (sha + ".snapshot")).chmod(0o600)
        return {
            "digest": sha,
            "root": str(root),
            "files": len(files),
            "omissions": snapshot["omissions"],
        }


def load(storage: Path, reference: dict[str, Any]) -> dict[str, Any]:
    """Read one immutable snapshot, refusing missing/corrupt content."""
    sha = reference.get("digest")
    _check_digest(sha)
    assert isinstance(sha, str)
    data = _read_regular(storage / (sha + ".snapshot"), MAX_MANIFEST_BYTES)
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError("Review snapshot digest changed")
    snapshot = json.loads(data)
    if snapshot.get("schema") != 1 or snapshot.get("root") != reference.get("root"):
        raise ValueError("Review snapshot identity changed")
    return snapshot


def compare(
    storage: Path,
    before: dict[str, Any],
    after: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe net changes and observed action outcomes without truncating a clean verdict."""
    old, new = load(storage, before), load(storage, after)
    omissions = list(old["omissions"]) + list(new["omissions"])
    if any(old[k] != new[k] for k in ("root", "git_dir", "head", "index_digest")):
        omissions.append("repository_identity_or_index_changed")
    changes = []
    for path in sorted(set(old["files"]) | set(new["files"])):
        left, right = old["files"].get(path), new["files"].get(path)
        if left == right:
            continue
        change: dict[str, Any] = {"path": path, "before": left, "after": right}
        if any(item and item.get("unsupported") for item in (left, right)):
            omissions.append("unsupported_change:" + path)
        else:
            texts = []
            for item in (left, right):
                if item:
                    _check_digest(item.get("digest"))
                    data = _read_regular(storage / (item["digest"] + ".blob"), MAX_FILE_BYTES)
                    if hashlib.sha256(data).hexdigest() != item["digest"]:
                        raise ValueError("Review baseline content changed")
                    texts.append(data.decode("utf-8"))
                else:
                    texts.append("")
            if sum(len(text.encode()) for text in texts) > 256_000 or sum(text.count("\n") for text in texts) > 8_000:
                omissions.append("diff_input_limit:" + path)
                changes.append(change)
                continue
            change["diff"] = "".join(
                (line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
                for line in difflib.unified_diff(
                    texts[0].splitlines(keepends=True),
                    texts[1].splitlines(keepends=True),
                    fromfile=path,
                    tofile=path,
                )
            )
            change["kind"] = "add" if left is None else "delete" if right is None else "modify"
        changes.append(change)
    deleted = {c["before"].get("digest"): c["path"] for c in changes if c.get("kind") == "delete"}
    for change in changes:
        if change.get("kind") == "add" and change["after"].get("digest") in deleted:
            change["renamed_from"] = deleted[change["after"]["digest"]]
    denied = {(row.get("turn_id"), row["id"]) for row in actions if row.get("phase") == "denied"}
    # A denied action has no mutation or PostToolUse to cover. The checkpoint
    # writer removes its request; callers with paired rows exclude them here too.
    actions = [row for row in actions if (row.get("turn_id"), row["id"]) not in denied]
    requests = {(row.get("turn_id"), row["id"]) for row in actions if row.get("phase") == "request"}
    outcomes = {(row.get("turn_id"), row["id"]) for row in actions if row.get("phase") == "outcome"}
    if requests != outcomes:
        omissions.append("missing_tool_event")
    if changes and not actions:
        omissions.append("changes_without_observed_actions")
    for action in actions:
        for value in action.get("paths", []):
            # Native apply_patch may spell in-repository paths absolutely. Keep
            # earlier turn records usable without rewriting their provenance.
            path = Path(value)
            if path.is_absolute():
                try:
                    path = path.relative_to(old["root"])
                except ValueError:
                    omissions.append("tool_path_outside_snapshot")
                    continue
            if path.as_posix() not in old["files"] and path.as_posix() not in new["files"]:
                omissions.append("tool_path_outside_snapshot")
        if action.get("coverage_issue"):
            omissions.append(action["coverage_issue"])
    evidence = {
        "representation": "raw working bytes; executable Git filters are not run",
        "scope": "Repository delta and observed tools only; ignored/external effects and author attribution are unverified.",
        "before": before["digest"],
        "after": after["digest"],
        "changes": changes,
        "actions": actions,
        "omissions": sorted(set(omissions)),
        "complete": not omissions,
    }
    encoded = json.dumps(evidence, sort_keys=True).encode()
    if len(encoded) > MAX_EVIDENCE_BYTES:
        return {
            "complete": False,
            "omissions": ["review_prompt_byte_limit"],
            "changes_count": len(changes),
            "before": before["digest"],
            "after": after["digest"],
            "actions_count": len(actions),
        }
    return evidence


def rebase_pending(
    storage: Path,
    baseline: dict[str, Any],
    observed: dict[str, Any],
    current: dict[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Carry observed changes without importing edits made between observation and the next prompt.

    A pending path changed outside that interval is ambiguous. Its old scope
    remains unreviewed, while the new prompt starts from its current contents.
    HEAD and index metadata belong to the new prompt, including intervening commits.
    """
    before, end, start = (load(storage, ref) for ref in (baseline, observed, current))
    omissions = list(start["omissions"]) + list(before["omissions"]) + list(end["omissions"])
    if any(before[k] != end[k] for k in ("root", "git_dir", "head", "index_digest")):
        omissions.append("repository_identity_or_index_changed")
    result = dict(start, files=dict(start["files"]), omissions=sorted(set(omissions)))
    unattributed = [
        path
        for path in sorted(set(end["files"]) | set(start["files"]))
        if end["files"].get(path) != start["files"].get(path)
    ]
    conflicts = []
    for path in set(before["files"]) | set(end["files"]):
        left, right = before["files"].get(path), end["files"].get(path)
        if left == right:
            continue
        if start["files"].get(path) != right:
            conflicts.append(path)
        elif left is None:
            result["files"].pop(path, None)
        else:
            result["files"][path] = left
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(encoded).hexdigest()
    atomic_write_bytes(storage / (sha + ".snapshot"), encoded)
    (storage / (sha + ".snapshot")).chmod(0o600)
    reference = dict(current, digest=sha, files=len(result["files"]), omissions=result["omissions"])
    return reference, unattributed, sorted(conflicts)


def prune(storage: Path, references: list[dict[str, Any]]) -> None:
    """Keep only checkpoint-owned snapshots and their blobs, under the capture lock."""
    if not storage.exists():
        return
    with file_lock_for_target(target_path=storage / "capture", timeout_s=1):
        keep = set()
        for reference in references:
            snapshot = load(storage, reference)
            keep.add(reference["digest"] + ".snapshot")
            keep.update(item["digest"] + ".blob" for item in snapshot["files"].values() if "digest" in item)
        for path in storage.iterdir():
            if path.suffix in {".snapshot", ".blob"} and path.name not in keep:
                _check_digest(path.stem)
                if path.is_file() and not path.is_symlink():
                    path.unlink()


def _check_digest(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid review evidence digest")


def _read_regular(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("Evidence input is not a bounded regular file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Evidence input exceeded its byte limit")
        return data


def _git_output(root: Path, env: dict[str, str], args: tuple[str, ...], expires: float) -> bytes:
    # Read incrementally: an adversarial index/path list must not allocate an
    # unbounded subprocess buffer before the snapshot's file limit is applied.
    with subprocess.Popen(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=" + os.devnull,
            *args,
        ],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as child:
        assert child.stdout is not None
        output = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                while True:
                    left = expires - time.monotonic()
                    if left <= 0 or not selector.select(left):
                        raise TimeoutError("Git evidence enumeration exceeded its deadline")
                    chunk = os.read(child.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > MAX_MANIFEST_BYTES:
                        raise ValueError("Git evidence enumeration exceeded its byte limit")
            if child.wait(timeout=max(0.001, expires - time.monotonic())):
                raise ValueError("Git evidence enumeration failed")
            return bytes(output)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
