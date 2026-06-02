"""Regression: a corrupted raw derivation must not crash transcript-cleanup scans.

Bug (audit second-pass, medium): _tracked_derivation_transcript_session_ids() narrowed every
non-None, non-Derivation value with .get(). Force-delete and shared-transcript scans pass the raw
JSON value of confirmed.derivation from manifests that failed strict validation, so a corrupted
"derivation": "oops" (a str, not a dict) hit "oops".get(...) -> AttributeError and aborted cleanup.
The regression was introduced when an earlier fix merged the dict branch into else to silence a
pyright "unreachable return []".

Fix: restore the isinstance(dict) guard with else -> [], widening the param to object so the guard
stays pyright-clean (object minus Derivation minus dict is still inhabited). src/forge/session/manager.py.
"""

from __future__ import annotations

import pytest

from forge.session.manager import (
    _referenced_transcript_session_ids,
    _tracked_derivation_transcript_session_ids,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("bad", ["oops", 123, 4.5, ["uuid"], True, ("x",)])
def test_malformed_raw_derivation_returns_empty_without_raising(bad: object) -> None:
    """A non-dict / non-Derivation derivation value degrades to [] (no AttributeError)."""
    assert _tracked_derivation_transcript_session_ids(bad) == []


def test_none_derivation_returns_empty() -> None:
    assert _tracked_derivation_transcript_session_ids(None) == []


def test_referenced_ids_survives_corrupted_derivation_in_raw_manifest() -> None:
    """The real force-delete scan path (raw_data branch) must not raise on a bad derivation, and must
    still recover the other UUID fields it can read."""
    raw = {"confirmed": {"claude_session_id": "uuid-good", "derivation": "oops"}}
    ids = _referenced_transcript_session_ids(None, raw)
    assert "uuid-good" in ids


def test_valid_raw_dict_derivation_still_extracted() -> None:
    """The dict path (the common raw case) still yields the relocated UUID -- no feature regression."""
    raw = {"confirmed": {"derivation": {"relocated_parent_session_id": "puuid-1"}}}
    assert "puuid-1" in _referenced_transcript_session_ids(None, raw)
