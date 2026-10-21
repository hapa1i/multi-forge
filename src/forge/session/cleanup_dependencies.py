"""Read-only dependency discovery for session content removal."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

from forge.core.runtime.codex_review_source import directory_fd, read_regular
from forge.install.project_registry import ProjectRegistryStore
from forge.install.tracking import TrackingStore

from .claude.paths import resolve_claude_project_root
from .exceptions import ForgeSessionError
from .identity import session_name_from_key
from .index import IndexStore
from .models import SessionIndexEntry, SessionState
from .store import SessionStore, is_session_shell


def session_entries(index: IndexStore) -> list[tuple[str, SessionIndexEntry]]:
    """Read all indexed identities without repairing missing manifests."""
    return [(session_name_from_key(key), entry) for key, entry in index.read().sessions.items()]


def discover_session_states(
    index: IndexStore, root: str, *, allow_missing: tuple[str, str] | None = None
) -> list[tuple[str, str, SessionState]]:
    """Read indexed and registered-project orphan manifests, refusing unreadable state."""
    entries = session_entries(index)
    roots = {
        str(Path(root).resolve()),
        *(str(Path(entry.root).resolve()) for _, entry in entries),
    }
    roots.update(project.canonical_path for project in ProjectRegistryStore().read_strict().projects)
    roots.update(
        installation.project_path
        for installation in TrackingStore().read().installations.values()
        if installation.project_path
    )
    indexed = {(str(Path(entry.root).resolve()), name) for name, entry in entries}
    identities = set(indexed)
    for project in roots:
        directory = Path(project) / ".forge" / "sessions"
        try:
            with directory_fd(directory) as descriptor:
                for name in os.listdir(descriptor):
                    metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    # Sessions are directories. Authority locks and OS metadata such as
                    # .DS_Store are regular files that cannot hold a manifest.
                    if stat.S_ISREG(metadata.st_mode):
                        continue
                    if not stat.S_ISDIR(metadata.st_mode):
                        raise ForgeSessionError(f"Cannot verify unexpected session-store entry: {directory / name}")
                    identities.add((str(Path(project).resolve()), name))
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ForgeSessionError(f"Cannot verify session dependencies at {directory}: {error}") from error
    states = []
    for project, name in sorted(identities):
        store = SessionStore(project, name)
        try:
            before = manifest_digest(store)
            state = store.read()
            if manifest_digest(store) != before:
                raise ValueError("manifest changed during dependency discovery")
        except FileNotFoundError as error:
            if (project, name) == allow_missing:
                continue
            # An unindexed shell left by a lock racing deletion reserves nothing. Apply
            # repeats this scan under the index lock, where creation cannot be
            # mid-publication. Indexed rows without manifests still need repair.
            try:
                if (project, name) not in indexed and is_session_shell(store.session_dir):
                    continue
            except OSError as shell_error:
                raise ForgeSessionError(
                    f"Cannot verify dependencies for '{name}' ({project}): {shell_error}"
                ) from shell_error
            raise ForgeSessionError(
                f"Cannot verify dependencies for '{name}' ({project}): missing manifest; "
                "inspect 'forge session repair' and 'forge session list --scope all' first"
            ) from error
        except (OSError, ValueError) as error:
            raise ForgeSessionError(f"Cannot verify dependencies for '{name}' ({project}): {error}") from error
        states.append((project, name, state))
    return states


def manifest_digest(store: SessionStore) -> str:
    """Fingerprint a bounded regular manifest without following any symlink."""
    return hashlib.sha256(read_regular(store.manifest_path, limit=8 * 1024 * 1024)).hexdigest()


def find_cleanup_dependencies(
    index: IndexStore,
    state: SessionState,
    *,
    forge_root: str,
    native_ids: set[str] | None = None,
    content_paths: tuple[str, ...] = (),
    allow_missing_target: bool = False,
) -> tuple[str, ...]:
    """Name every known session that reads the target's identity or owned content."""
    root = Path(forge_root).resolve()
    owned = (
        root / ".forge" / "sessions" / state.name,
        root / ".forge" / "artifacts" / state.name,
        root / ".forge" / "prev_sessions" / state.name,
    )
    selected_files = {Path(path).resolve() for path in content_paths}
    ids = set(native_ids or ())
    if state.confirmed.claude_session_id:
        ids.add(state.confirmed.claude_session_id)
    if state.confirmed.codex and state.confirmed.codex.thread_id:
        ids.add(state.confirmed.codex.thread_id)
    for key, value in _strings(asdict(state.confirmed)):
        if key in {"session_id", "rewind_relocated_session_id"}:
            ids.add(value)
    ids = {_normalized_native_id(value) for value in ids}
    entries = session_entries(index)
    dependencies = []
    for other_root, name, other in discover_session_states(
        index,
        forge_root,
        allow_missing=(str(root), state.name) if allow_missing_target else None,
    ):
        if (Path(other_root), name) == (root, state.name):
            continue
        reasons: set[str] = set()
        derivation = other.confirmed.derivation
        parent_roots = {Path((derivation.parent_forge_root if derivation else None) or other_root).resolve()}
        ambiguous_parent = False
        if derivation is None and other.parent_session:
            parent_roots, ambiguous_parent = _legacy_parent_roots(other, other_root, entries)
        if root in parent_roots and (
            other.parent_session == state.name
            or (
                derivation is not None and (derivation.parent_session == state.name or state.name in derivation.lineage)
            )
        ):
            reasons.add("ambiguous legacy parent/lineage" if ambiguous_parent else "parent/lineage")
        raw = asdict(other)
        prompt = other.intent.system_prompt
        references = [prompt.file] if prompt and prompt.file else []
        if prompt and prompt.file:
            # Prompt resolution runs before launch against the caller's CWD.
            # Also protect resumes invoked from either recorded launch root.
            prompt_roots = {Path.cwd()}
            if other.worktree:
                prompt_roots.add(Path(other.worktree.path))
            if other.confirmed.claude_project_root:
                prompt_roots.add(Path(other.confirmed.claude_project_root))
            references.extend(str(base / Path(prompt.file).expanduser()) for base in prompt_roots)
        for key, value in _strings(raw):
            if _normalized_native_id(value) in ids and key in {
                "claude_session_id",
                "thread_id",
                "resume_id",
                "session_id",
                "relocated_parent_session_id",
                "rewind_relocated_session_id",
            }:
                # Relocation carries a borrowed UUID into a separate Claude
                # project namespace; it does not make the source own the copy.
                codex_id = state.confirmed.codex.thread_id if state.confirmed.codex else None
                other_cwd = other.confirmed.claude_project_root or resolve_claude_project_root(other)
                target_cwd = state.confirmed.claude_project_root or resolve_claude_project_root(state)
                if (codex_id and _normalized_native_id(value) == _normalized_native_id(codex_id)) or (
                    Path(other_cwd).resolve() == Path(target_cwd).resolve()
                ):
                    reasons.add("native conversation")
            if key.endswith(("_path", "_file", "_transcript")) or key in {
                "source_path",
                "snapshot_path",
                "copied_path",
                "rollout_path",
            }:
                references.append(value)
        for value in references:
            candidate = Path(value).expanduser()
            for base in {Path(other_root), *parent_roots}:
                resolved = (candidate if candidate.is_absolute() else base / candidate).resolve()
                if resolved in selected_files or any(
                    resolved == path or resolved.is_relative_to(path) for path in owned
                ):
                    reasons.add("content reference")
        if _supervisor_references(raw, state.name, root):
            reasons.add("supervisor source")
        if reasons:
            dependencies.append(f"{name} ({other_root}): {', '.join(sorted(reasons))}")
    return tuple(dependencies)


