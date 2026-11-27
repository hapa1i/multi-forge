"""A native-ready host must not publish a sessionless Forge proxy thread as direct."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from forge.core.ops.codex_adopt import adopt_codex_session, plan_codex_adoption
from forge.core.ops.context import ExecutionContext
from forge.core.ops.session_adopt import AdoptError
from forge.session import SessionStore
from forge.session.index import IndexStore
from tests.fixtures.review_workers import make_codex_preflight

pytestmark = pytest.mark.regression


def test_proxy_alias_refused_at_plan_and_binding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    (project / ".forge").mkdir(parents=True)
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setattr("forge.core.ops.codex_adopt.assert_codex_ready", make_codex_preflight)
    thread_id = str(uuid4())
    day = home / "sessions/2026/11/27"
    day.mkdir(parents=True)
    path = day / f"rollout-2026-11-27T00-00-00-{thread_id}.jsonl"
    payload = {"id": thread_id, "cwd": str(project), "model_provider": "openai"}
    metadata = {"type": "session_meta", "payload": payload}
    path.write_text(json.dumps(metadata) + "\n")
    ctx = ExecutionContext.from_cwd(project)
    plan = plan_codex_adoption(ctx, thread_id)

    payload["model_provider"] = "forge_proxy"
    path.write_text(json.dumps(metadata) + "\n")
    with pytest.raises(AdoptError, match="cannot identify the original Forge proxy"):
        plan_codex_adoption(ctx, thread_id)
    with pytest.raises(AdoptError, match="cannot identify the original Forge proxy"):
        adopt_codex_session(ctx, plan, name="rejected")
    assert not SessionStore(str(project), "rejected").exists()
    assert IndexStore().peek_session("rejected", str(project)) is None
