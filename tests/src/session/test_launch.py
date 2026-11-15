"""Tests for forge.session.launch."""

from __future__ import annotations

import pytest

from forge.core.reactive.env import FORGE_PROXY_WIRE_SHAPE_VAR
from forge.session.launch import _build_session_env


@pytest.mark.parametrize(("resolved", "expect_unset"), [("openai_translated", False), (None, True)])
def test_proxy_launch_replaces_or_scrubs_inherited_wire_shape(
    monkeypatch: pytest.MonkeyPatch, resolved: str | None, expect_unset: bool
) -> None:
    """A parent session's shape must not describe a proxy whose own shape is unknown."""
    monkeypatch.setattr("forge.session.launch.resolve_proxy_wire_shape", lambda **_kw: resolved)

    env_vars, unset_vars = _build_session_env(
        session_name="child",
        context_limit=200000,
        template="private-template",
        base_url="http://127.0.0.1:18310",
        proxy_id="private-proxy",
    )

    assert env_vars.get(FORGE_PROXY_WIRE_SHAPE_VAR) == resolved
    assert (FORGE_PROXY_WIRE_SHAPE_VAR in unset_vars) is expect_unset
