"""Incognito exit cleanup must retain a replacement with the same session name."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.core.ops.claude_session import (
    ClaudeLaunchPreferences,
    ForkLaunchPlan,
    _run_incognito_cleanup,
    fork_claude_session,
    start_claude_session,
)
from forge.core.ops.session import ForgeOpError
from forge.core.runtime.launch_args import RuntimeLaunchArgs
from forge.session import SessionManager, SessionStore, create_session_state
from tests.fixtures.session_state import delete_published_session, publish_session

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("operation", ["start", "fork"])
def test_exit_cleanup_retains_replacement_instance(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    root = git_repo.resolve()
    (root / ".forge").mkdir(exist_ok=True)
    (root / ".claude").mkdir(exist_ok=True)
    monkeypatch.chdir(root)
    manager = SessionManager()
    presenter = MagicMock()
    name = "private-session"
    replacement = create_session_state(name, worktree_path=str(root))
    replacement.forge_root = str(root)
    store = SessionStore(str(root), name)
    replacement_identity: list[str] = []
    replacement_bytes: list[bytes] = []

    def replace_after_launch(**_kwargs: object) -> None:
        # Simulate the gap after the old launch lease exits and before its finally cleanup.
        delete_published_session(manager.index_store, name, root)
        publish_session(manager.index_store, replacement, root)
        replacement_token = store.review_identity()
        assert replacement_token is not None
        replacement_identity.append(replacement_token)
        replacement_bytes.append(store.manifest_path.read_bytes())
        raise ForgeOpError("old launcher finished")

    with (
        patch("forge.core.ops.claude_session.preflight_host_claude_binary"),
        patch(
            "forge.core.ops.claude_session.launch_claude_session",
            side_effect=replace_after_launch,
        ),
    ):
        if operation == "start":
            result = start_claude_session(
                manager=manager,
                name=name,
                template=None,
                base_url=None,
                direct=True,
                incognito=True,
                worktree=False,
                branch=None,
                launch_mode="host",
                use_sidecar=False,
                mounts=(),
                image=None,
                no_launch=False,
                extensions=None,
                launch_args=RuntimeLaunchArgs(),
                context_limit_override=None,
                proxy_display=None,
                proxy_id=None,
                normalized_direct_model=None,
                prompt_file=None,
                memory_flag=None,
                subprocess_proxy=None,
                supervisor=None,
                presenter=presenter,
            )
            assert result.exit_code == 1
        else:
            original = replace(replacement, is_incognito=True)
            publish_session(manager.index_store, original, root)
            plan = ForkLaunchPlan(
                manifest=original,
                session_id=None,
                resume_id=None,
                fork_session=True,
                register_fork=False,
                prompt_file=None,
                context_limit=200_000,
                launch_preferences=ClaudeLaunchPreferences(use_sidecar=False, mounts=(), image=None),
                effective_template=None,
                runtime_base_url=None,
                proxy_id=None,
                incognito=True,
                render_post_exit=False,
                instance_id=store.review_identity(),
            )
            fork_result = fork_claude_session(manager=manager, plan=plan, presenter=presenter)
            assert fork_result.exit_code == 1

    assert store.manifest_path.read_bytes() == replacement_bytes[0]
    assert store.review_identity() == replacement_identity[0]
    assert not store.read().is_incognito
    assert manager.index_store.peek_session(name, str(root)) is not None
    presenter.on_incognito_cleanup_ok.assert_not_called()
    warning = presenter.on_incognito_cleanup_warning.call_args.args[0]
    assert "retained its replacement" in warning
    assert "forge session purge" not in warning


def test_missing_original_identity_never_recaptures_current_session(
    tmp_path: Path,
) -> None:
    state = create_session_state("private-session", worktree_path=str(tmp_path))
    manager = MagicMock()
    presenter = MagicMock()

    _run_incognito_cleanup(manager, state, presenter, expected_instance_id=None)

    manager.purge_session.assert_not_called()
    assert "no captured instance identity" in presenter.on_incognito_cleanup_warning.call_args.args[0]


def test_stale_prepared_fork_cannot_launch_under_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.session.exceptions import SessionNotFoundError

    root = tmp_path.resolve()
    monkeypatch.chdir(root)
    manager = SessionManager()
    original = create_session_state("private-session", worktree_path=str(root), is_incognito=True)
    original.forge_root = str(root)
    publish_session(manager.index_store, original, root)
    store = SessionStore(str(root), original.name)
    original_instance = store.review_identity()
    delete_published_session(manager.index_store, original.name, root)
    replacement = replace(original, is_incognito=False)
    publish_session(manager.index_store, replacement, root)
    before = store.manifest_path.read_bytes()
    plan = ForkLaunchPlan(
        manifest=original,
        session_id=None,
        resume_id=None,
        fork_session=True,
        register_fork=False,
        prompt_file=None,
        context_limit=200_000,
        launch_preferences=ClaudeLaunchPreferences(use_sidecar=False, mounts=(), image=None),
        effective_template=None,
        runtime_base_url=None,
        proxy_id=None,
        incognito=True,
        render_post_exit=False,
        instance_id=original_instance,
    )
    invoke = MagicMock()
    with patch("forge.core.ops.claude_session.preflight_host_claude_binary"):
        with pytest.raises(SessionNotFoundError):
            fork_claude_session(manager=manager, plan=plan, presenter=MagicMock(), invoke=invoke)

    invoke.assert_not_called()
    assert store.manifest_path.read_bytes() == before


def test_fresh_rewind_cleanup_uses_original_child_identity(git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.cli.session_lifecycle import _rollback_created_session

    root = git_repo.resolve()
    (root / ".forge").mkdir(exist_ok=True)
    monkeypatch.chdir(root)
    manager = SessionManager()
    manager.start_session("parent", direct=True)
    published: list[str] = []
    child, _ = manager.resume_session(
        "parent", child_name="fresh-child", resume_mode="native", instance_sink=published.append
    )
    assert published == [SessionStore(str(root), child.name).review_identity()]
    delete_published_session(manager.index_store, child.name, root)
    replacement = create_session_state(child.name, worktree_path=str(root))
    replacement.forge_root = str(root)
    publish_session(manager.index_store, replacement, root)
    store = SessionStore(str(root), child.name)
    before = store.manifest_path.read_bytes()

    error, tip = _rollback_created_session(
        manager=manager,
        session_name=child.name,
        forge_root=child.forge_root,
        delete_worktree=False,
        error="Rewind preparation failed.",
        tip="Retry preparation.",
        log_context="rewind test",
        expected_instance_id=published[0],
    )

    assert "retained its replacement" in error
    assert "--keep-worktree" in tip
    assert f"--forge-root {root}" in tip
    assert store.manifest_path.read_bytes() == before


def test_initial_native_refusal_offers_only_original_instance_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shlex

    root = tmp_path / "project with spaces"
    root.mkdir()
    manager = SessionManager()
    state = create_session_state("private-session", worktree_path=str(root), is_incognito=True)
    state.forge_root = str(root)
    publish_session(manager.index_store, state, root)
    store = SessionStore(str(root), state.name)
    token = store.review_identity()
    assert token is not None
    before = store.manifest_path.read_bytes()
    presenter = MagicMock()
    monkeypatch.setattr(
        "forge.session.purge_native.check_native_inactivity",
        lambda _runtime: ("Claude client is still active; exit it before purge",),
    )

    _run_incognito_cleanup(manager, state, presenter, expected_instance_id=token)

    warning = presenter.on_incognito_cleanup_warning.call_args.args[0]
    expected = shlex.join(["forge", "session", "purge", state.name, "--forge-root", str(root), "--force"])
    assert "Claude client is still active" in warning
    assert "review a new purge preview" in warning
    assert expected in warning
    assert "--yes" not in warning
    assert store.manifest_path.read_bytes() == before
    presenter.on_incognito_cleanup_ok.assert_not_called()
