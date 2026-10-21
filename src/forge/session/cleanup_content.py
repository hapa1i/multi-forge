"""Exact, retryable inventories for Forge-owned session content.

The caller owns dependency admission and the session publication/writer fence.
Neither planning nor applying reads native stores or removes session manifests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

import dacite

from forge.core.paths import get_forge_home
from forge.core.runtime.codex_review_source import directory_fd
from forge.core.state import StateError
from forge.search.cleanup import (
    indexed_transcript_paths,
    remove_transcript_paths,
    search_store_paths,
)
from forge.search.store import SearchDocumentStore
from forge.session.models import SessionState
from forge.session.prev_sessions import child_notes_path, child_path


@dataclass(frozen=True)
class ContentFile:
    """One regular file pinned to its location, inode and captured bytes."""

    path: str
    boundary: str
    category: str
    device: int
    inode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class ContentDirectory:
    """A directory to remove only after its exact inventoried contents are gone."""

    path: str
    boundary: str
    device: int
    inode: int


@dataclass(frozen=True)
class ForgeContentPlan:
    """Serializable content inventory; exclusions never grant deletion authority."""

    schema_version: int
    forge_root: str
    session_name: str
    files: tuple[ContentFile, ...] = ()
    directories: tuple[ContentDirectory, ...] = ()
    absent_paths: tuple[str, ...] = ()
    search_keys: tuple[str, ...] = ()
    reviewer_homes: tuple[str, ...] = ()
    refusals: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the durable retry representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ForgeContentPlan:
        """Read an exact supported inventory without accepting unknown fields."""
        plan = dacite.from_dict(cls, value, config=dacite.Config(strict=True, cast=[tuple]))
        if plan.schema_version != 1:
            raise ValueError("Unsupported Forge content cleanup inventory; upgrade Forge before retrying")
        _validate_inventory_shape(plan)
        return plan


@dataclass
class _Inventory:
    files: dict[str, ContentFile] = field(default_factory=dict)
    directories: dict[str, ContentDirectory] = field(default_factory=dict)
    refusals: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reviewer_homes: list[str] = field(default_factory=list)
    absent_paths: set[str] = field(default_factory=set)

    def add_file(self, path: Path, boundary: Path, category: str) -> None:
        try:
            captured = _capture_file(path, boundary, category)
            if captured is not None:
                self.files[str(path)] = captured
                if path.name.endswith(".notes.md"):
                    self.notes.append(f"Remove user-authored transfer notes: {path}")
            else:
                self.absent_paths.add(str(path))
        except (OSError, ValueError) as error:
            self.refusals.append(f"Cannot inventory {path}: {error}")

    def add_tree(self, path: Path, boundary: Path, category: str) -> None:
        try:
            _contained(path, boundary)
            with directory_fd(path.parent) as parent:
                try:
                    identity = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    self.absent_paths.add(str(path))
                    return
                if not stat.S_ISDIR(identity.st_mode):
                    raise ValueError("owned content tree is not a regular directory")
            with directory_fd(path) as descriptor:
                children = sorted(os.listdir(descriptor))
            self.directories[str(path)] = ContentDirectory(str(path), str(boundary), identity.st_dev, identity.st_ino)
            for name in children:
                child = path / name
                if child.is_dir() and not child.is_symlink():
                    self.add_tree(child, boundary, category)
                else:
                    self.add_file(child, boundary, category)
        except FileNotFoundError:
            self.absent_paths.add(str(path))
            return
        except (OSError, ValueError) as error:
            self.refusals.append(f"Cannot inventory {path}: {error}")


def plan_forge_content(state: SessionState, *, forge_root: Path, forge_home: Path | None = None) -> ForgeContentPlan:
    """Read owned paths without creating locks, directories, or derived state."""
    root = forge_root.expanduser().resolve()
    home = (forge_home or get_forge_home()).expanduser().resolve()
    _safe_name(state.name)
    inventory = _Inventory()
    artifacts = root / ".forge" / "artifacts" / state.name
    inventory.add_tree(artifacts, root, "artifacts")
    inventory.add_tree(root / ".forge" / "prev_sessions" / state.name, root, "transfer")
    _add_child_context(state, root, inventory)
    session_ids = _session_ids(state)
    _add_queue_markers(state, root, home, session_ids, inventory)
    _add_qa_copies(home, session_ids, inventory)
    _add_reviewer_copies(home, session_ids, inventory)
    search_keys: tuple[str, ...] = ()
    try:
        for path in search_store_paths(root):
            _check_regular_location(path, root)
        keys = indexed_transcript_paths(root)
        metadata_keys = {
            doc.transcript_path
            for doc in SearchDocumentStore(root).read()
            if doc.session_name == state.name and doc.session_id in session_ids
        }
        recorded_paths = _recorded_transcript_paths(state, root)
        for key in sorted(metadata_keys):
            if not _under(Path(key), artifacts) and key not in recorded_paths:
                inventory.refusals.append(f"Search transcript has no recorded session ownership: {key}")
        search_keys = tuple(sorted({key for key in keys if _under(Path(key), artifacts)} | metadata_keys))
    except Exception as error:
        inventory.refusals.append(f"Cannot inventory search content: {error}")
    plan = ForgeContentPlan(
        schema_version=1,
        forge_root=str(root),
        session_name=state.name,
        files=tuple(inventory.files[key] for key in sorted(inventory.files)),
        directories=tuple(inventory.directories[key] for key in sorted(inventory.directories)),
        absent_paths=tuple(sorted(inventory.absent_paths)),
        search_keys=search_keys,
        reviewer_homes=tuple(inventory.reviewer_homes),
        refusals=tuple(inventory.refusals),
        exclusions=tuple(inventory.exclusions),
        notes=tuple(inventory.notes),
    )
    try:
        with forge_content_leases(plan):
            pass
    except (OSError, ValueError) as error:
        plan = replace(plan, refusals=(*plan.refusals, str(error)))
    return plan


def plan_orphan_artifacts(forge_root: Path, session_name: str) -> ForgeContentPlan:
    """Inventory an absent session's artifact tree after independent reference checks."""
    root = forge_root.expanduser().resolve()
    _safe_name(session_name)
    inventory = _Inventory()
    artifacts = root / ".forge" / "artifacts" / session_name
    inventory.add_tree(artifacts, root, "artifacts")
    keys: tuple[str, ...] = ()
    try:
        for path in search_store_paths(root):
            _check_regular_location(path, root)
        keys = tuple(sorted(key for key in indexed_transcript_paths(root) if _under(Path(key), artifacts)))
    except Exception as error:
        inventory.refusals.append(f"Cannot inventory search content: {error}")
    return ForgeContentPlan(
        schema_version=1,
        forge_root=str(root),
        session_name=session_name,
        files=tuple(inventory.files[key] for key in sorted(inventory.files)),
        directories=tuple(inventory.directories[key] for key in sorted(inventory.directories)),
        absent_paths=tuple(sorted(inventory.absent_paths)),
        search_keys=keys,
        refusals=tuple(inventory.refusals),
    )


