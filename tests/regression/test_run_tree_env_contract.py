"""Regression: run-tree identity stays orthogonal to FORGE_DEPTH (Phase 4a).

Run identity (FORGE_RUN_ID/FORGE_PARENT_RUN_ID/FORGE_ROOT_RUN_ID) was added
alongside the existing FORGE_DEPTH recursion guard. The two MUST stay orthogonal:
introducing run identity must not change the depth increment, and the depth-based
spawn guard must keep firing regardless of run-tree vars. Three recursion guards
depend on FORGE_DEPTH >= 2 (semantic supervisor, team handlers, review engine), so
a regression here would silently re-enable runaway subprocess spawning.

Affected: src/forge/core/reactive/env.py
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from forge.core.reactive.env import (
    FORGE_DEPTH_VAR,
    FORGE_PARENT_RUN_ID_VAR,
    FORGE_ROOT_RUN_ID_VAR,
    FORGE_RUN_ID_VAR,
    build_claude_env,
    get_forge_depth,
    should_spawn_subprocesses,
)

pytestmark = pytest.mark.regression


def test_depth_increment_unchanged_by_run_identity():
    """Stamping run identity does not alter the FORGE_DEPTH increment."""
    with patch.dict("os.environ", {FORGE_DEPTH_VAR: "1"}, clear=True):
        env = build_claude_env()
    assert env[FORGE_DEPTH_VAR] == "2"
    # Run-tree vars are present but computed independently of depth.
    assert FORGE_RUN_ID_VAR in env
    assert FORGE_ROOT_RUN_ID_VAR in env


def test_get_forge_depth_ignores_run_vars():
    """get_forge_depth reads only FORGE_DEPTH, never the run-tree vars."""
    env = {
        FORGE_DEPTH_VAR: "1",
        FORGE_RUN_ID_VAR: "run_x",
        FORGE_PARENT_RUN_ID_VAR: "run_p",
        FORGE_ROOT_RUN_ID_VAR: "run_r",
    }
    assert get_forge_depth(env) == 1


def test_spawn_guard_fires_at_max_depth_with_run_vars():
    """At FORGE_DEPTH >= 2 the spawn guard returns False even with run vars set."""
    env = {
        FORGE_DEPTH_VAR: "2",
        FORGE_RUN_ID_VAR: "run_x",
        FORGE_ROOT_RUN_ID_VAR: "run_r",
    }
    assert should_spawn_subprocesses(env) is False


def test_spawn_guard_allows_below_max_with_run_vars():
    """Below max depth the guard still allows spawning regardless of run vars."""
    env = {FORGE_DEPTH_VAR: "1", FORGE_RUN_ID_VAR: "run_x"}
    assert should_spawn_subprocesses(env) is True
