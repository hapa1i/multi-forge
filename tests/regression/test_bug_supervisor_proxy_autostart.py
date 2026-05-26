"""Regression: ``--supervisor-proxy <template>`` must auto-start, not hard-error.

Bug: ``forge session fork planner --name executor --supervise --supervisor-proxy
openrouter-deepseek`` failed with "Error: Supervisor proxy 'openrouter-deepseek' not
found in registry" whenever a *template* of that name existed but no proxy was running
yet. The user reasonably expected Forge to bring the proxy up.

Root cause: ``preflight_supervisor_proxy`` (now ``ensure_supervisor_proxy``,
src/forge/guard/semantic/supervisor.py) resolved only against the runtime registry and
hard-failed on a miss -- it never fell back to the matching template.

Fix: ``ensure_supervisor_proxy`` delegates to ``ensure_proxy``
(src/forge/proxy/proxy_orchestrator.py), which starts a proxy from a matching template.
A genuine no-proxy/no-template name now fails with an actionable message that points at
``forge proxy template list`` instead of the opaque "not found in registry".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from forge.guard.semantic.supervisor import ensure_supervisor_proxy

pytestmark = pytest.mark.regression

_ORCH = "forge.proxy.proxy_orchestrator"


def test_supervisor_proxy_template_autostarts_instead_of_erroring() -> None:
    """A --supervisor-proxy naming a template with no running proxy auto-starts it.

    Exercises the real ensure_supervisor_proxy -> ensure_proxy path; only the actual
    server spawn (start_proxy) and registry/template lookups are mocked.
    """
    from forge.proxy.proxies import ProxyNotFoundError

    started = MagicMock(proxy_id="openrouter-deepseek")
    with (
        patch(f"{_ORCH}.ProxyRegistryStore"),
        patch(f"{_ORCH}.resolve_proxy", side_effect=ProxyNotFoundError("openrouter-deepseek")),
        patch(f"{_ORCH}.template_exists", return_value=True),
        patch(f"{_ORCH}.start_proxy", return_value=MagicMock(proxy=started, source="spawn")) as start,
    ):
        proxy_id, was_started = ensure_supervisor_proxy("openrouter-deepseek")

    assert proxy_id == "openrouter-deepseek"
    assert was_started is True
    assert start.call_args.kwargs["template"] == "openrouter-deepseek"


def test_unknown_supervisor_proxy_gives_actionable_error() -> None:
    """No proxy and no template -> actionable message, not the old registry jargon."""
    from forge.proxy.proxies import ProxyNotFoundError

    with (
        patch(f"{_ORCH}.ProxyRegistryStore"),
        patch(f"{_ORCH}.resolve_proxy", side_effect=ProxyNotFoundError("typo-proxy")),
        patch(f"{_ORCH}.template_exists", return_value=False),
    ):
        with pytest.raises(ValueError) as exc:
            ensure_supervisor_proxy("typo-proxy")

    msg = str(exc.value)
    assert "forge proxy template list" in msg
    assert "not found in registry" not in msg