@contextmanager
def forge_content_leases(plan: ForgeContentPlan) -> Iterator[None]:
    """Probe or hold existing reviewer locks without creating or rewriting files."""
    _validate_inventory_shape(plan)
    with ExitStack() as stack:
        if plan.reviewer_homes:
            from forge.core.reactive.codex_reviewer_home import reviewer_lease

            for home in sorted(plan.reviewer_homes):
                try:
                    stack.enter_context(reviewer_lease(Path(home)))
                except (OSError, ValueError) as error:
                    raise ValueError(f"Cannot acquire cleanup reviewer lease at {home}: {error}") from error
        yield


def apply_forge_content(plan: ForgeContentPlan, *, _reviewer_leases_held: bool = False) -> tuple[str, ...]:
    """Apply a pinned inventory while the caller holds its session writer fence."""
    if plan.refusals:
        raise ValueError("; ".join(plan.refusals))
    removed: list[str] = []
    with nullcontext() if _reviewer_leases_held else forge_content_leases(plan):
        validate_forge_content(plan)
        remove_transcript_paths(Path(plan.forge_root), plan.search_keys)
        for item in plan.files:
            path = Path(item.path)
            try:
                with directory_fd(path.parent) as descriptor:
                    current = _capture_file(path, Path(item.boundary), item.category)
                    if current is None:
                        continue
                    if current != item:
                        raise ValueError(f"Cleanup file changed since preview: {path}")
                    try:
                        os.unlink(path.name, dir_fd=descriptor)
                    except OSError as error:
                        raise type(error)(f"Cannot remove cleanup content {path}: {error}") from error
                    removed.append(item.path)
            except FileNotFoundError:
                continue
        for directory in sorted(
            plan.directories,
            key=lambda entry: len(Path(entry.path).parts),
            reverse=True,
        ):
            path = Path(directory.path)
            try:
                with directory_fd(path.parent) as descriptor:
                    _validate_directory(directory)
                    os.rmdir(path.name, dir_fd=descriptor)
                    removed.append(directory.path)
            except FileNotFoundError:
                continue
    return tuple(removed)


