"""O027 regression: optional unwrapping is restricted to real unions."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pytest

from forge.core.typing_helpers import unwrap_optional
from forge.session import SessionStore, create_session_state

pytestmark = pytest.mark.regression


@pytest.mark.parametrize(
    "annotation",
    [
        pytest.param(list[str], id="list"),
        pytest.param(set[str], id="set"),
        pytest.param(tuple[str], id="tuple"),
    ],
)
def test_single_argument_generic_is_not_unwrapped(annotation: object) -> None:
    assert unwrap_optional(annotation) == annotation


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        pytest.param(Optional[str], str, id="typing-optional"),
        pytest.param(str | None, str, id="pep604-optional"),
        pytest.param(Union[str, int], Union[str, int], id="non-optional-union"),
    ],
)
def test_union_handling_control(annotation: object, expected: object) -> None:
    assert unwrap_optional(annotation) == expected


def test_list_typed_intent_overrides_keep_round_trip_semantics(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path), "session")
    state = create_session_state("session", worktree_path=str(tmp_path))
    state.overrides = {
        "memory": {"tags": ["project"]},
        "policy": {"bundles": ["tdd"]},
    }
    store.write(state)

    loaded = store.read()

    assert loaded.overrides == state.overrides
