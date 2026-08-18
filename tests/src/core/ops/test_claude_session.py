"""Focused tests for shared Claude session operation boundaries."""

import ast
import inspect
from pathlib import Path

import pytest

import forge.cli.session_fork as session_fork_cli
from forge.core.ops import claude_session as claude_session_ops
from forge.core.ops import session_fork_execution as fork_execution_ops
from forge.core.ops.claude_session import SupervisorWiring, launch_claude_session
from forge.core.ops.session import ForgeOpError
from forge.session import SessionState, SessionStore, create_session_state


def _resolve(state: SessionState, *, cwd: Path) -> claude_session_ops.ClaudeSessionStateContext:
    return claude_session_ops.resolve_claude_session_state_context(state, cwd=cwd)


def test_state_context_uses_durable_root_and_recorded_worktree(tmp_path: Path) -> None:
    forge_root = tmp_path / "nested-project"
    worktree = tmp_path / "relocated-checkout"
    shell = tmp_path / "unrelated-shell"
    state = create_session_state("worker", worktree_path=str(worktree))
    state.forge_root = str(forge_root)

    context = _resolve(state, cwd=shell)

    assert context.worktree_path == worktree
    assert context.forge_root == forge_root
    assert context.store.forge_root == forge_root.resolve()
    assert context.store.session_name == "worker"


def test_state_context_uses_recorded_worktree_for_legacy_missing_root(tmp_path: Path) -> None:
    worktree = tmp_path / "legacy-checkout"
    state = create_session_state("legacy", worktree_path=str(worktree))

    context = _resolve(state, cwd=tmp_path / "unrelated-shell")

    assert context.worktree_path == worktree
    assert context.forge_root == worktree
    assert context.store.forge_root == worktree.resolve()


def test_state_context_uses_explicit_cwd_only_when_no_durable_path_exists(tmp_path: Path) -> None:
    shell = tmp_path / "legacy-shell"
    state = create_session_state("legacy")

    context = _resolve(state, cwd=shell)

    assert context.worktree_path == shell
    assert context.forge_root == shell
    assert context.store.forge_root == shell.resolve()


def test_state_context_does_not_treat_a_missing_worktree_as_state_loss(tmp_path: Path) -> None:
    forge_root = tmp_path / "project"
    missing = tmp_path / "missing-checkout"
    state = create_session_state("degraded", worktree_path=str(missing))
    state.forge_root = str(forge_root)

    context = _resolve(state, cwd=tmp_path / "unrelated-shell")

    assert context.worktree_path == missing
    assert context.forge_root == forge_root
    assert context.store.forge_root == forge_root.resolve()


def test_post_create_mutations_use_resolved_store_outside_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forge_root = tmp_path / "project"
    worktree = tmp_path / "checkout"
    shell = tmp_path / "unrelated-shell"
    supervisor_root = tmp_path / "supervisor-project"
    for path in (forge_root, worktree, shell, supervisor_root):
        path.mkdir()
    monkeypatch.chdir(shell)

    state = create_session_state("worker", worktree_path=str(worktree))
    state.forge_root = str(forge_root)
    store = SessionStore(str(forge_root), state.name)
    store.write(state)
    context = _resolve(state, cwd=shell)

    state = claude_session_ops._apply_memory_activation(context)
    context = _resolve(state, cwd=shell)
    state = claude_session_ops._apply_subprocess_proxy(context, "subprocess-proxy")
    context = _resolve(state, cwd=shell)

    supervisor = create_session_state("planner", worktree_path=str(supervisor_root))
    supervisor.forge_root = str(supervisor_root)
    state = claude_session_ops.apply_supervisor_wiring(
        context,
        SupervisorWiring(
            target="planner",
            source_state=supervisor,
            supervisor_proxy=None,
            supervisor_direct=True,
            cascade=False,
            checker_model=None,
            checker_provider=None,
            checker_effort=None,
            supervisor_effort=None,
            supervisor_runtime=None,
        ),
        proxy_id=None,
        template=None,
        direct=True,
    )

    persisted = store.read()
    assert persisted == state
    assert persisted.intent.memory is not None
    assert persisted.intent.memory.auto_update is not None
    assert persisted.intent.memory.auto_update.enabled is True
    assert persisted.intent.subprocess_proxy == "subprocess-proxy"
    assert persisted.intent.policy is not None
    assert persisted.intent.policy.supervisor is not None
    assert persisted.intent.policy.supervisor.forge_root == str(supervisor_root)
    assert not SessionStore(str(shell), state.name).exists()