def validate_forge_content(plan: ForgeContentPlan) -> None:
    """Reject changed files or new tree entries before any content is removed."""
    _validate_inventory_shape(plan)
    if plan.refusals:
        raise ValueError("; ".join(plan.refusals))
    for missing in plan.absent_paths:
        path = Path(missing)
        if path.exists() or path.is_symlink():
            raise ValueError(f"New content appeared since cleanup preview: {path}")
    allowed = {item.path for item in plan.files} | {item.path for item in plan.directories}
    for directory in plan.directories:
        try:
            _validate_directory(directory)
            with directory_fd(Path(directory.path)) as descriptor:
                unexpected = [
                    str(Path(directory.path) / name)
                    for name in os.listdir(descriptor)
                    if str(Path(directory.path) / name) not in allowed
                ]
            if unexpected:
                raise ValueError(f"New content appeared since cleanup preview: {', '.join(unexpected)}")
        except FileNotFoundError:
            continue
    for item in plan.files:
        current = _capture_file(Path(item.path), Path(item.boundary), item.category)
        if current is not None and current != item:
            raise ValueError(f"Cleanup file changed since preview: {item.path}")
    for path in search_store_paths(Path(plan.forge_root)):
        _check_regular_location(path, Path(plan.forge_root))
    keys = indexed_transcript_paths(Path(plan.forge_root))
    artifacts = Path(plan.forge_root) / ".forge" / "artifacts" / plan.session_name
    if any(_under(Path(key), artifacts) and key not in plan.search_keys for key in keys):
        raise ValueError("New search content appeared since cleanup preview")


def validate_forge_content_scope(plan: ForgeContentPlan, state: SessionState) -> None:
    """Bind a durable inventory to its session and current global Forge home."""
    _validate_inventory_shape(plan)
    if plan.session_name != state.name or (
        state.forge_root and Path(state.forge_root).resolve() != Path(plan.forge_root)
    ):
        raise ValueError("Forge content inventory differs from its session identity")
    home = get_forge_home().expanduser().resolve()
    child_paths: set[Path] = set()
    derivation = state.confirmed.derivation
    if derivation and derivation.context_file:
        roots = {Path(plan.forge_root)}
        if derivation.parent_forge_root:
            roots.add(Path(derivation.parent_forge_root).resolve())
        stored = Path(derivation.context_file)
        recorded = stored if stored.is_absolute() else Path(plan.forge_root) / stored
        for root in roots:
            if recorded == child_path(root, derivation.parent_session, state.name):
                child_paths.update(
                    (
                        recorded,
                        child_notes_path(root, derivation.parent_session, state.name),
                    )
                )
    for file in plan.files:
        if file.category in {"child-context", "child-notes"}:
            if Path(file.path) not in child_paths:
                raise ValueError("Cleanup child context differs from its recorded derivation")
        elif file.category not in {"artifacts", "transfer"} and Path(file.boundary) != home:
            raise ValueError("Cleanup copy or queue marker is outside the current Forge home")
    for directory in plan.directories:
        if Path(directory.boundary) not in {home, Path(plan.forge_root)}:
            raise ValueError("Cleanup directory is outside its owning Forge root or home")
    if any(Path(reviewer).parent != home / "reviewers" for reviewer in plan.reviewer_homes):
        raise ValueError("Cleanup reviewer home is outside the current Forge home")
    artifacts = Path(plan.forge_root) / ".forge" / "artifacts" / plan.session_name
    external_keys = {key for key in plan.search_keys if not _under(Path(key), artifacts)}
    if external_keys:
        recorded_paths = _recorded_transcript_paths(state, Path(plan.forge_root))
        if external_keys - recorded_paths:
            raise ValueError("Cleanup search keys differ from the session's recorded transcript paths")
        ids = _session_ids(state)
        try:
            documents = SearchDocumentStore(Path(plan.forge_root)).read()
        except StateError as error:
            raise ValueError(f"Cannot verify cleanup search ownership: {error}") from error
        for document in documents:
            if document.transcript_path in external_keys and (
                document.session_name != state.name or document.session_id not in ids
            ):
                raise ValueError(f"Cleanup search ownership changed: {document.transcript_path}")


