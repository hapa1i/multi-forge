"""Package-owned model route catalog and request normalization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Any, Literal

import yaml

from forge.core.models.catalog import (
    ModelCatalogError,
    load_model_catalog,
    resolve_model_id,
)
from forge.core.models.direct_model import (
    ONE_M_SUFFIX,
    claude_model_tier,
    resolve_direct_model_pin,
)

RouteKind = Literal["direct", "proxy"]

SUPPORTED_ROUTE_CATALOG_SCHEMA_VERSIONS = frozenset({1})
SUPPORTED_DIRECT_RUNTIMES = frozenset({"claude_code"})


class ModelRouteCatalogError(ValueError):
    """Raised when the route catalog or a model-route request is invalid."""


@dataclass(frozen=True)
class ModelRouteCandidate:
    """One ordered way to reach a canonical model."""

    kind: RouteKind
    model_ref: str
    runtime: str | None = None
    source_id: str | None = None
    template: str | None = None

    def __post_init__(self) -> None:
        if not self.model_ref:
            raise ModelRouteCatalogError("route candidate model_ref cannot be empty")
        if self.kind == "direct":
            if self.runtime is None:
                raise ModelRouteCatalogError("direct route candidate requires runtime")
            if self.source_id is not None or self.template is not None:
                raise ModelRouteCatalogError("direct route candidate cannot declare source_id or template")
            return
        if self.kind == "proxy":
            if self.source_id is None or self.template is None:
                raise ModelRouteCatalogError("proxy route candidate requires source_id and template")
            if self.runtime is not None:
                raise ModelRouteCatalogError("proxy route candidate cannot declare runtime")
            return
        raise ModelRouteCatalogError(f"unsupported route candidate kind: {self.kind!r}")

    @property
    def identity(self) -> tuple[str, str | None, str | None, str | None, str]:
        """Return the fields that make an ordered candidate unique."""

        return (self.kind, self.runtime, self.source_id, self.template, self.model_ref)


@dataclass(frozen=True)
class ModelRouteCatalog:
    """Immutable ordered route candidates keyed by canonical route model."""

    schema_version: int
    models: Mapping[str, tuple[ModelRouteCandidate, ...]]

    def routes_for(self, route_key: str) -> tuple[ModelRouteCandidate, ...]:
        """Return ordered candidates for an already-normalized route key."""

        try:
            return self.models[route_key]
        except KeyError:
            raise ModelRouteCatalogError(f"No route catalog entry for canonical model {route_key!r}") from None


@dataclass(frozen=True)
class ModelRouteRequest:
    """Normalized explicit model request used by route planning."""

    requested_model: str
    route_key: str
    claude_tier: str | None
    transport_1m: bool

    def direct_execution_ref(self, model_ref: str) -> str:
        """Restore the Claude Code transport suffix for a direct candidate."""

        if self.transport_1m:
            return f"{model_ref.removesuffix(ONE_M_SUFFIX)}{ONE_M_SUFFIX}"
        return model_ref.removesuffix(ONE_M_SUFFIX)


_route_catalog: ModelRouteCatalog | None = None


def normalize_model_route_request(value: str) -> ModelRouteRequest:
    """Normalize a catalog id, alias, or Claude ``[1m]`` spelling."""

    raw_value = value.strip()
    if not raw_value:
        raise ModelRouteCatalogError("--model cannot be empty")

    requested_transport_1m = raw_value.endswith(ONE_M_SUFFIX)
    lookup_value = raw_value.removesuffix(ONE_M_SUFFIX) if requested_transport_1m else raw_value
    try:
        requested_model = resolve_model_id(lookup_value)
    except ModelCatalogError as exc:
        raise ModelRouteCatalogError(f"Unknown model or alias: {value!r}") from exc

    canonical_1m = requested_model.endswith("-1m")
    route_key = requested_model.removesuffix("-1m") if canonical_1m else requested_model
    transport_1m = requested_transport_1m or canonical_1m
    claude_tier = claude_model_tier(route_key)

    if requested_transport_1m and claude_tier is None:
        raise ModelRouteCatalogError(f"[1m] is only supported for Claude model requests, got {value!r}")
    if claude_tier is not None:
        try:
            resolve_direct_model_pin(f"{route_key}{ONE_M_SUFFIX}" if transport_1m else route_key)
        except ValueError as exc:
            raise ModelRouteCatalogError(str(exc)) from exc

    return ModelRouteRequest(
        requested_model=requested_model,
        route_key=route_key,
        claude_tier=claude_tier,
        transport_1m=transport_1m,
    )


def load_model_route_catalog(*, force_reload: bool = False) -> ModelRouteCatalog:
    """Load, strictly validate, and cache the packaged route catalog."""

    global _route_catalog

    if _route_catalog is not None and not force_reload:
        return _route_catalog

    raw = _load_route_catalog_yaml()
    catalog = _validate_and_build_route_catalog(raw)
    validate_model_route_catalog_integrations(catalog, _builtin_model_sources())
    _route_catalog = catalog
    return catalog


def clear_model_route_catalog_cache() -> None:
    """Clear the cached route catalog for tests and controlled reloads."""

    global _route_catalog
    _route_catalog = None


def get_model_route_candidates(model_or_alias: str) -> tuple[ModelRouteCandidate, ...]:
    """Normalize a model request and return its ordered route candidates."""

    request = normalize_model_route_request(model_or_alias)
    return load_model_route_catalog().routes_for(request.route_key)


def validate_model_route_catalog_integrations(
    catalog: ModelRouteCatalog,
    sources: Iterable[Any],
) -> None:
    """Validate proxy source/template ownership through a narrow metadata input."""

    source_map: dict[str, Any] = {}
    for source in sources:
        source_id = getattr(source, "id", None)
        if not isinstance(source_id, str) or not source_id:
            raise ModelRouteCatalogError("model-source metadata must expose a non-empty id")
        if source_id in source_map:
            raise ModelRouteCatalogError(f"duplicate model-source id in integration metadata: {source_id!r}")
        source_map[source_id] = source

    for model_id, candidates in catalog.models.items():
        for index, candidate in enumerate(candidates):
            if candidate.kind != "proxy":
                continue
            assert candidate.source_id is not None
            assert candidate.template is not None
            source = source_map.get(candidate.source_id)
            if source is None:
                raise ModelRouteCatalogError(
                    f"models.{model_id}.routes[{index}].source_id references unknown source {candidate.source_id!r}"
                )
            template_names = tuple(getattr(source, "template_names", ()))
            if candidate.template not in template_names:
                raise ModelRouteCatalogError(
                    f"models.{model_id}.routes[{index}].template {candidate.template!r} does not belong to "
                    f"source {candidate.source_id!r}"
                )


def _load_route_catalog_yaml() -> dict[str, Any]:
    """Read and parse ``model_routes.yaml`` from package resources."""

    try:
        catalog_ref = resources.files("forge.core.data").joinpath("model_routes.yaml")
        raw = yaml.safe_load(catalog_ref.read_text(encoding="utf-8"))
    except (OSError, TypeError, yaml.YAMLError) as exc:
        raise ModelRouteCatalogError(f"Could not load packaged model route catalog: {exc}") from exc
    if not isinstance(raw, dict):
        raise ModelRouteCatalogError(f"Model route catalog must be an object, got {type(raw).__name__}")
    return raw


def _validate_and_build_route_catalog(raw: dict[str, Any]) -> ModelRouteCatalog:
    """Validate parsed route-catalog YAML without lifecycle dependencies."""

    _require_exact_fields(raw, {"schema_version", "models"}, "route catalog")
    schema_version = raw["schema_version"]
    if type(schema_version) is not int:
        raise ModelRouteCatalogError(
            f"route catalog schema_version must be an integer, got {type(schema_version).__name__}"
        )
    if schema_version not in SUPPORTED_ROUTE_CATALOG_SCHEMA_VERSIONS:
        raise ModelRouteCatalogError(
            f"Unsupported model route catalog schema_version: {schema_version!r} "
            f"(supported: {sorted(SUPPORTED_ROUTE_CATALOG_SCHEMA_VERSIONS)})"
        )

    models_raw = raw["models"]
    if not isinstance(models_raw, dict):
        raise ModelRouteCatalogError(f"route catalog models must be an object, got {type(models_raw).__name__}")
    if not models_raw:
        raise ModelRouteCatalogError("route catalog models cannot be empty")

    models: dict[str, tuple[ModelRouteCandidate, ...]] = {}
    for model_id, model_data in models_raw.items():
        if not isinstance(model_id, str) or not model_id:
            raise ModelRouteCatalogError(f"route catalog model key must be a non-empty string, got {model_id!r}")
        try:
            canonical_model = resolve_model_id(model_id)
        except ModelCatalogError as exc:
            raise ModelRouteCatalogError(f"route catalog references unknown model key {model_id!r}") from exc
        if canonical_model != model_id:
            raise ModelRouteCatalogError(
                f"route catalog model key {model_id!r} is an alias for {canonical_model!r}; use canonical keys"
            )
        if model_id.endswith("-1m"):
            raise ModelRouteCatalogError(
                f"route catalog model key {model_id!r} duplicates 1M transport identity; use its base route key"
            )
        if not isinstance(model_data, dict):
            raise ModelRouteCatalogError(f"models.{model_id} must be an object, got {type(model_data).__name__}")
        _require_exact_fields(model_data, {"routes"}, f"models.{model_id}")
        routes_raw = model_data["routes"]
        if not isinstance(routes_raw, list) or not routes_raw:
            raise ModelRouteCatalogError(f"models.{model_id}.routes must be a non-empty list")

        candidates: list[ModelRouteCandidate] = []
        seen: set[tuple[str, str | None, str | None, str | None, str]] = set()
        for index, candidate_raw in enumerate(routes_raw):
            candidate = _parse_candidate(model_id, index, candidate_raw)
            if candidate.identity in seen:
                raise ModelRouteCatalogError(f"models.{model_id}.routes[{index}] duplicates an earlier candidate")
            seen.add(candidate.identity)
            candidates.append(candidate)
        models[model_id] = tuple(candidates)

    _validate_model_coverage(models)
    _validate_direct_first(models)
    return ModelRouteCatalog(schema_version=schema_version, models=MappingProxyType(models))


def _parse_candidate(model_id: str, index: int, raw: Any) -> ModelRouteCandidate:
    context = f"models.{model_id}.routes[{index}]"
    if not isinstance(raw, dict):
        raise ModelRouteCatalogError(f"{context} must be an object, got {type(raw).__name__}")
    kind = raw.get("kind")
    if kind == "direct":
        _require_exact_fields(raw, {"kind", "runtime", "model_ref"}, context)
        runtime = _require_nonempty_string(raw["runtime"], f"{context}.runtime")
        if runtime not in SUPPORTED_DIRECT_RUNTIMES:
            raise ModelRouteCatalogError(f"{context}.runtime is unsupported: {runtime!r}")
        model_ref = _require_nonempty_string(raw["model_ref"], f"{context}.model_ref")
        if model_ref.endswith(ONE_M_SUFFIX):
            raise ModelRouteCatalogError(f"{context}.model_ref must not duplicate the [1m] transport modifier")
        candidate = ModelRouteCandidate(kind="direct", runtime=runtime, model_ref=model_ref)
    elif kind == "proxy":
        _require_exact_fields(raw, {"kind", "source_id", "template", "model_ref"}, context)
        source_id = _require_nonempty_string(raw["source_id"], f"{context}.source_id")
        template = _require_nonempty_string(raw["template"], f"{context}.template")
        model_ref = _require_nonempty_string(raw["model_ref"], f"{context}.model_ref")
        if "/" not in model_ref:
            raise ModelRouteCatalogError(f"{context}.model_ref must be a catalog-listed provider reference")
        candidate = ModelRouteCandidate(
            kind="proxy",
            source_id=source_id,
            template=template,
            model_ref=model_ref,
        )
    else:
        raise ModelRouteCatalogError(f"{context}.kind must be 'direct' or 'proxy', got {kind!r}")

    try:
        candidate_request = normalize_model_route_request(candidate.model_ref)
    except ModelRouteCatalogError as exc:
        raise ModelRouteCatalogError(f"{context}.model_ref is not cataloged: {candidate.model_ref!r}") from exc
    if candidate_request.route_key != model_id:
        raise ModelRouteCatalogError(
            f"{context}.model_ref {candidate.model_ref!r} resolves to {candidate_request.route_key!r}, "
            f"not model key {model_id!r}"
        )
    if candidate.kind == "direct" and candidate.runtime == "claude_code" and candidate_request.claude_tier is None:
        raise ModelRouteCatalogError(f"{context} direct claude_code candidate must resolve to a Claude model")
    return candidate


def _validate_model_coverage(
    models: Mapping[str, tuple[ModelRouteCandidate, ...]],
) -> None:
    expected_keys = {
        normalize_model_route_request(model_id).route_key for model_id in load_model_catalog().models.keys()
    }
    missing = sorted(expected_keys - set(models))
    if missing:
        raise ModelRouteCatalogError(f"route catalog is missing canonical model keys: {missing}")


def _validate_direct_first(
    models: Mapping[str, tuple[ModelRouteCandidate, ...]],
) -> None:
    checked: set[str] = set()
    for model_id in load_model_catalog().models:
        try:
            pin = resolve_direct_model_pin(model_id)
        except ValueError:
            continue
        route_key = pin.canonical_model
        if route_key in checked:
            continue
        checked.add(route_key)
        routes = models.get(route_key, ())
        if not routes or routes[0].kind != "direct":
            raise ModelRouteCatalogError(
                f"models.{route_key}.routes must start with a direct candidate for Claude pin compatibility"
            )
        first = routes[0]
        if first.runtime != "claude_code" or first.model_ref != route_key:
            raise ModelRouteCatalogError(
                f"models.{route_key}.routes[0] must preserve direct claude_code model_ref {route_key!r}"
            )


def _require_exact_fields(raw: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(raw)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ModelRouteCatalogError(f"{context} missing required fields: {missing}")
    if extra:
        raise ModelRouteCatalogError(f"{context} has unknown fields: {extra}")


def _require_nonempty_string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ModelRouteCatalogError(f"{context} must be a non-empty string")
    return value


def _builtin_model_sources() -> tuple[Any, ...]:
    from forge.backend.sources import list_model_sources

    return list_model_sources()


__all__ = [
    "ModelRouteCandidate",
    "ModelRouteCatalog",
    "ModelRouteCatalogError",
    "ModelRouteRequest",
    "SUPPORTED_ROUTE_CATALOG_SCHEMA_VERSIONS",
    "clear_model_route_catalog_cache",
    "get_model_route_candidates",
    "load_model_route_catalog",
    "normalize_model_route_request",
    "validate_model_route_catalog_integrations",
]
