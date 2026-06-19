"""Regression: custom proxy templates must preflight credentials from their declared source.

Bug: ``unified_backend`` keyed credential lookup on ``TEMPLATE_ENV_VARS``, a map built only
from shipped catalog aliases. A user-named template (arbitrary filename) was absent from that
map, so ``_ensure_template_credentials`` saw an empty required-vars list and returned early --
skipping credential preflight entirely. The proxy then launched without its API key and failed
at runtime instead of failing fast at start.

Root cause: filename-keyed credential resolution ignored the template's declared ``proxy.source``.
Fix: ``required_env_vars_for_template`` reads ``proxy.source`` and resolves required env vars from
the model-source catalog, falling back to ``TEMPLATE_ENV_VARS`` only when no source is readable.

Affected files:
- src/forge/core/auth/template_secrets.py
- src/forge/proxy/proxy_orchestrator.py
"""

from __future__ import annotations

import pytest

from forge.proxy.proxy_orchestrator import ProxyStartError, _ensure_template_credentials

pytestmark = pytest.mark.regression

_CUSTOM_TEMPLATE = (
    "proxy:\n"
    "  family: anthropic\n"
    "  preferred_provider: openrouter\n"
    "  source: openrouter\n"
    "  default_port: 9101\n"
    "  openrouter:\n"
    "    tiers:\n"
    "      sonnet: anthropic/claude-sonnet-4.6\n"
)


def test_custom_template_preflights_declared_source_credentials(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A custom-named template with ``proxy.source: openrouter`` must require OPENROUTER_API_KEY.

    Pre-fix this raised nothing (preflight skipped because the name was absent from
    ``TEMPLATE_ENV_VARS``); the source-derived lookup now fails fast at start.
    """
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    (templates_dir / "custom-openrouter.yaml").write_text(_CUSTOM_TEMPLATE)

    with pytest.raises(ProxyStartError, match="OPENROUTER_API_KEY"):
        _ensure_template_credentials("custom-openrouter")
