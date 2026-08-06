"""D008 regression: a parent launch override must not replace runtime identity.

Root cause: ``validate_key`` rejected only the exact ``launch.runtime`` path, so
setting the parent ``launch`` object bypassed the guard and persisted an effective
runtime that launcher dispatch deliberately ignores.
"""

from __future__ import annotations

import pytest

from forge.session.exceptions import InvalidOverrideKeyError
from forge.session.overrides import set_override

pytestmark = pytest.mark.regression


def test_parent_launch_object_cannot_override_runtime() -> None:
    overrides: dict[str, object] = {}

    with pytest.raises(InvalidOverrideKeyError, match="runtime is immutable launch identity"):
        set_override(overrides, "launch", {"runtime": "codex"})

    assert overrides == {}
