"""A completed Codex turn cannot publish facts or consume a replacement's receipts."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

from forge.core.ops import codex_interactive, codex_session
from forge.session import IndexStore, SessionManager, SessionStore, create_session_state
from forge.session.codex_handoff import (
    consume_pending_context,
    stage_pending_context,
    write_observation_receipt,
)
from forge.session.models import CodexConfirmed
from tests.fixtures.session_state import publish_session
from tests.src.core.ops.test_codex_interactive import _FakeInvoke, _interactive_mocks
from tests.src.core.ops.test_codex_session import (
    _SUCCESS_TID,
    _codex_mocks,
    _make_project,
    _seed_codex_session,
)

pytestmark = pytest.mark.regression

_REPLACEMENT_THREAD = "11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize("frontend", ["headless", "interactive"])
@pytest.mark.parametrize("operation", ["start", "resume"])
@pytest.mark.parametrize("boundary", ["after-runtime", "before-index-sync"])
def test_post_turn_replacement_preserves_new_instance_and_completed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, frontend: str, operation: str, boundary: str
) -> None:
    project, ctx = _make_project(tmp_path, monkeypatch)
    if operation == "resume":
        _seed_codex_session(project)
    module = codex_session if frontend == "headless" else codex_interactive
    store = SessionStore(str(project), "impl")
    replacement_files: dict[str, bytes] = {}
    replacement_row: dict[str, Any] = {}
    old_tokens: list[str] = []

    def replace_completed_instance() -> None:
        token = store.review_identity()
        assert token is not None
        old_tokens.append(token)
        # This uses supported cleanup after the runtime lease has been released.
        SessionManager().delete_session("impl", forge_root=str(project), delete_worktree=False)
        replacement = create_session_state("impl", worktree_path=str(project), runtime="codex")
        replacement.confirmed.codex = CodexConfirmed(thread_id=_REPLACEMENT_THREAD)
        replacement.confirmed.confirmed_by = "replacement"
        entry = publish_session(IndexStore(), replacement, project)
        assert entry.instance_id != token
        replacement_row.update(vars(entry))
        stage_pending_context(store.session_dir, "replacement delivery receipt")
        consume_pending_context(
            store.session_dir, session_id=_REPLACEMENT_THREAD, transcript_path=None, source="startup"
        )
        write_observation_receipt(
            store.session_dir, session_id=_REPLACEMENT_THREAD, transcript_path=None, source="startup"
        )
        stage_pending_context(store.session_dir, "replacement pending handoff")
        replacement_files.update(
            {
                str(path.relative_to(store.session_dir)): path.read_bytes()
                for path in store.session_dir.rglob("*")
                if path.is_file()
            }
        )

    if boundary == "after-runtime":
        original_authority = module.authority_launch_transaction

        @contextmanager
        def replace_after_runtime(**kwargs: Any) -> Iterator[Any]:
            with original_authority(**kwargs) as attempt:
                yield attempt
            replace_completed_instance()

        monkeypatch.setattr(module, "authority_launch_transaction", replace_after_runtime)
    else:
        original_sync = module.sync_codex_thread_to_index

        def replace_before_index_sync(*args: Any, **kwargs: Any) -> None:
            replace_completed_instance()
            original_sync(*args, **kwargs)

        monkeypatch.setattr(module, "sync_codex_thread_to_index", replace_before_index_sync)

    result: (
        codex_session.CodexSessionStartResult
        | codex_session.CodexSessionResumeResult
        | codex_interactive.CodexInteractiveResult
    )
    if frontend == "headless":
        with _codex_mocks():
            if operation == "start":
                result = codex_session.start_codex_session(
                    ctx=ctx, name="impl", parent="planner", task="Synthetic task", context_delivery="hook"
                )
            else:
                result = codex_session.continue_codex_session(ctx=ctx, name="impl", task="Synthetic continuation")
        assert result.codex.success and result.codex.returncode == 0
    else:
        monkeypatch.setattr(
            codex_interactive, "_discover_thread_post_exit", lambda *args, **kwargs: (_SUCCESS_TID, None, None)
        )
        with _interactive_mocks():
            if operation == "start":
                interactive_result = codex_interactive.start_interactive_codex_session(
                    ctx=ctx, name="impl", parent="planner", invoke=_FakeInvoke(), context_delivery="hook"
                )
            else:
                interactive_result = codex_interactive.reattach_codex_session(
                    ctx=ctx, name="impl", invoke=_FakeInvoke()
                )
        assert interactive_result.exit_code == 0
        result = interactive_result

    assert len(old_tokens) == 1
    assert store.review_identity() == replacement_row["instance_id"]
    current_entry = IndexStore().peek_session("impl", str(project))
    assert current_entry is not None and vars(current_entry) == replacement_row
    assert {
        str(path.relative_to(store.session_dir)): path.read_bytes()
        for path in store.session_dir.rglob("*")
        if path.is_file()
    } == replacement_files
    assert result.thread_id == _SUCCESS_TID
    assert any(
        "post-exit manifest update" in warning or "Could not publish Codex thread" in warning
        for warning in result.warnings
    )
