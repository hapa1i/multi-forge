"""Tests for cross-CWD transcript relocation (native-relocate spike).

The autouse ``isolate_claude_home`` fixture (tests/conftest.py) points
``CLAUDE_HOME`` at a temp dir, so these tests exercise the *real* path helpers
(`get_transcript_path` / `get_project_encoded_dir`) rather than monkeypatching
them -- the whole point of the primitive is correct CWD-encoded path math.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from forge.session.claude.paths import (
    encode_project_path,
    get_claude_home,
    get_transcript_path,
)
from forge.session.claude.relocate import (
    RelocateConflictError,
    RelocateResult,
    RelocateSourceMissingError,
    relocate_transcript,
)

_UUID = "abc-123-def-456"
_SIGNATURE_MARKER = "FAKE_SIGNATURE_zzz999"
_SIGNED_TRANSCRIPT = (
    '{"type":"assistant","message":{"content":['
    '{"type":"thinking","thinking":"reasoning...","signature":"' + _SIGNATURE_MARKER + '"},'
    '{"type":"tool_use","name":"Read","input":{"file_path":"/workspace/x.txt"}}]}}\n'
).encode("utf-8")


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    """Two real CWDs (parent + child) to encode into distinct project dirs."""
    src = tmp_path / "parent_cwd"
    dst = tmp_path / "child_cwd"
    src.mkdir()
    dst.mkdir()
    return src, dst


def _seed(root: Path, session_id: str, data: bytes) -> Path:
    """Write a transcript at the CWD-encoded path for ``root`` and return it."""
    path = get_transcript_path(str(root), session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class TestRelocateTranscript:
    """Tests for relocate_transcript()."""

    def test_copies_bytes_verbatim(self, roots: tuple[Path, Path]) -> None:
        """Signed content is reproduced byte-for-byte at the dest encoded dir."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)

        result = relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
        )

        assert isinstance(result, RelocateResult)
        assert result.dest_path.read_bytes() == _SIGNED_TRANSCRIPT
        assert _SIGNATURE_MARKER in result.dest_path.read_text()
        assert result.bytes_copied == len(_SIGNED_TRANSCRIPT)
        assert result.already_present is False
        assert result.paths_rewritten is False
        assert result.dest_path == get_transcript_path(str(dst), _UUID)

    def test_creates_dest_encoded_dir(self, roots: tuple[Path, Path]) -> None:
        """The destination CWD-encoded dir is created and correctly named."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)
        dest_dir = get_transcript_path(str(dst), _UUID).parent
        assert not dest_dir.exists()

        relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
        )

        assert dest_dir.is_dir()
        assert dest_dir.name == encode_project_path(str(dst))

    def test_missing_source_raises(self, roots: tuple[Path, Path]) -> None:
        """A missing source transcript raises (clean break, no silent no-op)."""
        src, dst = roots
        with pytest.raises(RelocateSourceMissingError):
            relocate_transcript(
                session_id=_UUID,
                source_project_root=str(src),
                dest_project_root=str(dst),
            )

    def test_idempotent_identical(self, roots: tuple[Path, Path]) -> None:
        """A second relocate of identical bytes is a no-op (bytes_copied=0)."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)

        first = relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
        )
        second = relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
        )

        assert first.already_present is False
        assert second.already_present is True
        assert second.bytes_copied == 0
        assert second.dest_path.read_bytes() == _SIGNED_TRANSCRIPT

    def test_refuses_clobber_on_diff(self, roots: tuple[Path, Path]) -> None:
        """Differing dest bytes are not overwritten unless overwrite=True."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)
        other = _seed(dst, _UUID, b'{"unrelated":"transcript"}\n')

        with pytest.raises(RelocateConflictError):
            relocate_transcript(
                session_id=_UUID,
                source_project_root=str(src),
                dest_project_root=str(dst),
            )
        assert other.read_bytes() == b'{"unrelated":"transcript"}\n'

        forced = relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
            overwrite=True,
        )
        assert forced.dest_path.read_bytes() == _SIGNED_TRANSCRIPT
        assert forced.bytes_copied == len(_SIGNED_TRANSCRIPT)
        assert forced.already_present is False

    def test_rewrite_paths_not_implemented(self, roots: tuple[Path, Path]) -> None:
        """The rewrite_paths seam is reserved, not implemented (locks deferral)."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)
        with pytest.raises(NotImplementedError):
            relocate_transcript(
                session_id=_UUID,
                source_project_root=str(src),
                dest_project_root=str(dst),
                rewrite_paths=True,
            )

    def test_dest_perms_owner_only(self, roots: tuple[Path, Path]) -> None:
        """A created dest dir is 0700 and the transcript is 0600."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)

        result = relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
        )

        assert stat.S_IMODE(result.dest_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(result.dest_path.parent.stat().st_mode) == 0o700

    def test_respects_claude_home(self, roots: tuple[Path, Path]) -> None:
        """The dest lands under the isolated CLAUDE_HOME, never the real ~/.claude."""
        src, dst = roots
        _seed(src, _UUID, _SIGNED_TRANSCRIPT)

        result = relocate_transcript(
            session_id=_UUID,
            source_project_root=str(src),
            dest_project_root=str(dst),
        )

        assert result.dest_path.is_relative_to(get_claude_home())
        assert get_claude_home() != Path.home() / ".claude"
