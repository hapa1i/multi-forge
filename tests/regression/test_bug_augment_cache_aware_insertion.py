"""Regression: system_prompt_augment must insert cache-aware.

Bug class: silent cache invalidation. The card requires augmentation to prefer
the post-cache tail (after the final system cache_control marker) so the cached
prefix stays byte-identical; only when there is no safe anchor should it append
and LOG the expected invalidation. A naive prepend/insert-before would shift the
cached prefix and silently blow the prompt cache.

Affected files: src/forge/proxy/intercept.py
"""

from __future__ import annotations

import pytest

from forge.proxy import intercept

pytestmark = pytest.mark.regression


def test_augment_inserted_after_last_cache_marker_preserves_prefix():
    system = [
        {"type": "text", "text": "stable cached preamble", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "uncached tail"},
    ]
    new, invalidation = intercept.insert_augment_cache_aware(system, "user addendum")

    assert invalidation is False
    # The cached block (index 0, with its marker) is byte-identical and still first.
    assert new[0] == {"type": "text", "text": "stable cached preamble", "cache_control": {"type": "ephemeral"}}
    # The augment lands immediately AFTER the marker, never before it.
    assert new[1] == {"type": "text", "text": "user addendum"}
    assert new[2]["text"] == "uncached tail"


def test_multiple_markers_anchor_on_the_last_one():
    system = [
        {"type": "text", "text": "p0", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "p1", "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "p2"},
    ]
    new, invalidation = intercept.insert_augment_cache_aware(system, "AUG")
    assert invalidation is False
    assert [b["text"] for b in new] == ["p0", "p1", "AUG", "p2"]  # after the LAST marker


def test_markerless_system_flags_expected_invalidation():
    new, invalidation = intercept.insert_augment_cache_aware([{"type": "text", "text": "no cache marker here"}], "AUG")
    assert invalidation is True  # surfaced, not silent
    assert [b["text"] for b in new] == ["no cache marker here", "AUG"]
