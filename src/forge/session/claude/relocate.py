"""Cross-CWD relocation of Claude session transcripts (native-relocate spike).

Claude Code finds a ``--resume`` target only in the CWD-encoded project dir
(``~/.claude/projects/<encoded-cwd>/<uuid>.jsonl``). To resume a conversation
from a different CWD, its transcript JSONL must first be copied into the
destination CWD's encoded dir. This module performs that copy *content
untouched* -- the signature-safe minimum: signed ``thinking`` /
``redacted_thinking`` blocks and ``tool_result`` content are reproduced
byte-for-byte, so the resumed continuation can revalidate them.

Rewriting absolute paths inside content blocks is a separate, deferred, opt-in
concern; the ``rewrite_paths`` seam exists but is intentionally not implemented.

See ``docs/board/doing/runtime_abstraction/`` (Phase 3 native-relocate spike).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .paths import get_transcript_path

_TRANSCRIPT_MODE = 0o600
_PROJECT_DIR_MODE = 0o700


class RelocateSourceMissingError(FileNotFoundError):
    """Source transcript JSONL not found in the source CWD-encoded dir."""


class RelocateConflictError(FileExistsError):
    """Destination transcript exists with different content and overwrite=False."""


@dataclass(frozen=True)
class RelocateResult:
    """Outcome of a transcript relocation.

    Attributes:
        session_id: Claude session UUID that was relocated.
        source_path: Source transcript (under the source CWD's encoded dir).
        dest_path: Destination transcript (under the dest CWD's encoded dir).
        bytes_copied: Bytes actually written; 0 on an idempotent no-op.
        already_present: Dest already held identical bytes (no write performed).
        paths_rewritten: Whether absolute paths in content blocks were rewritten
            (always False in the spike; the seam is reserved).
    """

    session_id: str
    source_path: Path
    dest_path: Path
    bytes_copied: int
    already_present: bool
    paths_rewritten: bool


def relocate_transcript(
    *,
    session_id: str,
    source_project_root: str,
    dest_project_root: str,
    rewrite_paths: bool = False,
    overwrite: bool = False,
) -> RelocateResult:
    """Copy a Claude session transcript into the destination CWD's encoded dir.

    Content is reproduced byte-for-byte (the signature-safe minimum): signed
    thinking blocks and tool_result content are not modified. The write is
    atomic (temp file + ``os.replace``) so a crash mid-copy cannot leave a
    partial JSONL at the destination.

    Args:
        session_id: Claude session UUID (transcript filename stem).
        source_project_root: CWD whose encoded dir holds the source transcript.
        dest_project_root: CWD whose encoded dir should receive the copy.
        rewrite_paths: Reserved seam for rewriting absolute paths inside content
            blocks. Not implemented in the spike; True raises NotImplementedError.
        overwrite: If the destination exists with *different* bytes, replace it.
            Default False refuses (RelocateConflictError) so an unrelated
            transcript sharing the UUID + encoded dir is never clobbered silently.

    Returns:
        RelocateResult describing source, dest, and whether a write occurred.

    Raises:
        RelocateSourceMissingError: Source transcript does not exist.
        RelocateConflictError: Dest exists with different bytes and overwrite=False.
        NotImplementedError: rewrite_paths=True (deferred opt-in).
    """
    if rewrite_paths:
        raise NotImplementedError(
            "rewrite_paths is a deferred opt-in seam; content-untouched relocation "
            "is the signature-safe minimum for the native-relocate spike."
        )

    source_path = get_transcript_path(source_project_root, session_id)
    if not source_path.exists():
        raise RelocateSourceMissingError(f"No transcript for session {session_id!r} at {source_path}")

    dest_path = get_transcript_path(dest_project_root, session_id)
    source_bytes = source_path.read_bytes()

    if dest_path.exists():
        if dest_path.read_bytes() == source_bytes:
            return RelocateResult(
                session_id=session_id,
                source_path=source_path,
                dest_path=dest_path,
                bytes_copied=0,
                already_present=True,
                paths_rewritten=False,
            )
        if not overwrite:
            raise RelocateConflictError(
                f"Destination transcript {dest_path} exists with different content; "
                "pass overwrite=True to replace it."
            )

    dest_dir = dest_path.parent
    # chmod only a dir we create -- never relax perms on an existing Claude dir.
    created_dir = not dest_dir.exists()
    dest_dir.mkdir(parents=True, exist_ok=True)
    if created_dir:
        os.chmod(dest_dir, _PROJECT_DIR_MODE)

    # Atomic, owner-only: write a unique temp beside the target (same filesystem;
    # mkstemp is 0600), then os.replace. A unique name avoids collisions between
    # concurrent same-UUID relocations, and the temp is removed if anything fails
    # before the rename. Transcripts carry source code and prompts -> keep 0600.
    fd, tmp_name = tempfile.mkstemp(dir=dest_dir, prefix=f".{session_id}.", suffix=".jsonl.tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(source_bytes)
        os.chmod(tmp_path, _TRANSCRIPT_MODE)
        os.replace(tmp_path, dest_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return RelocateResult(
        session_id=session_id,
        source_path=source_path,
        dest_path=dest_path,
        bytes_copied=len(source_bytes),
        already_present=False,
        paths_rewritten=False,
    )
