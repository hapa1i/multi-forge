"""A late advisory designation must reject passthrough before launch commitment."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from forge.core.ops import claude_session, codex_interactive, codex_session
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_authority import set_session_authority
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.runtime.launch_args import RuntimeLaunchArgs
from forge.session.active import ActiveSessionStore
from forge.session.authority import read_authority_events
from forge.session.index import IndexStore
from forge.session.models import CodexConfirmed, create_session_state
from forge.session.store import SessionStore
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("entrypoint", ["claude", "codex_start", "codex_reattach", "codex_first", "codex_continue"])
def test_late_advisory_authority_refuses_passthrough(
    entrypoint: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    (project / ".claude").mkdir()
    monkeypatch.chdir(project)
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    ctx = ExecutionContext(cwd=project, worktree_root=project, project_root=project, forge_root=project)
    parent = create_session_state("planner", worktree_path=str(project))
    existing = create_session_state("impl", worktree_path=str(project), runtime="codex")
    existing.confirmed.codex = CodexConfirmed(thread_id="11111111-2222-3333-4444-555555555555")
    for state in (parent, existing):
        publish_session(IndexStore(), state, project, forge_root=project)

    preflight = CodexPreflight(
        installed=True,
        version="0.160.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="subscription_quota",
        ready=True,
        blocking_reason=None,
        hook_seam="enrollment_gated",
        proxy_responses="native_direct",
        doctor_status="ok",
    )
    monkeypatch.setattr(codex_interactive, "assert_codex_ready", lambda: preflight)
    monkeypatch.setattr(codex_session, "assert_codex_ready", lambda: preflight)

    ops = (
        claude_session
        if entrypoint == "claude"
        else codex_interactive if entrypoint in ("codex_start", "codex_reattach") else codex_session
    )
    transaction = ops.authority_launch_transaction
    changed: list[str] = []

    @contextmanager
    def change_authority_before_lock(**kwargs: Any) -> Iterator[Any]:
        store = kwargs["store"]
        assert store.read().intent.authority is None
        # Model a control-plane update after the caller's read and before the
        # launch lock, using the real publication and authority journal paths.
        set_session_authority(ctx=ctx, session_name=store.session_name, role="advisory", tier=None)
        changed.append(store.session_name)
        with transaction(**kwargs) as attempt:
            yield attempt

    monkeypatch.setattr(ops, "authority_launch_transaction", change_authority_before_lock)
    seam = MagicMock(side_effect=AssertionError("refusal must precede runtime seam verification"))
    monkeypatch.setattr("forge.core.ops.session_authority_launch._preflight_authority_seam", seam)
    invoke = MagicMock(side_effect=AssertionError("refused launch must not invoke a runtime"))
    monkeypatch.setattr(codex_session.CodexHeadlessInvoker, "run", invoke)
    monkeypatch.setattr(codex_session, "bridge_session_to_codex", invoke)
    args = RuntimeLaunchArgs(passthrough=("--debug",) if entrypoint == "claude" else ("--search",))

    with pytest.raises(ForgeOpError, match="not accepted for advisory-authority launches"):
        if entrypoint == "claude":
            claude_session.launch_claude_session(
                manifest=parent,
                session_id=None,
                resume_id=None,
                effective_template=None,
                runtime_base_url=None,
                context_limit=200_000,
                use_sidecar=False,
                invoke=invoke,
                launch_args=args,
            )
        elif entrypoint == "codex_start":
            codex_interactive.start_interactive_codex_session(ctx=ctx, name="child", invoke=invoke, launch_args=args)
        elif entrypoint == "codex_reattach":
            codex_interactive.reattach_codex_session(ctx=ctx, name="impl", invoke=invoke, launch_args=args)
        elif entrypoint == "codex_first":
            codex_session.start_codex_session(
                ctx=ctx, parent="planner", name="child", task="Wait", strategy="minimal", launch_args=args
            )
        else:
            codex_session.continue_codex_session(ctx=ctx, name="impl", task="Wait", launch_args=args)

    assert len(changed) == 1
    seam.assert_not_called()
    invoke.assert_not_called()
    name = changed[0]
    assert [event.event_type for event in read_authority_events(str(project), name)] == ["authority_configured"]
    assert ActiveSessionStore().peek_session(name, forge_root=str(project)) is None
    assert not (project / ".forge" / "artifacts" / name / "routing").exists()
    store = SessionStore(str(project), name)
    if store.exists():
        assert store.read().confirmed.route_commit is None
