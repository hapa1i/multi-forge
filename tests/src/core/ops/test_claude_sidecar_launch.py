"""Tests for Claude sidecar launch plumbing."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from forge.core.ops.claude_session import (
    ClaudeSessionLaunchResult,
    ClaudeSessionStartResult,
    ClaudeSidecarLaunch,
    ClaudeStartCreated,
    ClaudeStartExtensions,
    launch_claude_session,
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
from forge.session.routing import derive_routing_history


class _Presenter:
    def __init__(self) -> None:
        self.sidecar_launch: ClaudeSidecarLaunch | None = None

    def on_created(self, event: ClaudeStartCreated) -> None:
        pass

    def on_extensions(self, event: ClaudeStartExtensions) -> None:
        pass

    def on_no_launch(self) -> None:
        pass

    def before_launch(self, forge_root: Path) -> None:
        pass

    def on_routing_payload(self, payload: dict[str, Any]) -> None:
        pass

    def on_sidecar_launch(self, event: ClaudeSidecarLaunch) -> None:
        self.sidecar_launch = event

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


@dataclass(frozen=True)
class _SidecarFixture:
    result: ClaudeSessionStartResult
    launch_result: ClaudeSessionLaunchResult
    run_sidecar: Any
    build_routing_payload: Any
    store: SessionStore
    forge_root: Path
    worktree: Path
    presenter: _Presenter


def _proxy_routing_payload(*, proxy_id: str | None = None) -> dict[str, Any]:
    return {
        "route": {
            "kind": "proxy",
            "backend_id": None,
            "proxy_id": proxy_id,
            "template": "litellm-openai",
            "custom_route_fingerprint": None,
            "wire_shape": "openai_translated",
        },
        "requested_model": None,
        "selected_tier": None,
        "selected_model": None,
        "default_tier": "sonnet",
        "direct_model": None,
        "tier_mappings": {"sonnet": "openai/gpt-5"},
        "model_alternatives": {},
        "billing_mode": "unknown",
        "route_scope_tags": ["route:proxy", "runtime:claude_code"],
        "marking_snapshots": [
            {
                "slot": "tier_default",
                "tier": "sonnet",
                "request_model": None,
                "route_model": "openai/gpt-5",
                "canonical_model": "gpt-5",
                "declaration": {
                    "status": "unknown",
                    "basis": None,
                    "source_url": None,
                    "checked_at": None,
                    "effective_from": None,
                    "route_scope": [],
                },
            }
        ],
    }


def _launch_split_root_sidecar(
    tmp_path: Path,
    *,
    prompt_file: Path | None = None,
    resolved_proxy_id: str | None = None,
) -> _SidecarFixture:
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

    presenter = _Presenter()
    launch_results: list[ClaudeSessionLaunchResult] = []

    def capture_launch(**kwargs: Any) -> ClaudeSessionLaunchResult:
        launch_result = launch_claude_session(**kwargs)
        launch_results.append(launch_result)
        return launch_result

    with ExitStack() as stack:
        stack.enter_context(patch("forge.sidecar.docker.is_docker_available", return_value=True))
        stack.enter_context(patch("forge.sidecar.get_secrets_for_template", return_value={}))
        run_sidecar = stack.enter_context(patch("forge.sidecar.run_sidecar_session", return_value=0))
        build_routing_payload = stack.enter_context(
            patch(
                "forge.core.ops.claude_session.build_claude_routing_payload",
                return_value=_proxy_routing_payload(proxy_id=resolved_proxy_id),
            )
        )
        stack.enter_context(patch("forge.core.ops.claude_session.launch_claude_session", side_effect=capture_launch))
        if resolved_proxy_id is not None:
            stack.enter_context(patch("forge.proxy.proxies.recover_proxy_id_from_base_url", return_value=None))
            stack.enter_context(patch("forge.proxy.proxies.ProxyRegistryStore.read", return_value=object()))
            stack.enter_context(
                patch(
                    "forge.proxy.proxies.resolve_proxy_optional",
                    return_value=SimpleNamespace(proxy_id=resolved_proxy_id),
                )
            )
            stack.enter_context(
                patch(
                    "forge.config.loader.load_proxy_instance_config",
                    return_value=SimpleNamespace(upstream_base_url="https://api.example.test"),
                )
            )
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
            presenter=presenter,
            run_active=run_active,
        )

    return _SidecarFixture(
        result=result,
        launch_result=launch_results[0],
        run_sidecar=run_sidecar,
        build_routing_payload=build_routing_payload,
        store=store,
        forge_root=forge_root,
        worktree=worktree,
        presenter=presenter,
    )


def test_sidecar_launch_mounts_session_forge_root_when_worktree_differs(
    tmp_path: Path,
) -> None:
    fixture = _launch_split_root_sidecar(tmp_path)

    assert fixture.result.exit_code == 0
    kwargs = fixture.run_sidecar.call_args.kwargs
    assert kwargs["project_dir"] == fixture.worktree
    assert kwargs["env_vars"][FORGE_FORGE_ROOT_VAR] == "/workspace"
    assert kwargs["env_vars"][FORGE_SIDECAR_HOST_FORGE_ROOT_VAR] == str(fixture.forge_root.resolve())
    assert kwargs["env_vars"][FORGE_SIDECAR_HOST_WORKTREE_PATH_VAR] == str(fixture.worktree.resolve())
    assert (str(fixture.worktree / ".claude"), "/workspace/.claude", "rw") in kwargs["extra_mounts"]
    assert (str(fixture.forge_root / ".forge"), "/workspace/.forge", "rw") in kwargs["extra_mounts"]
    assert (
        str(fixture.forge_root / ".forge" / "sidecar-home"),
        "/root/.claude",
        "rw",
    ) in kwargs["extra_mounts"]
    assert not (fixture.worktree / ".forge").exists()


def test_sidecar_launch_mounts_prompt_hidden_by_split_forge_root(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "checkout"
    prompt_file = worktree / ".forge" / "launch-context" / "split-sidecar.md"
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("combined launch context\n", encoding="utf-8")

    fixture = _launch_split_root_sidecar(tmp_path, prompt_file=prompt_file)

    assert fixture.result.exit_code == 0
    kwargs = fixture.run_sidecar.call_args.kwargs
    container_prompt = f"/tmp/{prompt_file.name}"
    assert (str(fixture.forge_root / ".forge"), "/workspace/.forge", "rw") in kwargs["extra_mounts"]
    assert (str(prompt_file.resolve()), container_prompt, "ro") in kwargs["extra_mounts"]
    prompt_arg = kwargs["claude_args"].index("--append-system-prompt-file")
    assert kwargs["claude_args"][prompt_arg + 1] == container_prompt


def test_template_resolution_changes_only_routing_proxy_identity(tmp_path: Path) -> None:
    fixture = _launch_split_root_sidecar(tmp_path, resolved_proxy_id="resolved-proxy")

    assert fixture.build_routing_payload.call_args.kwargs["proxy_id"] == "resolved-proxy"
    history = derive_routing_history(fixture.store.forge_root, fixture.store.read())
    assert history.effective_commit is not None
    assert history.effective_commit.payload["route"]["proxy_id"] == "resolved-proxy"

    assert fixture.run_sidecar.call_args.kwargs["proxy_id"] is None
    assert fixture.presenter.sidecar_launch is not None
    assert fixture.presenter.sidecar_launch.proxy_id is None
    assert fixture.launch_result.proxy_id is None
    launch = fixture.store.read().confirmed.launch
    assert launch is not None
    assert launch.proxy_id is None
