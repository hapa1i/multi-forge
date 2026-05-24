"""Drift tripwire: walkthrough-state.py must be byte-identical in both locations.

The walkthrough/ copy is canonical; the qa/ copy is generated from it by
scripts/sync-walkthrough-state.py (the sync-walkthrough-state pre-commit hook).
This test is the backstop that catches drift when the hook is bypassed
(git commit --no-verify) or the qa/ copy is edited directly.
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
        "Edit the walkthrough/ copy, then run scripts/sync-walkthrough-state.py "
        "(or let the sync-walkthrough-state pre-commit hook) to regenerate the qa/ copy."
    )
