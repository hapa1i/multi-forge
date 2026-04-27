"""Regression tests: removed legacy override keys are rejected.

Schema v3 removes `model_tier` and `llm` from the session schema.
These keys should now be rejected as unknown override targets.
"""

from __future__ import annotations

import pytest

from forge.session.exceptions import InvalidOverrideKeyError
from forge.session.overrides import validate_key


def test_model_tier_override_is_rejected() -> None:
    with pytest.raises(InvalidOverrideKeyError) as exc_info:
        validate_key("model_tier")
    assert "unknown field" in str(exc_info.value)


def test_llm_override_is_rejected() -> None:
    with pytest.raises(InvalidOverrideKeyError) as exc_info:
        validate_key("llm.temperature")
    assert "unknown field" in str(exc_info.value)
