"""Regression for O054: fresh resume modes share routing-reference precedence.

The production CLI resolver supplies both a proxy id and template, while legacy and
injected routing can be template-only. Every fresh mode must use the shared fallback
instead of reimplementing a narrower proxy-id-only calculation.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.cli.session import _resolve_routing_from_cli
from forge.cli.session_lifecycle import _resume_context_ref
from forge.cli.session_routing import ResolvedRouting
from forge.proxy.proxies import ProxyEntry
from forge.session import create_session_state
from forge.session.models import StartedWithProxy

pytestmark = pytest.mark.regression


def test_resume_context_ref_prefers_explicit_proxy_id() -> None:
    state = create_session_state("parent")
    routing = ResolvedRouting(template="openrouter-kimi", proxy_id="openrouter-kimi-1234")

    assert _resume_context_ref(state=state, routing=routing, direct=False) == "openrouter-kimi-1234"


def test_resume_context_ref_falls_back_to_explicit_template() -> None:
    state = create_session_state("parent")
    routing = ResolvedRouting(template="openrouter-kimi")

    assert _resume_context_ref(state=state, routing=routing, direct=False) == "openrouter-kimi"


def test_resume_context_ref_prefers_inherited_proxy_id() -> None:
    state = create_session_state("parent")
    state.confirmed.started_with_proxy = StartedWithProxy(
        base_url="http://localhost:8090",
        proxy_id="openrouter-kimi-1234",
        template="openrouter-kimi",
    )

    assert _resume_context_ref(state=state, routing=None, direct=False) == "openrouter-kimi-1234"


def test_resume_context_ref_falls_back_to_legacy_inherited_template() -> None:
    state = create_session_state(
        "parent",
        proxy_template="openrouter-kimi",
        proxy_base_url="http://localhost:8090",
    )

    assert _resume_context_ref(state=state, routing=None, direct=False) == "openrouter-kimi"


def test_resume_context_ref_returns_none_for_direct_override() -> None:
    state = create_session_state(
        "parent",
        proxy_template="openrouter-kimi",
        proxy_base_url="http://localhost:8090",
    )

    assert _resume_context_ref(state=state, routing=None, direct=True) is None


def test_every_fresh_resume_mode_calls_only_the_shared_reference() -> None:
    repo = Path(__file__).resolve().parents[2]
    functions = (
        (repo / "src/forge/cli/session_lifecycle.py", "_resume_fresh"),
        (repo / "src/forge/cli/session_resume_modes.py", "_resume_fresh_native"),
        (repo / "src/forge/cli/session_resume_modes.py", "_resume_fresh_rewind"),
    )

    for path, function_name in functions:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function_name)
        shared_calls = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_resume_context_ref"
        ]
        direct_routing_reads = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "routing"
            and node.attr in {"proxy_id", "template"}
        ]

        assert len(shared_calls) == 1, function_name
        assert direct_routing_reads == [], function_name


def test_resolve_routing_from_cli_proxy_path_returns_proxy_id() -> None:
    entry = ProxyEntry(
        proxy_id="openrouter-kimi-1234",
        template="openrouter-kimi",
        base_url="http://localhost:8090",
        port=8090,
    )

    with (
        patch("forge.proxy.proxy_orchestrator.ensure_proxy", return_value=(entry, False)),
        patch("forge.cli.claude._healthcheck_proxy"),
        patch("forge.session.context_limit._get_context_limit_for_proxy", return_value=1048576),
    ):
        routing = _resolve_routing_from_cli(proxy_name="openrouter-kimi", direct=False)

    assert routing.template == "openrouter-kimi"
    assert routing.proxy_id == "openrouter-kimi-1234"
    assert routing.base_url == "http://localhost:8090"
    assert routing.context_limit == 1048576


def test_resolve_routing_from_cli_direct_path_has_no_template_or_proxy_id() -> None:
    routing = _resolve_routing_from_cli(proxy_name=None, direct=True)

    assert routing.template is None
    assert routing.proxy_id is None
    assert routing.base_url is None
