"""Regression: Claude project-path encoding must convert underscores to hyphens.

Bug: ``encode_project_path`` (src/forge/session/claude/paths.py) replaced only
``/`` and ``.`` with ``-``, but Claude Code 2.1.158 also replaces ``_``. Verified
empirically during the native-relocate spike (Phase 3, runtime_abstraction):
a CWD of ``.../My_Proj.v2_Test-9`` is stored by Claude under
``...-My-Proj-v2-Test-9``. Because ``get_transcript_path`` /
``get_project_encoded_dir`` build on this function, the mismatch silently pointed
transcript lookups at the wrong directory for any underscore-bearing path,
breaking cleanup, status-line transcript reads, and cross-CWD relocation.

Affected: src/forge/session/claude/paths.py (encode_project_path).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.session.claude.paths import (
    encode_project_path,
    get_transcript_path,
)

pytestmark = pytest.mark.regression


def test_underscore_in_path_is_hyphenated(tmp_path: Path) -> None:
    """A single underscore directory component encodes with a hyphen, not '_'."""
    project = tmp_path / "my_project"
    project.mkdir()

    encoded = encode_project_path(str(project))

    assert "_" not in encoded, f"underscore leaked into encoded path: {encoded}"
    assert encoded.endswith("-my-project")


def test_mixed_specials_match_claude_rule(tmp_path: Path) -> None:
    """`/`, `.`, and `_` all map to `-`; case, digits, and `-` are preserved."""
    project = tmp_path / "My_Proj.v2_Test-9"
    project.mkdir()

    encoded = encode_project_path(str(project))

    # The trailing component is what Claude Code 2.1.158 produced empirically.
    assert encoded.endswith("-My-Proj-v2-Test-9")
    assert "_" not in encoded


def test_transcript_path_uses_hyphenated_dir(tmp_path: Path) -> None:
    """get_transcript_path lands in the hyphenated dir Claude actually uses."""
    project = tmp_path / "a_b_c"
    project.mkdir()

    transcript = get_transcript_path(str(project), "uuid-123")

    assert transcript.name == "uuid-123.jsonl"
    assert "_" not in transcript.parent.name
    assert transcript.parent.name.endswith("-a-b-c")