def test_post_create_mutations_fall_back_to_worktree_not_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = tmp_path / "legacy-checkout"
    shell = tmp_path / "unrelated-shell"
    worktree.mkdir()
    shell.mkdir()
    monkeypatch.chdir(shell)

    state = create_session_state("legacy", worktree_path=str(worktree))
    store = SessionStore(str(worktree), state.name)
    store.write(state)
    context = _resolve(state, cwd=shell)

    state = claude_session_ops._apply_memory_activation(context)
    context = _resolve(state, cwd=shell)
    claude_session_ops._apply_subprocess_proxy(context, "subprocess-proxy")

    persisted = store.read()
    assert persisted.intent.memory is not None
    assert persisted.intent.memory.auto_update is not None
    assert persisted.intent.memory.auto_update.enabled is True
    assert persisted.intent.subprocess_proxy == "subprocess-proxy"
    assert not SessionStore(str(shell), state.name).exists()


def test_state_context_structural_drift_reminders() -> None:
    # These source checks are cheap reminders; the behavioral cases above own correctness.
    for operation in (
        claude_session_ops.start_claude_session,
        claude_session_ops.launch_claude_session,
        claude_session_ops.resume_claude_session,
        claude_session_ops.fork_claude_session,
    ):
        assert "resolve_claude_session_state_context" in inspect.getsource(operation)

    for mutation in (
        claude_session_ops._apply_memory_activation,
        claude_session_ops._apply_subprocess_proxy,
        claude_session_ops.apply_supervisor_wiring,
    ):
        source = inspect.getsource(mutation)
        assert "context.store" in source
        assert "Path.cwd" not in source
        assert "SessionStore(" not in source

    cli_tree = ast.parse(inspect.getsource(session_fork_cli))
    cli_fork = next(node for node in cli_tree.body if isinstance(node, ast.FunctionDef) and node.name == "fork")
    calls = {
        node.func.id for node in ast.walk(cli_fork) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    local_store_imports = [
        alias
        for node in ast.walk(cli_fork)
        if isinstance(node, ast.ImportFrom) and node.module == "forge.session"
        for alias in node.names
        if alias.name == "SessionStore"
    ]
    context_store_reads = [
        node
        for node in ast.walk(cli_fork)
        if isinstance(node, ast.Attribute)
        and node.attr == "store"
        and isinstance(node.value, ast.Name)
        and node.value.id == "fork_state_context"
    ]
    assert "execute_session_fork" in calls
    assert not local_store_imports

    execution_source = inspect.getsource(fork_execution_ops._prepare_created_fork)
    assert "resolve_claude_session_state_context" in execution_source
    assert "Path.cwd" not in execution_source
    assert "SessionStore(" not in execution_source
    assert not context_store_reads


def test_launch_refuses_missing_recorded_worktree_before_callbacks(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "deleted-worktree"
    state = create_session_state("degraded", worktree_path=str(missing))
    callbacks: list[str] = []

    def record_invoke(**_kwargs: object) -> int:
        callbacks.append("invoke")
        return 0

    with pytest.raises(ForgeOpError) as exc_info:
        launch_claude_session(
            manifest=state,
            session_id=None,
            resume_id=None,
            effective_template=None,
            runtime_base_url=None,
            context_limit=200_000,
            use_sidecar=False,
            before_launch=lambda _path: callbacks.append("before_launch"),
            invoke=record_invoke,
            run_active=lambda runner, **_kwargs: runner(),
        )

    message = str(exc_info.value)
    assert "cannot launch session 'degraded'" in message
    assert str(missing) in message
    assert "forge session delete degraded" in message
    assert callbacks == []
