"""Launch environments must carry the admitted target's instance across runtime boundaries."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from forge.core.ops.claude_session import launch_claude_session
from forge.core.ops.codex_bridge import _temporary_run_env
from forge.core.ops.codex_session import continue_codex_session, start_codex_session
from forge.core.reactive.env import new_root_run_identity
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.hooks.producers import capture_hook_instance
from forge.session.workers import SESSION_INSTANCE_ENV, session_worker_lease
from tests.fixtures.session_state import publish_session
from tests.src.core.ops.test_claude_sidecar_launch import _proxy_routing_payload
from tests.src.core.ops.test_codex_session import (
    _codex_mocks,
    _make_project,
    _seed_codex_session,
)

pytestmark = pytest.mark.regression


@pytest.mark.parametrize("use_sidecar", [False, True])
def test_ownerless_v1_launch_exports_migrated_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_sidecar: bool
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    monkeypatch.chdir(root)
    state = create_session_state(
        "legacy",
        worktree_path=str(root),
        launch_mode="sidecar" if use_sidecar else "host",
        proxy_template="litellm-openai",
        proxy_base_url="http://localhost:8085",
    )
    index = IndexStore()
    publish_session(index, state, root, forge_root=root)
    store = SessionStore(str(root), state.name)
    # Model an actual pre-identity session: v1 index and manifest, with no owner file.
    old_index = json.loads(index.index_path.read_text())
    old_index["version"] = 1
    for row in old_index["sessions"].values():
        row.pop("instance_id")
    index.index_path.write_text(json.dumps(old_index))
    old_manifest = json.loads(store.manifest_path.read_text())
    old_manifest["schema_version"] = 1
    old_manifest["intent"]["launch"].pop("model_route")
    store.manifest_path.write_text(json.dumps(old_manifest))
    (store.session_dir / "review-identity").unlink()
    legacy = store.read()
    entry = index.peek_session(state.name, str(root))
    assert entry is not None and entry.instance_id is None
    assert store.review_identity() is None
    invoke = Mock(return_value=0)

    with (
        patch("forge.sidecar.docker.is_docker_available", return_value=True),
        patch("forge.sidecar.docker.require_sidecar_contract"),
        patch("forge.sidecar.get_secrets_for_template", return_value={}),
        patch("forge.session.workers._sidecar_exit_confirmed", return_value=True),
        patch("forge.sidecar.run_sidecar_session", return_value=0) as run_sidecar,
        patch("forge.core.ops.claude_session.build_claude_routing_payload", return_value=_proxy_routing_payload()),
    ):
        result = launch_claude_session(
            manifest=legacy,
            session_id=None,
            resume_id=None,
            effective_template="litellm-openai",
            runtime_base_url="http://localhost:8085",
            context_limit=200000,
            use_sidecar=use_sidecar,
            run_active=lambda **kwargs: kwargs["runner"](),
            invoke=invoke,
        )

    assert result.exit_code == 0
    token = store.review_identity()
    assert token is not None
    assert index.get_session(state.name, str(root)).instance_id == token
    if use_sidecar:
        assert run_sidecar.call_args.kwargs["env_vars"][SESSION_INSTANCE_ENV] == token
    else:
        assert invoke.call_args.kwargs["env_vars"][SESSION_INSTANCE_ENV] == token
        assert SESSION_INSTANCE_ENV not in invoke.call_args.kwargs["unset_env_vars"]


@pytest.mark.parametrize("operation", ["start", "resume"])
@pytest.mark.parametrize("fail", [False, True])
def test_nested_headless_target_hook_admission_and_caller_restoration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, fail: bool
) -> None:
    root, ctx = _make_project(tmp_path, monkeypatch)
    parent_token = SessionStore(str(root), "planner").review_identity()
    assert parent_token is not None
    caller = {
        "FORGE_SESSION": "planner",
        "FORGE_FORGE_ROOT": str(root),
        SESSION_INSTANCE_ENV: parent_token,
        "FORGE_RUN_ID": "caller-run",
        "FORGE_ROOT_RUN_ID": "caller-root",
        "FORGE_PARENT_RUN_ID": "caller-parent",
    }
    for key, value in caller.items():
        monkeypatch.setenv(key, value)
    if operation == "resume":
        _seed_codex_session(root)
    observed: list[str] = []

    def admit_target_hook() -> None:
        assert os.environ["FORGE_SESSION"] == "impl"
        store = SessionStore(os.environ["FORGE_FORGE_ROOT"], "impl")
        token = capture_hook_instance(store)
        assert token != parent_token
        assert token == store.review_identity()
        with session_worker_lease(store.forge_root, "impl", expected_instance_id=token, label="target hook"):
            store.update(
                timeout_s=1,
                mutate=lambda state: setattr(state.confirmed, "confirmed_by", "hook:target"),
                expected_instance_id=token,
            )
        observed.append(token)

    def failed_invocation(request: Any) -> None:
        assert request.env[SESSION_INSTANCE_ENV] == os.environ[SESSION_INSTANCE_ENV]
        admit_target_hook()
        raise RuntimeError("native invocation failed")

    def run() -> None:
        if operation == "start":
            start_codex_session(ctx=ctx, name="impl", parent="planner", task="Synthetic task")
        else:
            continue_codex_session(ctx=ctx, name="impl", task="Synthetic continuation")

    with _codex_mocks(on_codex_spawn=admit_target_hook) as codex:
        if fail:
            with patch("forge.core.invoker.CodexHeadlessInvoker.run", side_effect=failed_invocation):
                with pytest.raises(RuntimeError, match="native invocation failed"):
                    run()
        else:
            run()
            assert len(observed) == 1
            assert codex.call.kwargs["env"][SESSION_INSTANCE_ENV] == observed[0]

    assert len(observed) == 1
    assert {key: os.environ.get(key) for key in caller} == caller
    assert SessionStore(str(root), "planner").review_identity() == parent_token


@pytest.mark.parametrize("inherited", [None, "a" * 32])
def test_temporary_run_env_scrubs_uncaptured_owner_and_restores_on_failure(
    monkeypatch: pytest.MonkeyPatch, inherited: str | None
) -> None:
    if inherited is None:
        monkeypatch.delenv(SESSION_INSTANCE_ENV, raising=False)
    else:
        monkeypatch.setenv(SESSION_INSTANCE_ENV, inherited)
    with pytest.raises(RuntimeError, match="probe failed"):
        with _temporary_run_env(new_root_run_identity(), "enrollment-probe"):
            assert os.environ.get(SESSION_INSTANCE_ENV) is None
            raise RuntimeError("probe failed")
    assert os.environ.get(SESSION_INSTANCE_ENV) == inherited