def _validate_inventory_shape(plan: ForgeContentPlan) -> None:
    if type(plan.schema_version) is not int or plan.schema_version != 1:
        raise ValueError("Unsupported Forge content cleanup inventory")
    root = Path(plan.forge_root)
    _absolute(root)
    _safe_name(plan.session_name)
    paths = [file.path for file in plan.files] + [directory.path for directory in plan.directories]
    if len(paths) != len(set(paths)) or set(paths).intersection(plan.absent_paths):
        raise ValueError("Duplicate or contradictory content paths in cleanup inventory")
    for values in (plan.absent_paths, plan.search_keys, plan.reviewer_homes):
        if len(values) != len(set(values)):
            raise ValueError("Duplicate entries in cleanup inventory")
        for value in values:
            _absolute(Path(value))
    entries: tuple[ContentFile | ContentDirectory, ...] = (*plan.files, *plan.directories)
    for entry in entries:
        path, boundary = Path(entry.path), Path(entry.boundary)
        _contained(path, boundary)
        if type(entry.device) is not int or entry.device < 0 or type(entry.inode) is not int or entry.inode < 0:
            raise ValueError("Malformed cleanup filesystem identity")
        if isinstance(entry, ContentFile):
            if type(entry.size) is not int or entry.size < 0 or not re.fullmatch(r"[0-9a-f]{64}", entry.sha256):
                raise ValueError("Malformed cleanup file fingerprint")
            valid = _owned_file_shape(plan, entry)
        else:
            valid = (
                boundary == root
                and any(
                    path.is_relative_to(root / ".forge" / category / plan.session_name)
                    for category in ("artifacts", "prev_sessions")
                )
            ) or _reviewer_input_shape(plan, path, boundary)
        if not valid:
            raise ValueError(f"Unsupported owned cleanup path: {path}")
    for reviewer in plan.reviewer_homes:
        path = Path(reviewer)
        if path.parent.name != "reviewers" or not (path.name == "codex" or path.name.startswith("codex-api-")):
            raise ValueError("Unsupported reviewer cleanup home")


def _owned_file_shape(plan: ForgeContentPlan, file: ContentFile) -> bool:
    path, boundary, root = Path(file.path), Path(file.boundary), Path(plan.forge_root)
    relative = path.relative_to(boundary).parts
    if file.category in {"artifacts", "transfer"}:
        category = "artifacts" if file.category == "artifacts" else "prev_sessions"
        return boundary == root and path.is_relative_to(root / ".forge" / category / plan.session_name)
    if file.category in {"child-context", "child-notes"}:
        filename = f"{plan.session_name}.md" if file.category == "child-context" else f"{plan.session_name}.notes.md"
        return (
            len(relative) == 5
            and relative[:2] == (".forge", "prev_sessions")
            and relative[3:] == ("children", filename)
        )
    if file.category == "queued-work":
        return relative[:-1] in {("pending-work",), ("pending-work", "failed")} and path.suffix == ".json"
    if file.category == "pending-transcript":
        return relative in {
            ("manual-testing", "qa", ".pending-transcript"),
            ("manual-testing", "walkthrough", ".pending-transcript"),
        }
    if file.category == "manual-testing-transcript":
        return (
            len(relative) == 5
            and relative[0] == "manual-testing"
            and relative[1] in {"qa", "walkthrough"}
            and relative[2] == "runs"
            and relative[4] == "transcript.jsonl"
        )
    return file.category == "reviewer-input" and _reviewer_input_shape(plan, path, boundary)


def _reviewer_input_shape(plan: ForgeContentPlan, path: Path, boundary: Path) -> bool:
    return any(
        Path(home).parent == boundary / "reviewers"
        and any(path.is_relative_to(Path(home) / tree) for tree in ("sessions", "review-index"))
        for home in plan.reviewer_homes
    )


def _absolute(path: Path) -> None:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Expected an absolute path without traversal: {path}")


def _contained(path: Path, boundary: Path) -> None:
    _absolute(path)
    _absolute(boundary)
    if path == boundary or not path.is_relative_to(boundary):
        raise ValueError(f"Path is outside its cleanup boundary: {path}")


def _under(path: Path, root: Path) -> bool:
    return path.is_absolute() and ".." not in path.parts and path.is_relative_to(root)


