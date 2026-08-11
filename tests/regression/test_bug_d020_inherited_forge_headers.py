"""Regression for D020: direct children must not inherit Forge correlation headers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.core.reactive.env import build_claude_env
from forge.core.run_id import (
    ANTHROPIC_CUSTOM_HEADERS_VAR,
    FORGE_COMMAND_HEADER,
    FORGE_ROOT_RUN_ID_HEADER,
    FORGE_RUN_ID_HEADER,
    FORGE_SESSION_HEADER,
)

pytestmark = pytest.mark.regression


def test_direct_child_strips_inherited_forge_headers() -> None:
    inherited = "\n".join(
        [
            "X-User: keep",
            f"{FORGE_RUN_ID_HEADER}: run_stale",
            f"{FORGE_ROOT_RUN_ID_HEADER.lower()}: run_root_stale",
            f"{FORGE_SESSION_HEADER}: forge_sess_stale",
            f"{FORGE_COMMAND_HEADER.lower()}: supervisor",
            "malformed-user-line",
        ]
    )

    with patch.dict("os.environ", {}, clear=True):
        env = build_claude_env(
            extra_vars={ANTHROPIC_CUSTOM_HEADERS_VAR: inherited},
            direct=True,
        )

    assert env[ANTHROPIC_CUSTOM_HEADERS_VAR].splitlines() == [
        "X-User: keep",
        "malformed-user-line",
    ]


def test_direct_child_removes_header_var_when_only_forge_headers_remain() -> None:
    with patch.dict("os.environ", {}, clear=True):
        env = build_claude_env(
            extra_vars={ANTHROPIC_CUSTOM_HEADERS_VAR: f"{FORGE_RUN_ID_HEADER}: run_stale"},
            direct=True,
        )

    assert ANTHROPIC_CUSTOM_HEADERS_VAR not in env
