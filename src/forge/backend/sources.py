"""Static model-source catalog for Forge backends.

This module defines local and remote model sources as static catalog entries.
Runtime local backend instances remain owned by ``forge.backend.registry``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Literal, get_args
from urllib.parse import urlparse

from forge.core.backend_dependency import BackendDependency
from forge.core.credential_registry import CREDENTIALS, Credential
from forge.core.provider_types import ProviderType

ModelSourceKind = Literal["local", "remote"]
EndpointKind = Literal["literal_url", "connection_value", "local_backend", "runtime_native"]
# A source's billing nature (a declared catalog fact), distinct from the
# per-invocation BillingMode (core/usage/ledger). "subscription_quota" is the one
# spelling shared between the two; posture is coarse and source-level.
BillingPosture = Literal["per_token", "subscription_quota", "free"]

_VALID_SOURCE_KINDS = frozenset(get_args(ModelSourceKind))
_VALID_ENDPOINT_KINDS = frozenset(get_args(EndpointKind))
_VALID_PROVIDERS = frozenset(get_args(ProviderType))
_VALID_BILLING_POSTURES = frozenset(get_args(BillingPosture))
_ENV_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


class ModelSourceCatalogError(ValueError):
    """Raised when model-source catalog definitions are invalid."""


class ModelSourceNotFoundError(LookupError):
    """Raised when a model-source id or alias is not found."""


@dataclass(frozen=True)
class SourceEndpoint:
    """How a model source resolves its endpoint."""

    kind: EndpointKind
    value: str | None = None
    default_url: str | None = None

    @classmethod
    def literal_url(cls, url: str) -> "SourceEndpoint":
        """Create an endpoint backed by a fixed URL."""

        return cls(kind="literal_url", value=url)

    @classmethod
    def connection_value(cls, env_var: str, *, default_url: str | None = None) -> "SourceEndpoint":
        """Create an endpoint resolved from a credential/connection env var."""

        return cls(kind="connection_value", value=env_var, default_url=default_url)

    @classmethod
    def local_backend(cls) -> "SourceEndpoint":
        """Create an endpoint derived from a local backend lifecycle dependency."""

        return cls(kind="local_backend")

    @classmethod
    def runtime_native(cls) -> "SourceEndpoint":
        """Create an endpoint whose connection and auth are owned by the runtime.

        No URL and no Forge credential -- a subscription reached through its
        runtime (e.g. ChatGPT via ``codex``). Which runtime can reach it is pinned
        by the source's ``reachable_via``, not by the endpoint.
        """

        return cls(kind="runtime_native")

    def __post_init__(self) -> None:
        _validate_endpoint(self)


@dataclass(frozen=True)
class LocalBackendLifecycle:
    """Local-only lifecycle refinement for a model source."""

    adapter: str
    default_port: int

    def __post_init__(self) -> None:
        if not self.adapter:
            raise ModelSourceCatalogError("local lifecycle adapter is required")
        if self.default_port <= 0:
            raise ModelSourceCatalogError("local lifecycle default_port must be positive")

    def to_backend_dependency(self, required_env_vars: Iterable[str] = ()) -> BackendDependency:
        """Convert to the existing template/runtime backend dependency shape."""

        return BackendDependency(
            adapter=self.adapter,
            port=self.default_port,
            required_env_vars=list(required_env_vars),
        )


@dataclass(frozen=True)
class ModelSourceCapabilities:
    """Capability flags attached to a model source."""

    auth_probe: bool = True
    provider_trace: bool = False
    provider_user_grouping: bool = False
    # Source's upstream serves the OpenAI Responses API on the proxy's Codex-facing
    # ingress (forge codex start --proxy). Gates the proxy `/v1/responses` route and
    # the codex preflight `proxy_supported` posture.
    responses_ingress: bool = False


@dataclass(frozen=True)
class ModelSource:
    """Static local-or-remote model source definition."""

    id: str
    kind: ModelSourceKind
    provider: ProviderType
    endpoint: SourceEndpoint
    credential_ids: tuple[str, ...]
    capabilities: ModelSourceCapabilities = field(default_factory=ModelSourceCapabilities)
    local_lifecycle: LocalBackendLifecycle | None = None
    template_names: tuple[str, ...] = ()
    billing_posture: BillingPosture = "per_token"
    # Lane runtimes that can reach this source; empty = any. A subscription whose
    # auth is a runtime's native login pins it here (chatgpt -> ("codex",)). Read
    # by forge.core.lanes._reachable; not consulted by transport resolution.
    reachable_via: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_source(self)

    @property
    def has_lifecycle(self) -> bool:
        """Whether this source has a local process lifecycle."""

        return self.local_lifecycle is not None

    @property
    def credentials(self) -> tuple[Credential, ...]:
        """Credential definitions required by this source."""

        return tuple(CREDENTIALS[credential_id] for credential_id in self.credential_ids)

    @property
    def required_env_vars(self) -> tuple[str, ...]:
        """Required credential and connection-value env vars for this source."""

        return required_env_vars_for_source(self)

    def to_backend_dependency(self) -> BackendDependency:
        """Convert a local source to the existing backend dependency shape."""

        if self.local_lifecycle is None:
            raise ModelSourceCatalogError(f"source {self.id!r} has no local lifecycle")
        return self.local_lifecycle.to_backend_dependency(self.required_env_vars)


def _build_identifier_lookup(sources: Iterable[ModelSource]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for source in sources:
        seen_for_source: set[str] = set()
        for identifier in (source.id, *source.template_names):
            if identifier in seen_for_source:
                continue
            seen_for_source.add(identifier)
            if not identifier:
                raise ModelSourceCatalogError(f"source {source.id!r} has an empty identifier")
            if identifier in lookup:
                raise ModelSourceCatalogError(
                    f"duplicate model-source identifier {identifier!r}: {lookup[identifier]!r} and {source.id!r}"
                )
            lookup[identifier] = source.id
    return lookup


def _validate_source(source: ModelSource) -> None:
    if not _SOURCE_ID_RE.match(source.id):
        raise ModelSourceCatalogError(f"invalid model-source id: {source.id!r}")
    if source.kind not in _VALID_SOURCE_KINDS:
        raise ModelSourceCatalogError(f"invalid model-source kind for {source.id!r}: {source.kind!r}")
    if source.provider not in _VALID_PROVIDERS:
        raise ModelSourceCatalogError(f"invalid provider for {source.id!r}: {source.provider!r}")
    if source.billing_posture not in _VALID_BILLING_POSTURES:
        raise ModelSourceCatalogError(f"invalid billing_posture for {source.id!r}: {source.billing_posture!r}")

    # Credential symmetry by endpoint family: a runtime_native source's auth is
    # owned by its runtime, so it declares NO Forge credential; every other kind
    # must declare at least one.
    if source.endpoint.kind == "runtime_native":
        if source.credential_ids:
            raise ModelSourceCatalogError(
                f"runtime_native source {source.id!r} must not declare credentials (auth is owned by the runtime)"
            )
    elif not source.credential_ids:
        raise ModelSourceCatalogError(f"source {source.id!r} must declare at least one credential")

    for credential_id in source.credential_ids:
        if credential_id not in CREDENTIALS:
            raise ModelSourceCatalogError(f"source {source.id!r} references unknown credential {credential_id!r}")
    for runtime_id in source.reachable_via:
        if not runtime_id:
            raise ModelSourceCatalogError(f"source {source.id!r} has an empty reachable_via entry")
    for template_name in source.template_names:
        if not _SOURCE_ID_RE.match(template_name):
            raise ModelSourceCatalogError(f"source {source.id!r} has invalid template name {template_name!r}")

    if source.kind == "local":
        if source.endpoint.kind != "local_backend":
            raise ModelSourceCatalogError(f"local source {source.id!r} must use a local_backend endpoint")
        if source.local_lifecycle is None:
            raise ModelSourceCatalogError(f"local source {source.id!r} must declare local lifecycle")
    else:
        if source.endpoint.kind == "local_backend":
            raise ModelSourceCatalogError(f"remote source {source.id!r} cannot use a local_backend endpoint")
        if source.local_lifecycle is not None:
            raise ModelSourceCatalogError(f"remote source {source.id!r} cannot declare local lifecycle")


def _validate_endpoint(endpoint: SourceEndpoint) -> None:
    if endpoint.kind not in _VALID_ENDPOINT_KINDS:
        raise ModelSourceCatalogError(f"invalid endpoint kind: {endpoint.kind!r}")

    if endpoint.kind == "literal_url":
        if not endpoint.value or not _is_http_url(endpoint.value):
            raise ModelSourceCatalogError(f"literal_url endpoint requires an http(s) URL, got {endpoint.value!r}")
        if endpoint.default_url is not None:
            raise ModelSourceCatalogError("literal_url endpoint cannot also set default_url")
        return

    if endpoint.kind == "connection_value":
        if not endpoint.value or not _ENV_VAR_RE.match(endpoint.value):
            raise ModelSourceCatalogError(f"connection_value endpoint requires an env var name, got {endpoint.value!r}")
        if endpoint.default_url is not None and not _is_http_url(endpoint.default_url):
            raise ModelSourceCatalogError(
                f"connection_value endpoint default_url must be an http(s) URL, got {endpoint.default_url!r}"
            )
        return

    if endpoint.kind == "runtime_native":
        if endpoint.value is not None or endpoint.default_url is not None:
            raise ModelSourceCatalogError("runtime_native endpoint cannot set value or default_url")
        return

    if endpoint.value is not None or endpoint.default_url is not None:
        raise ModelSourceCatalogError("local_backend endpoint cannot set value or default_url")


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def required_env_vars_for_source(source: ModelSource) -> tuple[str, ...]:
    """Return required env vars for a model source in declaration order."""

    required: list[str] = []

    def add(name: str) -> None:
        if name not in required:
            required.append(name)

    for credential in source.credentials:
        for env_var in credential.env_vars:
            if env_var.required:
                add(env_var.name)

    if source.endpoint.kind == "connection_value" and source.endpoint.value and source.endpoint.default_url is None:
        add(source.endpoint.value)

    return tuple(required)


def template_env_vars_by_template() -> dict[str, list[str]]:
    """Return the template -> required env var map derived from source definitions."""

    names: dict[str, list[str]] = {}
    for source in BUILTIN_MODEL_SOURCES:
        for template_name in source.template_names:
            names[template_name] = list(source.required_env_vars)
    return dict(sorted(names.items()))


OPENROUTER_TEMPLATE_NAMES: tuple[str, ...] = (
    "openrouter-anthropic",
    "openrouter-deepseek",
    "openrouter-gemini",
    "openrouter-gemini-flash",
    "openrouter-glm",
    "openrouter-kimi",
    "openrouter-minimax",
    "openrouter-openai",
    "openrouter-openai-codex",
    "openrouter-qwen",
)

REMOTE_LITELLM_TEMPLATE_NAMES: tuple[str, ...] = (
    "litellm-anthropic",
    "litellm-gemini",
    "litellm-openai",
)


BUILTIN_MODEL_SOURCES: tuple[ModelSource, ...] = (
    ModelSource(
        id="openrouter",
        kind="remote",
        provider="openrouter",
        endpoint=SourceEndpoint.connection_value(
            "OPENROUTER_BASE_URL",
            default_url="https://openrouter.ai/api/v1",
        ),
        credential_ids=("openrouter",),
        capabilities=ModelSourceCapabilities(provider_trace=True, provider_user_grouping=True),
        template_names=OPENROUTER_TEMPLATE_NAMES,
    ),
    ModelSource(
        id="litellm-remote",
        kind="remote",
        provider="litellm_remote",
        endpoint=SourceEndpoint.connection_value("LITELLM_BASE_URL"),
        credential_ids=("litellm-remote",),
        template_names=REMOTE_LITELLM_TEMPLATE_NAMES,
    ),
    ModelSource(
        id="anthropic-passthrough",
        kind="remote",
        provider="anthropic",
        endpoint=SourceEndpoint.literal_url("https://api.anthropic.com"),
        credential_ids=("anthropic-api",),
        template_names=("anthropic-passthrough",),
    ),
    ModelSource(
        id="anthropic-direct",
        kind="remote",
        provider="anthropic",
        endpoint=SourceEndpoint.literal_url("https://api.anthropic.com"),
        credential_ids=("anthropic-api",),
    ),
    # ChatGPT subscription reached through the codex runtime. Endpoint and auth are
    # owned by codex (codex login --device-auth -> chatgpt_tokens), so there is no
    # Forge URL and no Forge credential. Billing is the subscription's quota;
    # reachable only via codex (the runtime that holds the login). First
    # runtime_native source (epic consumer_lanes, T2).
    ModelSource(
        id="chatgpt",
        kind="remote",
        provider="openai",
        endpoint=SourceEndpoint.runtime_native(),
        credential_ids=(),
        billing_posture="subscription_quota",
        reachable_via=("codex",),
    ),
    ModelSource(
        id="litellm-gemini-local",
        kind="local",
        provider="litellm_local",
        endpoint=SourceEndpoint.local_backend(),
        credential_ids=("gemini-api",),
        local_lifecycle=LocalBackendLifecycle(
            adapter="litellm",
            default_port=4000,
        ),
        template_names=("litellm-gemini-local", "litellm-gemini-flash-local"),
    ),
    ModelSource(
        id="litellm-openai-local",
        kind="local",
        provider="litellm_local",
        endpoint=SourceEndpoint.local_backend(),
        credential_ids=("openai-api",),
        local_lifecycle=LocalBackendLifecycle(
            adapter="litellm",
            default_port=4000,
        ),
        template_names=("litellm-openai-local", "litellm-openai-codex-local"),
    ),
    ModelSource(
        id="litellm-anthropic-local",
        kind="local",
        provider="litellm_local",
        endpoint=SourceEndpoint.local_backend(),
        credential_ids=("anthropic-api",),
        local_lifecycle=LocalBackendLifecycle(
            adapter="litellm",
            default_port=4000,
        ),
        template_names=("litellm-anthropic-local",),
    ),
    # Codex-facing OpenAI Responses passthrough (forge codex start --proxy). A
    # local LiteLLM serves /v1/responses upstream, so reasoning is preserved
    # byte-for-byte and the x-litellm-response-cost header yields real cost.
    ModelSource(
        id="codex-responses-local",
        kind="local",
        provider="litellm_local",
        endpoint=SourceEndpoint.local_backend(),
        credential_ids=("openai-api",),
        capabilities=ModelSourceCapabilities(responses_ingress=True, provider_trace=True),
        local_lifecycle=LocalBackendLifecycle(
            adapter="litellm",
            default_port=4000,
        ),
        template_names=("codex-responses-local",),
    ),
    ModelSource(
        id="litellm-gemini-test",
        kind="local",
        provider="litellm_local",
        endpoint=SourceEndpoint.local_backend(),
        credential_ids=("gemini-api",),
        local_lifecycle=LocalBackendLifecycle(
            adapter="litellm",
            default_port=4001,
        ),
        template_names=("litellm-gemini-test",),
    ),
)


def list_model_sources() -> tuple[ModelSource, ...]:
    """Return all built-in model sources in stable catalog order."""

    return BUILTIN_MODEL_SOURCES


def get_model_source(source_id: str) -> ModelSource:
    """Return a model source by canonical id."""

    try:
        return _SOURCE_BY_ID[source_id]
    except KeyError:
        raise ModelSourceNotFoundError(f"Unknown model source: {source_id}") from None


def resolve_model_source_id(identifier: str) -> str:
    """Resolve a canonical source id or template alias to a canonical source id."""

    try:
        return _SOURCE_ID_BY_IDENTIFIER[identifier]
    except KeyError:
        raise ModelSourceNotFoundError(f"Unknown model source or alias: {identifier}") from None


def model_source_for_template(template_name: str) -> ModelSource:
    """Return the model source associated with a proxy template name."""

    try:
        return _SOURCE_BY_IDENTIFIER[template_name]
    except KeyError:
        raise ModelSourceNotFoundError(f"Unknown model source or alias: {template_name}") from None


def source_bearer_auth_env_var(source: ModelSource) -> str:
    """Return the single secret bearer-token env var for a source.

    Selects the one credential env var that is a secret and not a connection
    value, so a ``*_BASE_URL`` connection value is never mistaken for a bearer
    token. The Responses passthrough route injects the resolved value as
    ``Authorization: Bearer``.

    Raises:
        ModelSourceCatalogError: if zero or more than one qualifying env var
            exists. The choice must be unambiguous -- fail closed, never guess.
    """
    candidates = [
        env_var.name
        for credential in source.credentials
        for env_var in credential.env_vars
        if env_var.secret and not env_var.connection_value
    ]
    if len(candidates) != 1:
        raise ModelSourceCatalogError(
            f"source {source.id!r} must declare exactly one secret bearer env var for "
            f"Responses passthrough auth; found {len(candidates)}: {candidates}"
        )
    return candidates[0]


def validate_model_sources(sources: Iterable[ModelSource]) -> None:
    """Validate a model-source catalog for duplicate identifiers and bad entries."""

    materialized = tuple(sources)
    _build_identifier_lookup(materialized)
    for source in materialized:
        _validate_source(source)


validate_model_sources(BUILTIN_MODEL_SOURCES)
_SOURCE_ID_BY_IDENTIFIER = _build_identifier_lookup(BUILTIN_MODEL_SOURCES)
_SOURCE_BY_ID = {source.id: source for source in BUILTIN_MODEL_SOURCES}
_SOURCE_BY_IDENTIFIER = {
    identifier: _SOURCE_BY_ID[source_id] for identifier, source_id in _SOURCE_ID_BY_IDENTIFIER.items()
}


__all__ = [
    "BUILTIN_MODEL_SOURCES",
    "BillingPosture",
    "EndpointKind",
    "LocalBackendLifecycle",
    "ModelSource",
    "ModelSourceCapabilities",
    "ModelSourceCatalogError",
    "ModelSourceKind",
    "ModelSourceNotFoundError",
    "OPENROUTER_TEMPLATE_NAMES",
    "REMOTE_LITELLM_TEMPLATE_NAMES",
    "SourceEndpoint",
    "get_model_source",
    "list_model_sources",
    "model_source_for_template",
    "required_env_vars_for_source",
    "resolve_model_source_id",
    "template_env_vars_by_template",
    "validate_model_sources",
]
