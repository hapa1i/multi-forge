"""Drift tripwire: walkthrough-state.py must be byte-identical in both locations.

The QA skill (src/skills/qa/) and walkthrough skill (src/skills/walkthrough/)
each have a copy of walkthrough-state.py. They must stay in sync — if one is
updated, the other must be too.
"""

from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    """Walk up from this test file to find the repo root (contains pyproject.toml)."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    msg = "Cannot find repo root (no pyproject.toml in parents)"
    raise RuntimeError(msg)


def test_walkthrough_state_py_identical() -> None:
    """Both copies of walkthrough-state.py must be byte-identical."""
    root = _repo_root()
    walkthrough_copy = root / "src" / "skills" / "walkthrough" / "scripts" / "walkthrough-state.py"
    qa_copy = root / "src" / "skills" / "qa" / "scripts" / "walkthrough-state.py"

    assert walkthrough_copy.exists(), f"Missing: {walkthrough_copy}"
    assert qa_copy.exists(), f"Missing: {qa_copy}"

    walkthrough_bytes = walkthrough_copy.read_bytes()
    qa_bytes = qa_copy.read_bytes()

    assert walkthrough_bytes == qa_bytes, (
        "walkthrough-state.py has drifted between walkthrough/ and qa/. "
        "These files must be byte-identical. Update both when changing either."
    )