def _legacy_parent_roots(
    state: SessionState, root: str, entries: list[tuple[str, SessionIndexEntry]]
) -> tuple[set[Path], bool]:
    """Mirror inherited-plan membership lookup without its self-healing reads."""
    current = Path(root).resolve()
    parents = [entry for name, entry in entries if name == state.parent_session]
    child = next(
        (entry for name, entry in entries if name == state.name and Path(entry.root).resolve() == current), None
    )
    if child and child.project_root:
        siblings = [
            entry for entry in parents if Path(entry.project_root).resolve() == Path(child.project_root).resolve()
        ]
        matching = [entry for entry in siblings if (entry.relative_path or ".") == (child.relative_path or ".")]
        if len(matching) == 1:
            return {Path(matching[0].root).resolve()}, False
        if len(siblings) == 1:
            return {Path(siblings[0].root).resolve()}, False
        if siblings:
            candidates = {Path(entry.root).resolve() for entry in siblings}
            if state.parent_session and SessionStore(root, state.parent_session).exists():
                candidates.add(current)
            return candidates, True
        return {current}, False
    # Orphan manifests have no reliable project membership. The inherited-plan
    # reader can still consume a same-directory parent; otherwise retain all
    # indexed candidates instead of guessing which project the orphan belongs to.
    if state.parent_session and SessionStore(root, state.parent_session).exists():
        return {current}, False
    return ({Path(entry.root).resolve() for entry in parents} or {current}), bool(parents)


def _normalized_native_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        return value


def _strings(value: Any, parent_key: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str):
                yield str(key), child
            else:
                yield from _strings(child, str(key))
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child, parent_key)
    elif isinstance(value, str):
        yield parent_key, value


def _supervisor_references(value: Any, name: str, root: Path) -> bool:
    if isinstance(value, dict):
        for identity_key, root_key in (
            ("resume_id", "forge_root"),
            ("managed_session", "managed_root"),
        ):
            if value.get(identity_key) == name:
                source_root = value.get(root_key)
                if not source_root or Path(source_root).resolve() == root:
                    return True
        return any(_supervisor_references(child, name, root) for child in value.values())
    if isinstance(value, list):
        return any(_supervisor_references(child, name, root) for child in value)
    return False
