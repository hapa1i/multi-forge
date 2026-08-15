"""Source-parity contract for the self-contained walkthrough state scripts."""

from __future__ import annotations

import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STATE_SCRIPT_PATHS = {
    skill: REPO_ROOT / "src" / "skills" / skill / "scripts" / "walkthrough-state.py" for skill in ("walkthrough", "qa")
}

_ALLOWED_IDENTITY_LINES = {
    "walkthrough": {
        1: '"""Parse the walkthrough checklist into structured JSON with state tracking.',
        7: "This script is packaged with the walkthrough skill. The QA skill carries an",
    },
    "qa": {
        1: '"""Parse the QA checklist into structured JSON with state tracking.',
        7: "This script is packaged with the QA skill. The walkthrough skill carries an",
    },
}


def _normalized_script(skill: str) -> list[bytes]:
    lines = STATE_SCRIPT_PATHS[skill].read_bytes().splitlines(keepends=True)
    for line_number, expected in _ALLOWED_IDENTITY_LINES[skill].items():
        expected_line = f"{expected}\n".encode()
        assert lines[line_number] == expected_line, f"unexpected {skill} identity line {line_number + 1}"
        lines[line_number] = f"<allowed-skill-identity-line-{line_number + 1}>\n".encode()
    return lines


def test_walkthrough_and_qa_state_scripts_differ_only_in_named_identity_lines() -> None:
    assert _normalized_script("walkthrough") == _normalized_script("qa")


def test_walkthrough_and_qa_state_scripts_share_an_executable_mode() -> None:
    modes = [stat.S_IMODE(path.stat().st_mode) for path in STATE_SCRIPT_PATHS.values()]
    assert len(set(modes)) == 1
    assert modes[0] & stat.S_IXUSR
