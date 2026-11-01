"""Regression: SessionStart must not attribute a session to a stale proxy on its port.

``forge session start --proxy <template>`` spawns a new proxy id on the template's
default port whenever no instance is live, so stopped instances accumulate on one
base_url. The hook recovered the proxy id by reverse URL lookup and took the first
registry match: the oldest stopped instance. Bare resume then refused the live
proxy with ``proxy_id mismatch`` and only an explicit ``--proxy`` relaunch worked,
after which the hook recorded the stale id again.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.ops.claude_session import get_effective_proxy_for_resume
from forge.proxy.proxies import ProxyEntry, ProxyRegistry, ProxyRegistryStore
from forge.session import IndexStore, SessionStore, create_session_state
from forge.session.hooks import HookInput, handle_session_start
from tests.fixtures.session_state import publish_session

pytestmark = pytest.mark.regression

_TEMPLATE = "openrouter-gemini"
_BASE_URL = "http://localhost:8097"


def _entry(proxy_id: str, *, status: str, pid: int | None) -> ProxyEntry:
    return ProxyEntry(proxy_id=proxy_id, template=_TEMPLATE, base_url=_BASE_URL, port=8097, pid=pid, status=status)


def _start_session(tmp_path: Path, entries: list[ProxyEntry]) -> SessionStore:
    # Registration order matters: the stale instance precedes the live one, as in
    # the reported index where the oldest stopped proxy was the first URL match.
    ProxyRegistryStore().write(ProxyRegistry(proxies={entry.proxy_id: entry for entry in entries}))
    (tmp_path / ".claude").mkdir()
    index = IndexStore(tmp_path / "index.json")
    state = create_session_state("bizarre-pony", proxy_template=_TEMPLATE, proxy_base_url=_BASE_URL)
    publish_session(index, state, tmp_path, forge_root=tmp_path)

    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "FORGE_HOME", "CLAUDE_HOME", "CLAUDE_CONFIG_DIR", "CODEX_HOME"}
    }
    env.update({"FORGE_SESSION": "bizarre-pony", "ANTHROPIC_BASE_URL": _BASE_URL, "ACTIVE_TEMPLATE": _TEMPLATE})
    hook_input = HookInput(session_id="conversation-uuid", transcript_path="/tmp/transcript.jsonl", source="startup")
    with patch.dict(os.environ, env, clear=True):
        result = handle_session_start(hook_input, tmp_path, index)
    assert result.success
    return SessionStore(str(tmp_path), "bizarre-pony")


def test_session_start_records_live_proxy_over_earlier_stale_instance(tmp_path: Path) -> None:
    store = _start_session(
        tmp_path,
        [
            _entry("golden-citron", status="unhealthy", pid=None),
            _entry("crimson-papaya", status="unhealthy", pid=None),
            _entry("amber-fig", status="healthy", pid=62449),
        ],
    )

    manifest = store.read()
    assert manifest.confirmed.started_with_proxy is not None
    assert manifest.confirmed.started_with_proxy.proxy_id == "amber-fig"
    # Bare resume validates the live proxy against exactly this recorded identity.
    assert get_effective_proxy_for_resume(manifest) == (_TEMPLATE, _BASE_URL, "amber-fig")


def test_session_start_leaves_proxy_id_unknown_when_live_owner_is_ambiguous(tmp_path: Path) -> None:
    # A crashed proxy can keep a healthy status beside its replacement. Recording
    # neither keeps resume on template validation instead of a guessed identity.
    store = _start_session(
        tmp_path,
        [
            _entry("golden-citron", status="healthy", pid=999_999),
            _entry("amber-fig", status="healthy", pid=62449),
        ],
    )

    swp = store.read().confirmed.started_with_proxy
    assert swp is not None
    assert swp.proxy_id is None
    assert swp.template == _TEMPLATE
