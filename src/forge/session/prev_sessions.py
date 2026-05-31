"""Path layout for resume/fork context files (prev_sessions).

Centralizes the on-disk layout so assemble_transfer_context, SessionManager, fork paths,
and GC stay in sync.

Layout::

    <forge_root>/.forge/prev_sessions/
    +-- <parent>/
        +-- generated.md          # Strategy output (regeneratable cache)
        +-- children/
            +-- <child>.md        # Per-child authoritative context (durable)

The split exists so that regenerating the parent cache (re-running resume
against the same parent) never disturbs an existing child file. Once
``children/<child>.md`` exists, it is the authoritative context that gets
appended to the child session's system prompt.

Legacy note: pre-0.2.0, this was a single flat
``<forge_root>/.forge/prev_sessions/<parent>.md`` (parent-scoped, overwritten
by every resume/fork). New code never reads or writes the flat layout. GC
treats any remaining flat ``*.md`` files at the top level of
``prev_sessions/`` as orphans (see ``iter_legacy_flat_files``).
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

PREV_SESSIONS_DIR = "prev_sessions"
GENERATED_FILENAME = "generated.md"
CHILDREN_DIR = "children"

# Per-child user-notes overlay. ``children/<child>.notes.md`` is the sole
# user-editable surface; the paired ``children/<child>.md`` snapshot stays a
# pure AI artifact, so regenerating the parent cache never disturbs user notes.
NOTES_SUFFIX = ".notes.md"

# Header-only on purpose: the notes file is appended verbatim to the launch
# system prompt once it has content, so guidance lives in CLI console output,
# not in the file. ``notes_has_user_content`` treats the bare header as empty.
NOTES_TEMPLATE = "## User Notes\n\n"


def prev_sessions_root(forge_root: Path) -> Path:
    return forge_root / ".forge" / PREV_SESSIONS_DIR


def parent_dir(forge_root: Path, parent_name: str) -> Path:
    return prev_sessions_root(forge_root) / parent_name


def generated_path(forge_root: Path, parent_name: str) -> Path:
    return parent_dir(forge_root, parent_name) / GENERATED_FILENAME


def children_dir(forge_root: Path, parent_name: str) -> Path:
    return parent_dir(forge_root, parent_name) / CHILDREN_DIR


def child_path(forge_root: Path, parent_name: str, child_name: str) -> Path:
    return children_dir(forge_root, parent_name) / f"{child_name}.md"


def generated_path_rel(parent_name: str) -> str:
    """Return the forge-root-relative path to ``generated.md``."""
    return f".forge/{PREV_SESSIONS_DIR}/{parent_name}/{GENERATED_FILENAME}"


def child_path_rel(parent_name: str, child_name: str) -> str:
    """Return the forge-root-relative path to ``children/<child>.md``."""
    return f".forge/{PREV_SESSIONS_DIR}/{parent_name}/{CHILDREN_DIR}/{child_name}.md"


def child_notes_path(forge_root: Path, parent_name: str, child_name: str) -> Path:
    return children_dir(forge_root, parent_name) / f"{child_name}{NOTES_SUFFIX}"


def child_notes_path_rel(parent_name: str, child_name: str) -> str:
    """Return the forge-root-relative path to ``children/<child>.notes.md``."""
    return f".forge/{PREV_SESSIONS_DIR}/{parent_name}/{CHILDREN_DIR}/{child_name}{NOTES_SUFFIX}"


def snapshot_for_notes(notes_path: Path) -> Path:
    """Return the AI snapshot ``<child>.md`` paired with a ``<child>.notes.md`` overlay."""
    return notes_path.with_name(notes_path.name[: -len(NOTES_SUFFIX)] + ".md")


def notes_for_snapshot(snapshot_path: Path) -> Path:
    """Return the ``<child>.notes.md`` overlay paired with a snapshot ``<child>.md``."""
    return snapshot_path.with_name(snapshot_path.stem + NOTES_SUFFIX)


def ensure_notes_overlay(snapshot_path: Path) -> Path:
    """Return the notes overlay paired with ``snapshot_path``, creating a template if absent.

    Path-based entry point so launch paths (which already hold the snapshot
    path, including worktree-fork output roots) can resolve the overlay without
    recomputing the prev_sessions root. Idempotent: existing notes are left
    untouched.
    """
    target = notes_for_snapshot(snapshot_path)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(NOTES_TEMPLATE, encoding="utf-8")
    return target


def ensure_notes_template(forge_root: Path, parent_name: str, child_name: str) -> Path:
    """Return the per-child notes overlay path, creating a template if absent.

    Name-based convenience over ``ensure_notes_overlay`` for callers that hold
    ``(forge_root, parent, child)`` (e.g. ``forge transfer edit``). The overlay
    (``children/<child>.notes.md``) is the only user-editable transfer surface.
    """
    return ensure_notes_overlay(child_path(forge_root, parent_name, child_name))


def notes_has_user_content(path: Path) -> bool:
    """Return True if a notes overlay has user content beyond the template scaffold.

    Strips HTML comments, the ``## User Notes`` header, and blank lines, so an
    untouched template contributes nothing to the launch/compose context.
    """
    if not path.is_file():
        return False
    text = re.sub(r"<!--.*?-->", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return any(line.strip() and line.strip() != "## User Notes" for line in text.splitlines())


def compose_child_context(forge_root: Path, parent_name: str, child_name: str) -> str:
    """Compose the child's transfer view: AI snapshot + user-notes overlay.

    Approximates the launch context -- the snapshot, plus the notes overlay only
    when it has user content. Not byte-exact: the launcher (``_combine_prompt_files``)
    additionally adds ``<!-- Source: … -->`` markers and may prepend a configured
    prompt file. Raises ``FileNotFoundError`` if the snapshot is missing.
    """
    snapshot = child_path(forge_root, parent_name, child_name)
    if not snapshot.is_file():
        raise FileNotFoundError(f"No child snapshot at {snapshot}")

    parts = [snapshot.read_text(encoding="utf-8").rstrip()]
    notes = child_notes_path(forge_root, parent_name, child_name)
    if notes_has_user_content(notes):
        parts.append(notes.read_text(encoding="utf-8").rstrip())
    return "\n\n".join(parts) + "\n"


def ensure_child(forge_root: Path, parent_name: str, child_name: str) -> Path:
    """Create ``children/<child>.md`` as a copy of ``generated.md`` if absent.

    Idempotent: if the child file already exists (user has curated it, or it
    was created by a previous resume), leave it alone. This is the durability
    guarantee: once a child file exists, regenerating the parent cache does
    not affect it.

    Raises ``FileNotFoundError`` if neither the child file nor the parent
    cache exists -- the caller is responsible for running ``assemble_transfer_context``
    first.
    """
    target = child_path(forge_root, parent_name, child_name)
    if target.exists():
        return target

    source = generated_path(forge_root, parent_name)
    if not source.is_file():
        raise FileNotFoundError(
            f"Cannot copy parent cache to child: {source} does not exist. " "Run assemble_transfer_context() first."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def iter_parents(forge_root: Path) -> Iterator[Path]:
    """Yield each ``<parent>/`` directory under ``prev_sessions/``.

    Skips legacy flat ``.md`` files at the top level (see
    ``iter_legacy_flat_files``).
    """
    root = prev_sessions_root(forge_root)
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_dir():
            yield entry


def iter_children(forge_root: Path, parent_name: str) -> Iterator[Path]:
    """Yield each AI snapshot ``<child>.md`` under ``<parent>/children/``.

    Excludes the per-child user-notes overlay (``<child>.notes.md``); use
    ``iter_child_notes`` for those. The split matters for GC: a notes file's
    liveness is tied to its snapshot, never tracked independently (a notes file
    is never referenced by ``Derivation.context_file``).
    """
    target = children_dir(forge_root, parent_name)
    if not target.is_dir():
        return
    for entry in target.iterdir():
        if entry.is_file() and entry.suffix == ".md" and not entry.name.endswith(NOTES_SUFFIX):
            yield entry


def iter_child_notes(forge_root: Path, parent_name: str) -> Iterator[Path]:
    """Yield each per-child user-notes overlay ``<child>.notes.md``."""
    target = children_dir(forge_root, parent_name)
    if not target.is_dir():
        return
    for entry in target.iterdir():
        if entry.is_file() and entry.name.endswith(NOTES_SUFFIX):
            yield entry


def iter_legacy_flat_files(forge_root: Path) -> Iterator[Path]:
    """Yield top-level ``<parent>.md`` files (legacy pre-0.2.0 layout).

    These are orphan candidates for GC; new code never writes here.
    """
    root = prev_sessions_root(forge_root)
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_file() and entry.suffix == ".md":
            yield entry
