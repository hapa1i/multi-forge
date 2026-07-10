"""Tests for Claude sidecar launch plumbing."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from forge.core.ops.claude_session import (
    ClaudeSessionStartResult,
    ClaudeSidecarLaunch,
    ClaudeStartCreated,
    ClaudeStartExtensions,
    start_claude_session,
)
from forge.core.ops.session import ForgeOpError
from forge.core.reactive.env import (
    FORGE_FORGE_ROOT_VAR,
    FORGE_SIDECAR_HOST_FORGE_ROOT_VAR,
    FORGE_SIDECAR_HOST_WORKTREE_PATH_VAR,
)
from forge.session import LAUNCH_MODE_SIDECAR, SessionStore, create_session_state
from forge.session.models import SessionState


class _Presenter:
    def on_created(self, event: ClaudeStartCreated) -> None:
        pass

    def on_extensions(self, event: ClaudeStartExtensions) -> None:
        pass

    def on_no_launch(self) -> None:
        pass

    def before_launch(self, forge_root: Path) -> None:
        pass

    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None:
        pass

    def on_launch_error(self, error: ForgeOpError) -> None:
        raise error

    def on_incognito_cleanup_start(self) -> None:
        pass

    def on_incognito_cleanup_ok(self) -> None:
        pass

    def on_incognito_cleanup_warning(self, message: str) -> None:
        pass


class _FakeManager:
    def __init__(self, state: SessionState, store: SessionStore) -> None:
        self._state = state
        self._store = store

    def start_session(self, **kwargs: Any) -> SessionState:
        self._state.confirmed.claude_session_id = kwargs["claude_session_id"]
        self._store.write(self._state)
        return self._state


def _launch_split_root_sidecar(
    tmp_path: Path,
    *,
    prompt_file: Path | None = None,
) -> tuple[ClaudeSessionStartResult, Any, Path, Path]:
    forge_root = tmp_path / "main-repo"
    worktree = tmp_path / "checkout"
    forge_root.mkdir(exist_ok=True)
    worktree.mkdir(exist_ok=True)
    (worktree / ".claude").mkdir(exist_ok=True)

    state = create_session_state(
        "split-sidecar",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
        worktree_path=str(worktree),
        worktree_branch="split-sidecar",
        launch_mode=LAUNCH_MODE_SIDECAR,
    )
    assert state.worktree is not None
    state.worktree.is_worktree = True
    state.forge_root = str(forge_root)

    store = SessionStore(str(forge_root), state.name)
    store.write(state)

    def run_active(**kwargs: Any) -> int:
        return kwargs["runner"]()

    with (
        patch("forge.sidecar.docker.is_docker_available", return_value=True),
        patch("forge.sidecar.get_secrets_for_template", return_value={}),
        patch("forge.sidecar.run_sidecar_session", return_value=0) as run_sidecar,
    ):
        result = start_claude_session(
            manager=_FakeManager(state, store),  # type: ignore[arg-type]
            name=state.name,
            template="litellm-openai",
            base_url="http://localhost:8085",
            direct=False,
            incognito=False,
            worktree=True,
            branch=None,
            launch_mode=LAUNCH_MODE_SIDECAR,
            use_sidecar=True,
            mounts=(),
            image=None,
            no_launch=False,
            extensions=None,
            extra_args=None,
            context_limit_override=None,
            proxy_display=None,
            proxy_id=None,
            normalized_direct_model=None,
            prompt_file=str(prompt_file) if prompt_file is not None else None,
            memory_flag=None,
            subprocess_proxy=None,
            supervisor=None,
            presenter=_Presenter(),
            run_active=run_active,
        )

    return result, run_sidecar, forge_root, worktree


def test_sidecar_launch_mounts_session_forge_root_when_worktree_differs(
    tmp_path: Path,
) -> None:
    result, run_sidecar, forge_root, worktree = _launch_split_root_sidecar(tmp_path)

    assert result.exit_code == 0
    kwargs = run_sidecar.call_args.kwargs
    assert kwargs["project_dir"] == worktree
    assert kwargs["env_vars"][FORGE_FORGE_ROOT_VAR] == "/workspace"
    assert kwargs["env_vars"][FORGE_SIDECAR_HOST_FORGE_ROOT_VAR] == str(forge_root.resolve())
    assert kwargs["env_vars"][FORGE_SIDECAR_HOST_WORKTREE_PATH_VAR] == str(worktree.resolve())
    assert (str(worktree / ".claude"), "/workspace/.claude", "rw") in kwargs["extra_mounts"]
    assert (str(forge_root / ".forge"), "/workspace/.forge", "rw") in kwargs["extra_mounts"]
    assert (
        str(forge_root / ".forge" / "sidecar-home"),
        "/root/.claude",
        "rw",
    ) in kwargs["extra_mounts"]
    assert not (worktree / ".forge").exists()


def test_sidecar_launch_mounts_prompt_hidden_by_split_forge_root(tmp_path: Path) -> None:
    worktree = tmp_path / "checkout"
    prompt_file = worktree / ".forge" / "launch-context" / "split-sidecar.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("combined launch context\n", encoding="utf-8")

    result, run_sidecar, forge_root, _ = _launch_split_root_sidecar(tmp_path, prompt_file=prompt_file)

    assert result.exit_code == 0
    kwargs = run_sidecar.call_args.kwargs
    container_prompt = f"/tmp/{prompt_file.name}"
    assert (str(forge_root / ".forge"), "/workspace/.forge", "rw") in kwargs["extra_mounts"]
    assert (str(prompt_file.resolve()), container_prompt, "ro") in kwargs["extra_mounts"]
    prompt_arg = kwargs["claude_args"].index("--append-system-prompt-file")
    assert kwargs["claude_args"][prompt_arg + 1] == container_prompt