def _safe_name(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name:
        raise ValueError("Unsafe session name in cleanup inventory")


def _check_regular_location(path: Path, boundary: Path) -> None:
    _contained(path, boundary)
    try:
        with directory_fd(path.parent) as descriptor:
            identity = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
                raise ValueError(f"Content must be a regular file without hard links: {path}")
    except FileNotFoundError:
        return


def _capture_file(path: Path, boundary: Path, category: str) -> ContentFile | None:
    _contained(path, boundary)
    try:
        with directory_fd(path.parent) as descriptor:
            fd = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=descriptor,
            )
            with os.fdopen(fd, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    raise ValueError("content must be a regular file without hard links")
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise ValueError("content changed while creating cleanup inventory")
        return ContentFile(
            str(path),
            str(boundary),
            category,
            before.st_dev,
            before.st_ino,
            before.st_size,
            digest,
        )
    except FileNotFoundError:
        return None


def _validate_directory(item: ContentDirectory) -> None:
    path = Path(item.path)
    _contained(path, Path(item.boundary))
    with directory_fd(path.parent) as descriptor:
        identity = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
        if not stat.S_ISDIR(identity.st_mode) or (identity.st_dev, identity.st_ino) != (
            item.device,
            item.inode,
        ):
            raise ValueError(f"Cleanup directory changed since preview: {path}")


def _session_ids(state: SessionState) -> set[str]:
    ids = [state.confirmed.claude_session_id]
    if state.confirmed.codex:
        ids.append(state.confirmed.codex.thread_id)
    transcripts = state.confirmed.artifacts.get("transcripts", [])
    if isinstance(transcripts, list):
        ids.extend(entry.get("session_id") for entry in transcripts if isinstance(entry, dict))
    return {value for value in ids if isinstance(value, str) and value}


def _recorded_transcript_paths(state: SessionState, root: Path) -> set[str]:
    """Bind legacy search keys to transcript locations in the saved manifest."""
    recorded: list[object] = [state.confirmed.transcript_path]
    if state.confirmed.codex:
        recorded.append(state.confirmed.codex.rollout_path)
    transcripts = state.confirmed.artifacts.get("transcripts", [])
    if isinstance(transcripts, list):
        for entry in transcripts:
            if isinstance(entry, dict):
                recorded.extend((entry.get("copied_path"), entry.get("snapshot_path")))
    paths: set[str] = set()
    for value in recorded:
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser()
        path = path if path.is_absolute() else root / path
        _absolute(path)
        paths.add(str(path))
    return paths


def _add_child_context(state: SessionState, root: Path, inventory: _Inventory) -> None:
    derivation = state.confirmed.derivation
    if derivation is None or not derivation.context_file:
        return
    try:
        _safe_name(derivation.parent_session)
        parent_root = Path(derivation.parent_forge_root).resolve() if derivation.parent_forge_root else root
        stored = Path(derivation.context_file)
        candidates = {child_path(root, derivation.parent_session, state.name)}
        candidates.add(child_path(parent_root, derivation.parent_session, state.name))
        resolved = stored if stored.is_absolute() else root / stored
        if resolved not in candidates:
            inventory.exclusions.append(f"Transfer context has no supported child ownership: {resolved}")
            return
        boundary = next(
            candidate
            for candidate in (root, parent_root)
            if resolved == child_path(candidate, derivation.parent_session, state.name)
        )
        inventory.add_file(resolved, boundary, "child-context")
        inventory.add_file(
            child_notes_path(boundary, derivation.parent_session, state.name),
            boundary,
            "child-notes",
        )
    except (OSError, ValueError) as error:
        inventory.refusals.append(f"Cannot inventory child context: {error}")


def _read_object(path: Path, boundary: Path) -> dict[str, Any]:
    value = json.loads(_read_bytes(path, boundary))
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _read_bytes(path: Path, boundary: Path) -> bytes:
    _contained(path, boundary)
    with directory_fd(path.parent) as descriptor:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, "rb") as stream:
            identity = os.fstat(stream.fileno())
            if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
                raise ValueError("content must be a regular file without hard links")
            return stream.read()


