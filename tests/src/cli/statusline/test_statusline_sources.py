"""Full-command source acquisition tests for the status-line segment plan."""

from __future__ import annotations

import ast
import inspect
import json
from functools import cached_property
from types import ModuleType
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import status_line
from forge.cli.statusline import context as status_context
from forge.cli.statusline import formatting as status_formatting
from forge.cli.statusline import palette as status_palette
from forge.cli.statusline import registry as status_registry
from forge.cli.statusline import rendering as status_rendering
from forge.cli.statusline import sources as status_sources
from forge.cli.statusline import throttle as status_throttle
from forge.cli.statusline import types as status_types
from forge.cli.statusline.types import TranscriptStats
from forge.runtime_config import RuntimeConfig, StatusLineConfig

_INPUT = {
    "workspace": {"current_dir": "/tmp/source-plan"},
    "model": {"display_name": "Opus 4.6"},
    "context_window": {
        "context_window_size": 200_000,
        "used_percentage": 12,
        "current_usage": {"input_tokens": 12_000},
    },
}

_SOURCE_FUNCTIONS = {
    "compute_cache_hit_rate",
    "detect_proxy",
    "discover_session",
    "get_git_branch",
    "get_line_change_values",
    "get_transcript_stats",
    "scan_transcript",
}

_PRESENTATION_FUNCTIONS = {
    "format_billing_cost",
    "format_context_size",
    "format_line_changes",
    "get_context_display",
    "render_categories",
    "tier_color",
    "truncate_ansi",
    "visible_width",
    "wrap_output",
}

_OLD_PRIVATE_PRESENTATION_FUNCTIONS = {"_tier_color", "_visible_width", "_wrap_output"}

_LOWER_MODULES = (
    status_context,
    status_formatting,
    status_palette,
    status_registry,
    status_rendering,
    status_sources,
    status_throttle,
    status_types,
)


def _tree(module: ModuleType) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _top_level_definitions(module: ModuleType) -> set[str]:
    return {
        node.name
        for node in _tree(module).body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _dotted_attributes(module: ModuleType) -> set[str]:
    def dotted(node: ast.AST) -> str | None:
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name):
            return None
        parts.append(node.id)
        return ".".join(reversed(parts))

    return {name for node in ast.walk(_tree(module)) if isinstance(node, ast.Attribute) if (name := dotted(node))}


def _imported_modules(module: ModuleType) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_source_facts_have_one_lower_owner_and_all_consumers_use_it() -> None:
    assert set(status_sources.__all__) == _SOURCE_FUNCTIONS
    assert _SOURCE_FUNCTIONS <= _top_level_definitions(status_sources)
    assert _SOURCE_FUNCTIONS.isdisjoint(_top_level_definitions(sl))
    assert set(status_types.__all__) == {"ProxyRuntimeTruth", "TranscriptStats"}
    assert {"ProxyRuntimeTruth", "TranscriptStats"} <= _top_level_definitions(status_types)
    assert all("forge.cli.status_line" not in _imported_modules(module) for module in _LOWER_MODULES)

    assert {
        "status_sources.detect_proxy",
        "status_sources.discover_session",
    } <= _dotted_attributes(sl)
    assert {"sources.get_git_branch", "sources.get_transcript_stats"} <= _dotted_attributes(status_context)
    assert {"sources.compute_cache_hit_rate", "sources.get_line_change_values"} <= _dotted_attributes(status_registry)


def test_rendering_has_one_lower_owner_and_the_command_stays_thin() -> None:
    assert _top_level_definitions(sl) == {"_get_terminal_width", "status_line"}
    assert _PRESENTATION_FUNCTIONS <= _top_level_definitions(status_formatting)
    assert _OLD_PRIVATE_PRESENTATION_FUNCTIONS.isdisjoint(_top_level_definitions(status_formatting))
    assert _PRESENTATION_FUNCTIONS.isdisjoint(_top_level_definitions(sl))
    assert set(status_rendering.__all__) == {"render_output"}
    assert _top_level_definitions(status_rendering) == {"render_output"}
    assert "rendering.render_output" in _dotted_attributes(sl)
    assert "formatting.render_categories" in _dotted_attributes(status_rendering)
    assert list(inspect.signature(status_formatting.render_categories).parameters) == ["where", "stream"]


def test_statusline_consumers_use_only_public_formatting_names() -> None:
    for module in (sl, status_context, status_palette, status_registry, status_rendering):
        private_calls = {name for name in _dotted_attributes(module) if name.startswith(("fmt._", "formatting._"))}
        assert private_calls == set()


def test_only_effective_statusline_caches_remain() -> None:
    assert not hasattr(status_sources, "_transcript_cache")
    assert not hasattr(status_sources, "_numstat_cache")
    assert isinstance(status_context.RenderContext.transcript_stats, cached_property)
    assert callable(status_throttle.read_or_compute)


@pytest.mark.parametrize(
    ("segments", "expected_proxy_calls", "expected_session_calls"),
    [
        (["path", "branch"], 0, 0),
        (["model"], 1, 0),
        (["breadcrumb"], 0, 1),
        (["cost"], 1, 1),
        ([], 1, 1),
    ],
)
def test_status_line_acquires_only_declared_sources_once(
    segments: list[str],
    expected_proxy_calls: int,
    expected_session_calls: int,
) -> None:
    config = RuntimeConfig(statusline=StatusLineConfig(segments=segments))
    proxy_probe = Mock(return_value=(False, None, False))
    session_probe = Mock(return_value=(None, False))

    with (
        patch.object(status_sources, "detect_proxy", proxy_probe),
        patch.object(status_sources, "discover_session", session_probe),
        patch.object(status_sources, "get_git_branch", return_value="main"),
        patch.object(status_sources, "get_transcript_stats", return_value=TranscriptStats()),
        patch.object(sl, "_get_terminal_width", return_value=200),
        patch("forge.runtime_config.get_runtime_config", return_value=config),
    ):
        result = CliRunner().invoke(
            status_line,
            input=json.dumps(_INPUT),
            env={"FORGE_STATUS_TRUNCATE": "0"},
        )

    assert result.exit_code == 0, result.output
    assert proxy_probe.call_count == expected_proxy_calls
    assert session_probe.call_count == expected_session_calls


def test_repeated_zero_source_renders_keep_probe_counters_at_zero() -> None:
    """Instrument the hot path: repeated minimal polls never enter either probe."""
    config = RuntimeConfig(statusline=StatusLineConfig(segments=["path", "branch"]))
    proxy_probe = Mock(return_value=(False, None, False))
    session_probe = Mock(return_value=(None, False))
    runner = CliRunner()

    with (
        patch.object(status_sources, "detect_proxy", proxy_probe),
        patch.object(status_sources, "discover_session", session_probe),
        patch.object(status_sources, "get_git_branch", return_value="main"),
        patch.object(sl, "_get_terminal_width", return_value=200),
        patch("forge.runtime_config.get_runtime_config", return_value=config),
    ):
        results = [
            runner.invoke(
                status_line,
                input=json.dumps(_INPUT),
                env={"FORGE_STATUS_TRUNCATE": "0"},
            )
            for _ in range(25)
        ]

    assert all(result.exit_code == 0 for result in results)
    assert proxy_probe.call_count == 0
    assert session_probe.call_count == 0
