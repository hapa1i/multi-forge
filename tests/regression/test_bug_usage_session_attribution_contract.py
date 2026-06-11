"""Regression: the per-session usage read surface must agree with what emitters tag.

``forge usage`` / the session-end summary find a session's ledger events by
``event.session == manifest.name`` (the read filter) and read its policy decisions from
that manifest. The supervisor -- the headline emitter, whose ``status="error"`` events are
the OpenRouter content-filter failures this surface was built to reveal -- tags its ledger
event with ``session=context.session_name``. So the surface only works if
``ActionContext.session_name == manifest.name``.

That bridge is a single assignment in ``ClaudeHookAdapter.build_contexts``
(``session_name=manifest.name``). Pin it so a future change (e.g. tagging a Claude UUID
instead of the name) -- which would silently make supervisor activity invisible to
``forge usage`` while the policy-decision half kept working -- fails loudly here.

Affected: ``src/forge/cli/hooks/policy.py``, ``src/forge/core/ops/usage_summary.py``.
"""

from __future__ import annotations

import pytest

from forge.cli.hooks.policy import ClaudeHookAdapter
from forge.core.ops.usage_summary import build_session_activity_summary
from forge.core.usage.ledger import UsageEvent, log_usage_event
from forge.session.models import create_session_state

pytestmark = pytest.mark.regression


def test_action_context_session_name_is_manifest_name() -> None:
    manifest = create_session_state("planner", worktree_path="/tmp/x")
    [ctx] = ClaudeHookAdapter().build_contexts(
        {"tool_input": {"file_path": "a.py", "content": "x"}},
        "Write",
        manifest,
    )
    # The bridge: the supervisor emits its ledger event with session=context.session_name,
    # and the read surface filters event.session == manifest.name. If these diverge, the
    # ledger half (incl. supervisor errors) goes silently invisible to `forge usage`.
    assert ctx.session_name == manifest.name


def test_supervisor_tagged_event_is_found_by_read_surface() -> None:
    # An event tagged with the manifest name (what the supervisor does via
    # context.session_name) must be attributed to that session by the read surface --
    # this is the content-filter-failure visibility the whole feature is for.
    log_usage_event(
        UsageEvent(
            run_id="r",
            root_run_id="r",
            runtime="claude_code",
            command="supervisor",
            status="error",
            session="planner",
        )
    )
    summary = build_session_activity_summary("planner", forge_root=None)
    sup = next(c for c in summary.commands if c.command == "supervisor")
    assert sup.errors == 1
