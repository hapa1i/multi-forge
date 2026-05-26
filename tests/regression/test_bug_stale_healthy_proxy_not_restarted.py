"""Regression: a registry entry marked "healthy" whose process died must be restarted.

Bug: after the initial ``--proxy``/``--supervisor-proxy`` auto-start fix, ``ensure_proxy``
returned whatever ``resolve_proxy`` matched and trusted the persisted ``status``. A proxy
recorded as ``"healthy"`` whose process had since died (e.g. after a reboot/crash) was
handed back as if it were live, so the launcher reported "proxy is not running" (or the
supervisor failed at call time) instead of bringing the proxy back up -- the most common
form of the UX issue.

Root cause: ``ProxyRegistryStore.read()`` (src/forge/proxy/proxies.py) never prunes dead
pids -- ``prune_dead_pids`` only runs in explicit ``forge proxy`` commands -- and
``ensure_proxy`` (src/forge/proxy/proxy_orchestrator.py) short-circuited on the
``resolve_proxy`` hit without verifying liveness.

Fix: ``ensure_proxy`` routes every *template-name* match through ``start_proxy``, which
reuses a live proxy or adopts/spawns a fresh one. Stale "healthy" entries fail the reuse
healthcheck inside ``start_proxy`` and are persisted as unhealthy before replacement, so
the next template lookup does not become ambiguous. Bare proxy_ids stay presence-only.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.proxy.proxy_orchestrator import ensure_proxy

pytestmark = pytest.mark.regression

_ORCH = "forge.proxy.proxy_orchestrator"


def test_stale_healthy_template_entry_is_restarted() -> None:
    """resolve_proxy hits a status='healthy' entry whose pid is dead; ensure_proxy respawns."""
    stale = MagicMock(proxy_id="proxy_1", pid=999999)  # registry says healthy, process is gone
    fresh = MagicMock(proxy_id="proxy_2")

    with (
        patch(f"{_ORCH}.ProxyRegistryStore"),
        patch(f"{_ORCH}.resolve_proxy", return_value=stale),
        patch(f"{_ORCH}.template_exists", return_value=True),
        patch(f"{_ORCH}.start_proxy", return_value=MagicMock(proxy=fresh, source="spawn")) as start,
    ):
        entry, started = ensure_proxy("litellm-openai")

    # The resolve hit must NOT short-circuit a dead entry: start_proxy respawns.
    start.assert_called_once()
    assert start.call_args.kwargs["template"] == "litellm-openai"
    assert entry is fresh
    assert started is True


def test_live_template_entry_is_reused_not_respawned() -> None:
    """The companion case: start_proxy reports reuse, so started is False."""
    live = MagicMock(proxy_id="proxy_1", pid=4242)

    with (
        patch(f"{_ORCH}.ProxyRegistryStore"),
        patch(f"{_ORCH}.resolve_proxy", return_value=live),
        patch(f"{_ORCH}.template_exists", return_value=True),
        patch(f"{_ORCH}.start_proxy", return_value=MagicMock(proxy=live, source="reuse")) as start,
    ):
        entry, started = ensure_proxy("litellm-openai")

    start.assert_called_once()
    assert start.call_args.kwargs["template"] == "litellm-openai"
    assert entry is live
    assert started is False
