from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
import yaml

from forge.core.models.model_practices import (
    ModelPracticesError,
    load_model_practices,
    parse_model_practices,
    resolve_model_practice,
    unknown_model_practice,
)


def _catalog(*declarations: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "models": {"claude-opus-5": {"text_marking": list(declarations)}},
    }


def _declaration(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "status": "marked",
        "basis": "provider_declaration",
        "source_url": "https://provider.example/practice",
        "checked_at": "2026-08-20",
        "effective_from": "2026-08-02",
        "route_scope": ["backend:openrouter", "route:proxy", "runtime:claude_code"],
    }
    value.update(updates)
    return value


def test_packaged_catalog_is_valid_and_intentionally_empty() -> None:
    catalog = load_model_practices(force_reload=True)
    assert catalog.schema_version == 1
    assert catalog.models == {}


def test_unquoted_yaml_dates_normalize_to_stable_iso_strings() -> None:
    raw = yaml.safe_load("""
schema_version: 1
models:
  claude-opus-5:
    text_marking:
      - status: marked
        basis: provider_declaration
        source_url: https://provider.example/practice
        checked_at: 2026-08-20
        effective_from: 2026-08-02
        route_scope:
          - backend:openrouter
          - route:proxy
          - runtime:claude_code
""")

    declaration = parse_model_practices(raw).models["claude-opus-5"][0]

    assert declaration.checked_at == "2026-08-20"
    assert declaration.effective_from == "2026-08-02"


@pytest.mark.parametrize("status", ["marked", "unmarked"])
def test_marked_and_unmarked_declarations_resolve_conjunctively(status: str) -> None:
    catalog = parse_model_practices(_catalog(_declaration(status=status)))
    scope = ["backend:openrouter", "route:proxy", "runtime:claude_code"]

    resolved = resolve_model_practice("claude-opus-5", scope, catalog=catalog, on_date=date(2026, 8, 22))

    assert resolved == _declaration(status=status)
    assert resolve_model_practice("claude-opus-5", scope[:-1], catalog=catalog) == unknown_model_practice()


def test_future_declaration_and_unknown_model_resolve_unknown() -> None:
    catalog = parse_model_practices(_catalog(_declaration(effective_from="2027-01-01")))
    scope = ["backend:openrouter", "route:proxy", "runtime:claude_code"]

    assert (
        resolve_model_practice("claude-opus-5", scope, catalog=catalog, on_date=date(2026, 8, 22))
        == unknown_model_practice()
    )
    assert resolve_model_practice(None, scope, catalog=catalog) == unknown_model_practice()


def test_effective_date_defaults_to_the_utc_calendar() -> None:
    catalog = parse_model_practices(_catalog(_declaration(effective_from="2026-08-23")))
    scope = ["backend:openrouter", "route:proxy", "runtime:claude_code"]

    with patch("forge.core.models.model_practices.utc_today", return_value=date(2026, 8, 23)) as utc_today:
        resolved = resolve_model_practice("claude-opus-5", scope, catalog=catalog)

    assert resolved == _declaration(effective_from="2026-08-23")
    utc_today.assert_called_once_with()


@pytest.mark.parametrize(
    "raw",
    [
        {"schema_version": 2, "models": {}},
        {"schema_version": 1, "models": {}, "extra": True},
        _catalog(_declaration(status="unknown")),
        _catalog(_declaration(basis="detected")),
        _catalog(_declaration(source_url="http://provider.example/practice")),
        _catalog(_declaration(source_url="https://user:secret@provider.example/practice")),
        _catalog(_declaration(source_url="https://@provider.example/practice")),
        _catalog(_declaration(source_url="https://provider .example/practice")),
        _catalog(_declaration(source_url="https://[::1/practice")),
        _catalog(_declaration(source_url="https://provider.example:not-a-port/practice")),
        _catalog(_declaration(checked_at="08/20/2026")),
        _catalog(_declaration(effective_from="2026-8-2")),
        _catalog(_declaration(route_scope=["route:proxy", "runtime:claude_code"])),
        _catalog(_declaration(route_scope=["runtime:claude_code", "route:proxy", "backend:openrouter"])),
        _catalog(
            _declaration(
                route_scope=[
                    "backend:openrouter",
                    "backend:openrouter",
                    "route:proxy",
                    "runtime:claude_code",
                ]
            )
        ),
        _catalog(
            _declaration(
                route_scope=[
                    "backend:openrouter",
                    "owner:provider",
                    "route:proxy",
                    "runtime:claude_code",
                ]
            )
        ),
        _catalog(
            _declaration(
                route_scope=[
                    "backend:openrouter",
                    "route:proxy",
                    "route:direct",
                    "runtime:claude_code",
                ]
            )
        ),
        {
            "schema_version": 1,
            "models": {"claude-opus-5": {"text_marking": [_declaration()], "extra": True}},
        },
        _catalog({**_declaration(), "extra": True}),
        {
            "schema_version": 1,
            "models": {"opus": {"text_marking": [_declaration()]}},
        },
    ],
)
def test_invalid_catalog_shapes_fail_closed(raw: dict[str, object]) -> None:
    with pytest.raises(ModelPracticesError):
        parse_model_practices(raw)


def test_overlapping_declarations_are_rejected() -> None:
    broad = _declaration()
    billing_specific = _declaration(
        route_scope=[
            "backend:openrouter",
            "billing:api",
            "route:proxy",
            "runtime:claude_code",
        ]
    )

    with pytest.raises(ModelPracticesError, match="overlapping"):
        parse_model_practices(_catalog(broad, billing_specific))


def test_disjoint_backend_declarations_are_allowed() -> None:
    openrouter = _declaration()
    another = _declaration(
        status="unmarked",
        route_scope=["backend:litellm-remote", "route:proxy", "runtime:claude_code"],
    )
    catalog = parse_model_practices(_catalog(openrouter, another))

    assert (
        resolve_model_practice(
            "claude-opus-5",
            ["backend:litellm-remote", "route:proxy", "runtime:claude_code"],
            catalog=catalog,
        )["status"]
        == "unmarked"
    )


def test_catalog_resource_load_failure_is_not_silently_treated_as_unknown() -> None:
    with patch(
        "forge.core.models.model_practices.resources.files",
        side_effect=OSError("package resource unavailable"),
    ):
        with pytest.raises(ModelPracticesError, match="could not load model_practices.yaml"):
            load_model_practices(force_reload=True)
