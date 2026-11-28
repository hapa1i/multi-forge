"""Only one proxied Codex resume may launch from a given preflight snapshot."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from forge.core.ops.session import ForgeOpError
from forge.core.ops.session_routing import (
    build_codex_proxy_routing_payload,
    commit_launch_routing,
)
from forge.core.reactive.env import new_root_run_identity
from forge.core.runtime.codex_proxy_launch import CodexProxyLaunch
from forge.session import SessionStore, create_session_state
from forge.session.routing import codex_proxy_commits, read_routing_events

pytestmark = pytest.mark.regression


def test_two_resumes_from_the_same_predecessor_publish_one_commit(tmp_path: Path) -> None:
    launch = CodexProxyLaunch(
        "bound", "codex-responses-local", "http://127.0.0.1:8080", "local", "litellm", "model", "model", None
    )
    state = create_session_state(
        "work",
        runtime="codex",
        proxy_id=launch.proxy_id,
        proxy_template=launch.template,
        proxy_base_url=launch.base_url,
    )
    store = SessionStore(str(tmp_path), state.name)
    store.write(state)
    instance = store.review_identity(create=True)
    assert instance
    payload = build_codex_proxy_routing_payload(launch, instance)
    commit_launch_routing(
        store=store,
        state=state,
        root=new_root_run_identity(),
        operation="start",
        payload=payload,
        authority_attempt=None,
    )
    before_commit = Barrier(2)

    def resume() -> str | None:
        planned = store.read()
        run = new_root_run_identity()
        before_commit.wait(timeout=5)
        try:
            commit_launch_routing(
                store=store, state=planned, root=run, operation="resume", payload=payload, authority_attempt=None
            )
        except ForgeOpError as exc:
            assert "changed during preflight" in str(exc)
            return None
        return run.run_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(resume) for _ in range(2)]
        outcomes = [future.result(timeout=10) for future in futures]
    (winner,) = [run for run in outcomes if run is not None]
    final = store.read()
    assert final.confirmed.route_commit and final.confirmed.route_commit.run_id == winner
    assert [event.operation for event in read_routing_events(tmp_path, final)] == ["start", "resume"]
    assert codex_proxy_commits(tmp_path, final, instance)[-1].run_id == winner