def _add_queue_markers(
    state: SessionState,
    root: Path,
    home: Path,
    session_ids: set[str],
    inventory: _Inventory,
) -> None:
    for queue in (home / "pending-work", home / "pending-work" / "failed"):
        try:
            with directory_fd(queue) as descriptor:
                names = sorted(os.listdir(descriptor))
        except FileNotFoundError:
            continue
        except OSError as error:
            inventory.refusals.append(f"Cannot inventory queued work at {queue}: {error}")
            continue
        for name in names:
            if not name.endswith(".json"):
                continue
            path = queue / name
            try:
                value = _read_object(path, home)
                payload = value.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("queue marker has no payload")
                marker_root = payload.get("forge_root") or payload.get("worktree_path")
                matching_root = isinstance(marker_root, str) and Path(marker_root).resolve() == root
                if not matching_root or payload.get("session_name") != state.name:
                    continue
                if value.get("schema_version") != 1 or (payload.get("session_id") not in session_ids and session_ids):
                    inventory.refusals.append(f"Queued work has unverified schema or session identity: {path}")
                    continue
                inventory.add_file(path, home, "queued-work")
            except (OSError, ValueError) as error:
                inventory.exclusions.append(f"Unattributed queued work retained at {path}: {error}")


def _transcript_identity(path: Path, home: Path, session_ids: set[str], *, codex: bool = False) -> bool:
    found: set[str] = set()
    for line in _read_bytes(path, home).splitlines():
        value = json.loads(line)
        if not isinstance(value, dict):
            return False
        if codex:
            return (
                value.get("type") == "session_meta"
                and isinstance(value.get("payload"), dict)
                and value["payload"].get("id") in session_ids
            )
        identity = value.get("sessionId")
        if identity is not None:
            if not isinstance(identity, str):
                return False
            found.add(identity)
    return bool(found) and found.issubset(session_ids)


def _add_qa_copies(home: Path, session_ids: set[str], inventory: _Inventory) -> None:
    for skill in ("qa", "walkthrough"):
        skill_root = home / "manual-testing" / skill
        marker = skill_root / ".pending-transcript"
        try:
            if marker.exists():
                request = _read_object(marker, home)
                if request.get("session_id") in session_ids:
                    inventory.add_file(marker, home, "pending-transcript")
            runs = skill_root / "runs"
            with directory_fd(runs) as descriptor:
                names = sorted(os.listdir(descriptor))
            for name in names:
                transcript = runs / name / "transcript.jsonl"
                if not transcript.exists():
                    continue
                try:
                    if _transcript_identity(transcript, home, session_ids):
                        inventory.add_file(transcript, home, "manual-testing-transcript")
                    else:
                        inventory.exclusions.append(f"Unattributed QA/walkthrough transcript retained: {transcript}")
                except (OSError, ValueError) as error:
                    inventory.exclusions.append(
                        f"Unattributed QA/walkthrough transcript retained: {transcript}: {error}"
                    )
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as error:
            inventory.exclusions.append(f"QA/walkthrough copies not inventoried at {skill_root}: {error}")


def _add_reviewer_copies(home: Path, session_ids: set[str], inventory: _Inventory) -> None:
    from forge.core.reactive.codex_reviewer_home import INPUT_MARKER, MARKER

    parent = home / "reviewers"
    try:
        with directory_fd(parent) as descriptor:
            homes = [
                parent / name
                for name in sorted(os.listdir(descriptor))
                if name == "codex" or name.startswith("codex-api-")
            ]
    except FileNotFoundError:
        return
    except OSError as error:
        inventory.exclusions.append(f"Reviewer copies not inventoried at {parent}: {error}")
        return
    for reviewer in homes:
        try:
            ownership = _read_object(reviewer / MARKER, home)
            if ownership.get("version") != 1:
                raise ValueError("unrecognized reviewer ownership")
            sessions = reviewer / "sessions"
            if not sessions.exists():
                continue
            candidates = _Inventory()
            candidates.add_tree(sessions, home, "reviewer-input")
            if candidates.refusals:
                raise ValueError("; ".join(candidates.refusals))
            transcripts = [
                Path(item.path) for item in candidates.files.values() if Path(item.path).name != INPUT_MARKER
            ]
            if not transcripts:
                continue
            owned = [path for path in transcripts if _transcript_identity(path, home, session_ids, codex=True)]
            if not owned:
                continue
            if len(owned) != len(transcripts):
                raise ValueError("reviewer inputs/index also contain another session; shared copies are retained")
            for tree in (sessions, reviewer / "review-index"):
                marker = tree / INPUT_MARKER
                if tree.exists():
                    if _read_bytes(marker, home) != b"1\n":
                        raise ValueError("unrecognized reviewer input ownership")
                    inventory.add_tree(tree, home, "reviewer-input")
            inventory.reviewer_homes.append(str(reviewer))
        except (OSError, ValueError) as error:
            inventory.exclusions.append(f"Reviewer copies retained at {reviewer}: {error}")
