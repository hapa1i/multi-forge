"""Strict provider-declared model-practice catalog and route-scoped lookup."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from importlib import resources
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml

from forge.core.models.catalog import load_model_catalog, resolve_model_id

MODEL_PRACTICES_SCHEMA_VERSION = 1
PRACTICE_STATUSES = frozenset({"marked", "unmarked"})
PRACTICE_BASIS: Literal["provider_declaration"] = "provider_declaration"
RUNTIME_SCOPE_VALUES = frozenset({"claude_code", "codex"})
ROUTE_SCOPE_VALUES = frozenset({"direct", "proxy", "custom", "runtime_native"})
BILLING_SCOPE_VALUES = frozenset(
    {
        "api",
        "subscription_interactive",
        "subscription_headless_credit",
        "subscription_quota",
        "unknown",
    }
)
_SAFE_SCOPE_VALUE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_DECLARATION_FIELDS = frozenset({"status", "basis", "source_url", "checked_at", "effective_from", "route_scope"})


class ModelPracticesError(ValueError):
    """The packaged practice catalog or a fixture violates its strict schema."""


@dataclass(frozen=True)
class ModelPracticeDeclaration:
    status: Literal["marked", "unmarked"]
    basis: Literal["provider_declaration"]
    source_url: str
    checked_at: str
    effective_from: str | None
    route_scope: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["route_scope"] = list(self.route_scope)
        return value


@dataclass(frozen=True)
class ModelPracticesCatalog:
    schema_version: int
    models: dict[str, tuple[ModelPracticeDeclaration, ...]]


_catalog: ModelPracticesCatalog | None = None


def unknown_model_practice() -> dict[str, Any]:
    """Return the stable derived absence shape used by every read surface."""
    return {
        "status": "unknown",
        "basis": None,
        "source_url": None,
        "checked_at": None,
        "effective_from": None,
        "route_scope": [],
    }


def validate_route_scope_tags(tags: object, *, require_declaration: bool = False) -> tuple[str, ...]:
    """Validate sorted, unique code-owned route-scope tags."""
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ModelPracticesError("route_scope must be a list of strings")
    if tags != sorted(set(tags)):
        raise ModelPracticesError("route_scope must be sorted and unique")
    if require_declaration and not tags:
        raise ModelPracticesError("route_scope must be nonempty")

    families: dict[str, list[str]] = {}
    for tag in tags:
        if ":" not in tag:
            raise ModelPracticesError(f"unknown route-scope tag {tag!r}")
        family, value = tag.split(":", 1)
        if not value or _SAFE_SCOPE_VALUE_RE.fullmatch(value) is None:
            raise ModelPracticesError(f"invalid route-scope tag {tag!r}")
        if family == "runtime" and value not in RUNTIME_SCOPE_VALUES:
            raise ModelPracticesError(f"unknown runtime route-scope tag {tag!r}")
        if family == "route" and value not in ROUTE_SCOPE_VALUES:
            raise ModelPracticesError(f"unknown route route-scope tag {tag!r}")
        if family == "billing" and value not in BILLING_SCOPE_VALUES:
            raise ModelPracticesError(f"unknown billing route-scope tag {tag!r}")
        if family not in {"runtime", "route", "backend", "billing"}:
            raise ModelPracticesError(f"unknown route-scope tag family {family!r}")
        families.setdefault(family, []).append(value)

    for family, values in families.items():
        if len(values) > 1:
            raise ModelPracticesError(f"route_scope has more than one {family} tag")
    if require_declaration:
        for required in ("runtime", "route", "backend"):
            if required not in families:
                raise ModelPracticesError(f"route_scope requires exactly one {required} tag")
    return tuple(tags)


def parse_model_practices(raw: object) -> ModelPracticesCatalog:
    """Build the strict catalog from parsed YAML-compatible data."""
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "models"}:
        raise ModelPracticesError("model-practices catalog requires exactly schema_version and models")
    version = raw["schema_version"]
    if type(version) is not int or version != MODEL_PRACTICES_SCHEMA_VERSION:
        raise ModelPracticesError(f"unsupported model-practices schema version {version!r}")
    raw_models = raw["models"]
    if not isinstance(raw_models, dict):
        raise ModelPracticesError("models must be an object")

    intrinsic = load_model_catalog()
    parsed_models: dict[str, tuple[ModelPracticeDeclaration, ...]] = {}
    for model_id, raw_entry in raw_models.items():
        if not isinstance(model_id, str) or model_id not in intrinsic.models or resolve_model_id(model_id) != model_id:
            raise ModelPracticesError(f"model key must be a canonical catalog id: {model_id!r}")
        if not isinstance(raw_entry, dict) or set(raw_entry) != {"text_marking"}:
            raise ModelPracticesError(f"models.{model_id} requires exactly text_marking")
        declarations_raw = raw_entry["text_marking"]
        if not isinstance(declarations_raw, list) or not declarations_raw:
            raise ModelPracticesError(f"models.{model_id}.text_marking must be a nonempty list")
        declarations = tuple(
            _parse_declaration(model_id, index, declaration)
            for index, declaration in enumerate(declarations_raw, start=1)
        )
        _reject_overlapping_declarations(model_id, declarations)
        parsed_models[model_id] = declarations
    return ModelPracticesCatalog(schema_version=version, models=parsed_models)


def load_model_practices(*, force_reload: bool = False) -> ModelPracticesCatalog:
    """Load and cache the package-owned model-practices resource."""
    global _catalog
    if _catalog is not None and not force_reload:
        return _catalog
    try:
        resource = resources.files("forge.core.data").joinpath("model_practices.yaml")
        raw = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ModelPracticesError(f"could not load model_practices.yaml: {exc}") from exc
    _catalog = parse_model_practices(raw)
    return _catalog


def resolve_model_practice(
    canonical_model: str | None,
    route_scope_tags: list[str] | tuple[str, ...],
    *,
    on_date: date | None = None,
    catalog: ModelPracticesCatalog | None = None,
) -> dict[str, Any]:
    """Resolve one current provider declaration under conjunctive route scope."""
    if canonical_model is None:
        return unknown_model_practice()
    scope = set(validate_route_scope_tags(list(route_scope_tags)))
    declarations = (catalog or load_model_practices()).models.get(canonical_model, ())
    today = on_date or date.today()
    matches = [
        declaration
        for declaration in declarations
        if set(declaration.route_scope).issubset(scope)
        and (declaration.effective_from is None or date.fromisoformat(declaration.effective_from) <= today)
    ]
    if not matches:
        return unknown_model_practice()
    if len(matches) != 1:
        raise ModelPracticesError(f"multiple text-marking declarations match {canonical_model!r}")
    return matches[0].to_dict()


def validate_model_practice_snapshot(raw: object) -> None:
    """Validate one normalized declaration embedded in immutable route evidence."""
    if not isinstance(raw, dict) or set(raw) != _DECLARATION_FIELDS:
        raise ModelPracticesError("marking declaration has an invalid field set")
    if raw["status"] == "unknown":
        if any(raw[field] is not None for field in ("basis", "source_url", "checked_at", "effective_from")):
            raise ModelPracticesError("unknown marking declaration must use null metadata")
        if raw["route_scope"] != []:
            raise ModelPracticesError("unknown marking declaration must use an empty route_scope")
        return
    _parse_declaration("<snapshot>", 1, raw)


def _parse_declaration(model_id: str, index: int, raw: object) -> ModelPracticeDeclaration:
    label = f"models.{model_id}.text_marking[{index}]"
    if not isinstance(raw, dict) or set(raw) != _DECLARATION_FIELDS:
        raise ModelPracticesError(f"{label} has an invalid field set")
    status = raw["status"]
    if status not in PRACTICE_STATUSES:
        raise ModelPracticesError(f"{label}.status must be marked or unmarked")
    if raw["basis"] != PRACTICE_BASIS:
        raise ModelPracticesError(f"{label}.basis must be provider_declaration")
    source_url = raw["source_url"]
    if not isinstance(source_url, str):
        raise ModelPracticesError(f"{label}.source_url must be an HTTPS URL")
    try:
        parsed_url = urlsplit(source_url)
        hostname = parsed_url.hostname
        parsed_url.port
    except ValueError as exc:
        raise ModelPracticesError(f"{label}.source_url must be a credential-free HTTPS URL") from exc
    if (
        parsed_url.scheme != "https"
        or not hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or any(character.isspace() or ord(character) < 32 for character in source_url)
    ):
        raise ModelPracticesError(f"{label}.source_url must be a credential-free HTTPS URL")
    checked_at = _iso_date(raw["checked_at"], f"{label}.checked_at", nullable=False)
    assert checked_at is not None
    effective_from = _iso_date(raw["effective_from"], f"{label}.effective_from", nullable=True)
    route_scope = validate_route_scope_tags(raw["route_scope"], require_declaration=True)
    return ModelPracticeDeclaration(
        status=status,
        basis=PRACTICE_BASIS,
        source_url=source_url,
        checked_at=checked_at,
        effective_from=effective_from,
        route_scope=route_scope,
    )


def _iso_date(value: object, field: str, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is date:
        return value.isoformat()
    if not isinstance(value, str):
        raise ModelPracticesError(f"{field} must be an ISO date" + (" or null" if nullable else ""))
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ModelPracticesError(f"{field} must be an ISO date") from exc
    if parsed.isoformat() != value:
        raise ModelPracticesError(f"{field} must use YYYY-MM-DD")
    return value


def _reject_overlapping_declarations(model_id: str, declarations: tuple[ModelPracticeDeclaration, ...]) -> None:
    for index, left in enumerate(declarations):
        left_families = _scope_families(left.route_scope)
        for right in declarations[index + 1 :]:
            right_families = _scope_families(right.route_scope)
            if all(
                family not in left_families
                or family not in right_families
                or left_families[family] == right_families[family]
                for family in {"runtime", "route", "backend", "billing"}
            ):
                raise ModelPracticesError(f"model {model_id!r} has overlapping text-marking declarations")


def _scope_families(tags: tuple[str, ...]) -> dict[str, str]:
    return dict(tag.split(":", 1) for tag in tags)
