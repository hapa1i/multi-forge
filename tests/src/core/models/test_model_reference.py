from __future__ import annotations

import pytest

from forge.core.models.model_reference import (
    normalize_model_reference,
    strip_transport_model_suffix,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("claude-opus-5", "claude-opus-5"),
        ("claude-opus-5[1m]", "claude-opus-5"),
        ("anthropic/claude-opus-5", "claude-opus-5"),
        ("anthropic/claude-opus-5[1m]", "claude-opus-5"),
        ("opus", "claude-opus-5"),
        ("unknown-model", None),
        ("provider/unknown-model", None),
        ("anthropic/claude-opus-4-1", None),
        (None, None),
        ("  ", None),
    ],
)
def test_normalize_model_reference(value: str | None, expected: str | None) -> None:
    assert normalize_model_reference(value) == expected


def test_strip_transport_suffix_removes_only_the_terminal_hint() -> None:
    assert strip_transport_model_suffix("anthropic/[1m]/claude[1m]") == "anthropic/[1m]/claude"
