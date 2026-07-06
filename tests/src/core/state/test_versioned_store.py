"""Tests for shared versioned JSON store reads."""

from __future__ import annotations

import pytest

from forge.core.state import (
    StateCorruptedError,
    StateUnreadableError,
    read_versioned_json_object,
)


def test_null_version_defaults_to_missing_version(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"version": null}')

    with pytest.raises(StateCorruptedError, match="missing version field"):
        read_versioned_json_object(
            path,
            version_key="version",
            expected_version=1,
            corrupted_error=StateCorruptedError,
            unreadable_error=StateUnreadableError,
        )


def test_null_version_can_be_treated_as_mismatch(tmp_path) -> None:
    path = tmp_path / "state.json"
    path.write_text('{"version": null}')

    with pytest.raises(StateCorruptedError, match="incompatible version None"):
        read_versioned_json_object(
            path,
            version_key="version",
            expected_version=1,
            corrupted_error=StateCorruptedError,
            unreadable_error=StateUnreadableError,
            none_is_missing=False,
        )
