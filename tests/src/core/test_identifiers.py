from __future__ import annotations

import pytest

from forge.core.identifiers import is_lowercase_identifier


@pytest.mark.parametrize(
    "value",
    ["openrouter", "litellm-gemini-local", "backend_1", "backend.v2", "0-local"],
)
def test_lowercase_identifier_accepts_canonical_values(value: str) -> None:
    assert is_lowercase_identifier(value) is True


@pytest.mark.parametrize(
    "value",
    [None, "", "OpenRouter", "-backend", "backend/name", "backend:name", " backend", "backend "],
)
def test_lowercase_identifier_rejects_noncanonical_values(value: object) -> None:
    assert is_lowercase_identifier(value) is False
