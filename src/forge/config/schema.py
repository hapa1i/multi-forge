"""Configuration schema definitions using dataclasses.

This module defines the structure of all Forge configuration using dataclasses.
Each dataclass represents a configuration section with typed fields and defaults.

The schema is hierarchical:
    ForgeConfig
    ├── proxy: ProxyConfig
    │   ├── gemini: ProviderConfig
    │   ├── openai: ProviderConfig
    │   └── litellm: ProviderConfig
    ├── session: SessionConfig
    └── (future: mcp, policy, status, etc.)

Usage:
    from forge.config import config

    model = config.proxy.litellm.tiers.opus
    overrides = config.proxy.litellm.tier_overrides.get("opus")
"""

import re
from dataclasses import dataclass, field
from typing import Any

# --- CONSTANTS ---

OPENAI_MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-5",
    "gpt-5-codex",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-pro",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.1-codex-mini",
    "gpt-5.1-mini",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.2-pro",
    "gpt-5.3-codex",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.4-pro",
    "o1",
    "o1-mini",
    "o3",
    "o3-mini",
    "o3-pro",
    "o4-mini",
    "o4-mini-high",
]


# --- HELPER FUNCTIONS ---


def is_openai_model(model_name: str) -> bool:
    """Check if a model name refers to an OpenAI model.

    Uses strict allowlist-only matching against OPENAI_MODELS.
    No prefix heuristics - unknown gpt-* models will return False.

    Strips known provider prefixes (openai/, anthropic/) before matching.
    """
    clean_name = model_name.lower()

    if clean_name.startswith("anthropic/"):
        clean_name = clean_name[10:]
    elif clean_name.startswith("openai/"):
        clean_name = clean_name[7:]

    return clean_name in {m.lower() for m in OPENAI_MODELS}


# --- DATACLASSES ---


@dataclass
class TierModels:
    """Model mappings for each tier (haiku/sonnet/opus)."""

    haiku: str = ""
    sonnet: str = ""
    opus: str = ""

    def get(self, tier: str) -> str:
        """Get model for tier name."""
        return getattr(self, tier.lower(), self.sonnet)


@dataclass
class TierOverride:
    """Per-tier hyperparameter overrides.

    Use this to differentiate tiers that map to the same model.
    For example, if both sonnet and opus map to gpt-5.2, use tier_overrides
    to give opus higher reasoning_effort than sonnet.

    Values here override model catalog defaults. None means "use catalog default".
    """

    reasoning_effort: str | None = None  # none, low, medium, high, xhigh (model-dependent)
    verbosity: str | None = None  # low, medium, high
    temperature: float | None = None  # Override temperature for this tier
    thinking_budget_tokens: int | None = None  # For models with thinking budgets


@dataclass
class TierOverrides:
    """Per-tier overrides for hyperparameters.

    This structure allows families and proxies to customize behavior per tier,
    which is essential when multiple tiers map to the same underlying model.

    Flow:
    1. Family config defines tier_overrides as template defaults
    2. Proxy acquisition copies these to proxy overlay
    3. CLI args can override at acquisition time
    4. Proxy overlay can be modified at runtime
    """

    haiku: TierOverride | None = None
    sonnet: TierOverride | None = None
    opus: TierOverride | None = None

    def get(self, tier: str) -> TierOverride | None:
        """Get override for tier name, or None if not set."""
        return getattr(self, tier.lower(), None)


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider (Gemini, OpenAI, LiteLLM)."""

    tiers: TierModels = field(default_factory=TierModels)
    tier_overrides: TierOverrides = field(default_factory=TierOverrides)
    model_alternatives: dict[str, dict[str, str]] = field(default_factory=dict)
    auth_url: str = ""
    base_url: str = ""
    cache_ttl: float = 3600.0
    top_p: float | None = None
    enable_preamble: bool = False

    # LiteLLM-specific: API mode for OpenAI models
    openai_api_mode: str = "auto"  # auto, responses, chat_completions

    # Prompt caching mode (only affects Anthropic/Bedrock models via LiteLLM)
    # "passthrough": forward client cache_control unchanged (default)
    # "auto_inject": auto-add cache_control for long prompts
    prompt_caching: str = "passthrough"
    auto_cache_min_tokens: int = 1024

    # Error hint enrichment: append corrective hints to tool_result errors
    # before forwarding to the LLM, helping non-Claude models recover faster.
    error_hints: bool = False


def _coerce_optional_usd_cap(name: str, value: Any) -> float | None:
    """Coerce an optional USD cap to a positive float."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"Invalid {name}: must be a positive number of USD")
    try:
        amount = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {name}: must be a positive number of USD") from None
    if amount <= 0:
        raise ValueError(f"Invalid {name}: must be greater than 0")
    return amount


@dataclass
class CostCaps:
    """Spend cap configuration for a proxy."""

    per_day: float | None = None  # USD, rolling 24h window
    per_month: float | None = None  # USD, calendar month

    def __post_init__(self) -> None:
        self.per_day = _coerce_optional_usd_cap("costs.caps.per_day", self.per_day)
        self.per_month = _coerce_optional_usd_cap("costs.caps.per_month", self.per_month)


def _coerce_cost_caps(value: Any) -> CostCaps:
    """Normalize raw cost cap mappings into ``CostCaps``."""
    if value is None:
        return CostCaps()
    if isinstance(value, CostCaps):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid costs.caps: must be a mapping")
    return CostCaps(
        per_day=value.get("per_day"),
        per_month=value.get("per_month"),
    )


@dataclass
class CostConfig:
    """Cost tracking and cap configuration for a proxy."""

    caps: CostCaps = field(default_factory=CostCaps)
    on_cap_hit: str = "reject"  # "reject" (HTTP 429) or "warn" (header only)

    def __post_init__(self) -> None:
        self.caps = _coerce_cost_caps(self.caps)

        valid_actions = {"reject", "warn"}
        if self.on_cap_hit not in valid_actions:
            raise ValueError(
                f"Invalid on_cap_hit: '{self.on_cap_hit}' (must be one of: {', '.join(sorted(valid_actions))})"
            )


def _coerce_cost_config(value: Any) -> CostConfig:
    """Normalize raw proxy.yaml cost config into ``CostConfig``."""
    if value is None:
        return CostConfig()
    if isinstance(value, CostConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid costs: must be a mapping")
    if "cap_mode" in value:
        # Removed in metric-evidence Phase 3: caps have one behavior now (post-event). The
        # costs block is otherwise leniently parsed, so a removed key must be rejected
        # explicitly or it would be silently ignored (coding-standards: removed = tombstone).
        raise ValueError(
            "costs.cap_mode is no longer supported. Forge enforces spend caps after each "
            "completed request; there is no pre-flight 'strict' mode. Remove costs.cap_mode "
            "from proxy.yaml."
        )
    return CostConfig(
        caps=_coerce_cost_caps(value.get("caps", {}) or {}),
        on_cap_hit=value.get("on_cap_hit", "reject"),
    )


# --- Intercept / audit config (Phase 2 audit proxy) ---

_VALID_INTERCEPT_MODES = ("passthrough", "inspect", "override")
_VALID_WIRE_SHAPES = ("openai_translated", "anthropic_passthrough")
_VALID_GUARD_ACTIONS = ("warn", "block", "strip")
_DEFAULT_REDACT_HEADERS = (
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "anthropic-api-key",
    "openai-api-key",
    "openrouter-api-key",
    "x-goog-api-key",
    "cookie",
    "set-cookie",
)


def _reject_unknown_keys(value: dict, allowed: set[str], where: str) -> None:
    """Reject unknown keys in intercept/audit config (coding-standards §5).

    Unlike CostConfig's lenient .get() coercion, intercept/audit are security
    controls: a silently-ignored typo (e.g. audit.full_body) would leave the
    control OFF without telling the user, so unknown keys are corruption here.
    """
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"Unknown {where} key(s): {', '.join(sorted(unknown))}")


@dataclass
class InterceptOverrideConfig:
    """Override-mode mutation directives (applied only when intercept.mode='override').

    Targets are current-request control surfaces (mutation-safety invariant):
    cache-aware system-prompt augmentation and guard checks. Reasoning-effort
    pinning reuses tier_overrides.<tier>.reasoning_effort, not a field here.
    """

    system_prompt_augment: str = ""
    system_prompt_guards: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.system_prompt_augment, str):
            raise ValueError("intercept.override.system_prompt_augment must be a string")
        if not isinstance(self.system_prompt_guards, list):
            raise ValueError("intercept.override.system_prompt_guards must be a list")
        for guard in self.system_prompt_guards:
            if not isinstance(guard, dict) or "pattern" not in guard:
                raise ValueError("each intercept.override.system_prompt_guards entry needs a 'pattern' key")
            unknown = set(guard) - {"pattern", "action"}
            if unknown:
                raise ValueError(f"Unknown system_prompt_guards key(s): {', '.join(sorted(unknown))}")
            pattern = guard.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                raise ValueError("system_prompt_guards 'pattern' must be a non-empty string")
            # Compile now so a bad regex fails loudly at config time, not silently at
            # runtime (a skipped guard is a disabled security control).
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Invalid system_prompt_guards regex {pattern!r}: {e}") from e
            action = guard.get("action", "warn")
            if action not in _VALID_GUARD_ACTIONS:
                raise ValueError(
                    f"Invalid system_prompt_guards action: {action!r} (must be one of: {', '.join(_VALID_GUARD_ACTIONS)})"
                )


def _coerce_intercept_override(value: Any) -> InterceptOverrideConfig:
    if value is None:
        return InterceptOverrideConfig()
    if isinstance(value, InterceptOverrideConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid intercept.override: must be a mapping")
    _reject_unknown_keys(value, {"system_prompt_augment", "system_prompt_guards"}, "intercept.override")
    return InterceptOverrideConfig(
        system_prompt_augment=value.get("system_prompt_augment", ""),
        system_prompt_guards=value.get("system_prompt_guards", []) or [],
    )


@dataclass
class InterceptConfig:
    """Per-proxy wire-intercept mode (Phase 2 audit proxy).

    mode='passthrough' (default) leaves existing proxies unchanged: no body
    inspection, no mutation. 'inspect' observes (hash/drift/audit metadata).
    'override' additionally applies the override directives.
    """

    mode: str = "passthrough"
    override: InterceptOverrideConfig = field(default_factory=InterceptOverrideConfig)

    def __post_init__(self) -> None:
        if self.mode not in _VALID_INTERCEPT_MODES:
            raise ValueError(
                f"Invalid intercept.mode: {self.mode!r} (must be one of: {', '.join(_VALID_INTERCEPT_MODES)})"
            )
        self.override = _coerce_intercept_override(self.override)


def _coerce_intercept_config(value: Any) -> InterceptConfig:
    if value is None:
        return InterceptConfig()
    if isinstance(value, InterceptConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid intercept: must be a mapping")
    _reject_unknown_keys(value, {"mode", "override"}, "intercept")
    return InterceptConfig(
        mode=value.get("mode", "passthrough"),
        override=_coerce_intercept_override(value.get("override", {}) or {}),
    )


@dataclass
class AuditConfig:
    """Per-proxy audit logging configuration (Phase 2 audit proxy).

    Metadata-only audit is implied by intercept.mode in (inspect, override).
    audit_full_body is the high-risk opt-in for redacted full request/response
    capture; retention_days/max_total_mb bound on-disk exposure.
    """

    audit_full_body: bool = False
    redact_headers: list[str] = field(default_factory=list)
    retention_days: int = 14
    max_total_mb: int = 512

    def __post_init__(self) -> None:
        if not isinstance(self.audit_full_body, bool):
            raise ValueError("audit.audit_full_body must be a bool")
        if not isinstance(self.redact_headers, list):
            raise ValueError("audit.redact_headers must be a list")
        # bool is an int subclass; reject it explicitly so audit.retention_days=true fails.
        if isinstance(self.retention_days, bool) or not isinstance(self.retention_days, int) or self.retention_days < 0:
            raise ValueError("audit.retention_days must be a non-negative int")
        if isinstance(self.max_total_mb, bool) or not isinstance(self.max_total_mb, int) or self.max_total_mb <= 0:
            raise ValueError("audit.max_total_mb must be a positive int")
        self.redact_headers = [h.lower() for h in self.redact_headers]

    def effective_redact_headers(self) -> set[str]:
        """Return the union of default + user-configured redacted header names.

        User-supplied names are added to the defaults, never replace them — you
        cannot accidentally un-redact authorization.
        """
        return {h.lower() for h in _DEFAULT_REDACT_HEADERS} | set(self.redact_headers)


def _coerce_audit_config(value: Any) -> AuditConfig:
    if value is None:
        return AuditConfig()
    if isinstance(value, AuditConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid audit: must be a mapping")
    _reject_unknown_keys(value, {"audit_full_body", "redact_headers", "retention_days", "max_total_mb"}, "audit")
    return AuditConfig(
        audit_full_body=value.get("audit_full_body", False),
        redact_headers=value.get("redact_headers", []) or [],
        retention_days=value.get("retention_days", 14),
        max_total_mb=value.get("max_total_mb", 512),
    )


@dataclass
class ProviderTraceConfig:
    """Retention bounds for the provider-trace plane (openrouter_observability Phase 3).

    Diagnostics, not spend truth — matches the audit plane's defaults (14d / 512 MB) so the
    two on-disk telemetry surfaces share one mental model.
    """

    retention_days: int = 14
    max_total_mb: int = 512
    inject_openrouter_user: bool = False

    def __post_init__(self) -> None:
        # bool is an int subclass; reject it so provider_trace.retention_days=true fails loudly.
        if isinstance(self.retention_days, bool) or not isinstance(self.retention_days, int) or self.retention_days < 0:
            raise ValueError("provider_trace.retention_days must be a non-negative int")
        if isinstance(self.max_total_mb, bool) or not isinstance(self.max_total_mb, int) or self.max_total_mb <= 0:
            raise ValueError("provider_trace.max_total_mb must be a positive int")
        # Opt-in (default off): forward the Forge session grouping id into OpenRouter's `user`
        # field on the proxied direct-OpenRouter path (openrouter_observability Phase 5).
        if not isinstance(self.inject_openrouter_user, bool):
            raise ValueError("provider_trace.inject_openrouter_user must be a bool")


def _coerce_provider_trace_config(value: Any) -> ProviderTraceConfig:
    if value is None:
        return ProviderTraceConfig()
    if isinstance(value, ProviderTraceConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid provider_trace: must be a mapping")
    _reject_unknown_keys(value, {"retention_days", "max_total_mb", "inject_openrouter_user"}, "provider_trace")
    return ProviderTraceConfig(
        retention_days=value.get("retention_days", 14),
        max_total_mb=value.get("max_total_mb", 512),
        inject_openrouter_user=value.get("inject_openrouter_user", False),
    )


_VALID_REQUEST_LOG_ENABLED = ("auto", "off", "on")
_VALID_REQUEST_LOG_CAPTURE = ("metadata", "redacted")


@dataclass
class RequestLogConfig:
    """Per-proxy bounded request/response diagnostics (proxy_log_hygiene).

    Controls the redacted request JSONL under ``~/.forge/logs/requests/``. There is NO
    plaintext/full body mode -- bodies are always redacted (audit policy, design §7.x).

    - ``enabled='auto'`` preserves the historical coupling to ``log_level=debug``; ``'on'``
      decouples bounded capture from full debug logging; ``'off'`` disables it.
    - ``body_capture``/``response_capture``: ``metadata`` (no body) vs ``redacted`` (sanitized
      structure via the audit redaction builders).
    - ``max_file_mb``/``max_total_mb``/``retention_days``: prune budgets (0 = unbounded).
    - ``stream_chunks``: opt-in bounded per-chunk debug dumps (off even at ``log_level=debug``
      by default); ``stream_chunk_max_bytes`` caps each dumped chunk (0 = a small default cap).
    """

    enabled: str = "auto"
    body_capture: str = "metadata"
    response_capture: str = "metadata"
    max_file_mb: int = 16
    max_total_mb: int = 256
    retention_days: int = 14
    stream_chunks: bool = False
    stream_chunk_max_bytes: int = 0

    def __post_init__(self) -> None:
        if self.enabled not in _VALID_REQUEST_LOG_ENABLED:
            raise ValueError(
                f"logging.requests.enabled must be one of {', '.join(_VALID_REQUEST_LOG_ENABLED)} (got {self.enabled!r})"
            )
        for fname in ("body_capture", "response_capture"):
            val = getattr(self, fname)
            if val not in _VALID_REQUEST_LOG_CAPTURE:
                hint = ""
                if val == "full":
                    hint = (
                        " There is no plaintext/full body mode -- request logging follows the audit "
                        "redacted-body policy (design §7.x). Use 'redacted' for sanitized structure."
                    )
                raise ValueError(
                    f"logging.requests.{fname} must be one of {', '.join(_VALID_REQUEST_LOG_CAPTURE)} "
                    f"(got {val!r})." + hint
                )
        # bool is an int subclass; reject it so logging.requests.max_file_mb=true fails loudly.
        # 0 means unbounded (matches the prune helper + global log_retention_days semantics).
        for fname in ("max_file_mb", "max_total_mb", "retention_days", "stream_chunk_max_bytes"):
            val = getattr(self, fname)
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise ValueError(f"logging.requests.{fname} must be a non-negative int")
        if not isinstance(self.stream_chunks, bool):
            raise ValueError("logging.requests.stream_chunks must be a bool")


def _coerce_request_log_config(value: Any) -> RequestLogConfig:
    if value is None:
        return RequestLogConfig()
    if isinstance(value, RequestLogConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid logging.requests: must be a mapping")
    _reject_unknown_keys(
        value,
        {
            "enabled",
            "body_capture",
            "response_capture",
            "max_file_mb",
            "max_total_mb",
            "retention_days",
            "stream_chunks",
            "stream_chunk_max_bytes",
        },
        "logging.requests",
    )
    return RequestLogConfig(
        enabled=value.get("enabled", "auto"),
        body_capture=value.get("body_capture", "metadata"),
        response_capture=value.get("response_capture", "metadata"),
        max_file_mb=value.get("max_file_mb", 16),
        max_total_mb=value.get("max_total_mb", 256),
        retention_days=value.get("retention_days", 14),
        stream_chunks=value.get("stream_chunks", False),
        stream_chunk_max_bytes=value.get("stream_chunk_max_bytes", 0),
    )


@dataclass
class LoggingConfig:
    """Per-proxy logging namespace. Currently just ``requests`` (bounded request diagnostics);
    forward-compatible with future ``logging.*`` sub-blocks."""

    requests: RequestLogConfig = field(default_factory=RequestLogConfig)

    def __post_init__(self) -> None:
        self.requests = _coerce_request_log_config(self.requests)


def _coerce_logging_config(value: Any) -> LoggingConfig:
    if value is None:
        return LoggingConfig()
    if isinstance(value, LoggingConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("Invalid logging: must be a mapping")
    _reject_unknown_keys(value, {"requests"}, "logging")
    return LoggingConfig(requests=_coerce_request_log_config(value.get("requests", {}) or {}))


@dataclass
class BackendDependency:
    """Backend dependency declaration (proxy runtime requirement).

    Declares that a proxy template requires a backend service to be running.
    Example: local LiteLLM proxies require LiteLLM backend on port 4000.
    """

    adapter: str  # e.g., "litellm"
    port: int
    required_env_vars: list[str] = field(default_factory=list)


def _validate_wire_shape_intercept(wire_shape: str, intercept: InterceptConfig) -> None:
    """Reject intercept.mode='override' unless wire_shape='anthropic_passthrough'.

    override mutates the RAW Anthropic body, so the openai_translated path cannot apply it.
    Enforced on BOTH the running-proxy (ProxyInstanceConfig) and template (ProxyConfig) paths
    so 'forge proxy template edit' fails at edit time, not late at 'forge proxy create'.
    """
    if intercept.mode == "override" and wire_shape != "anthropic_passthrough":
        raise ValueError(
            "intercept.mode='override' requires wire_shape='anthropic_passthrough' "
            "(override applies to the raw passthrough body only). "
            "Set wire_shape: anthropic_passthrough, or use intercept.mode: inspect."
        )


_VALID_DEFAULT_TIERS = frozenset({"haiku", "sonnet", "opus"})


def _validate_default_tier(default_tier: str) -> None:
    """Reject a default_tier outside the user-facing tier allowlist.

    Enforced on BOTH ProxyConfig (template path) and ProxyInstanceConfig (running
    proxy) so a bad default_tier fails at 'forge proxy template edit', not late at
    'forge proxy create'.
    """
    if default_tier not in _VALID_DEFAULT_TIERS:
        raise ValueError(
            f"Invalid default_tier: '{default_tier}' (must be one of: {', '.join(sorted(_VALID_DEFAULT_TIERS))})"
        )


@dataclass
class ProxyConfig:
    """Proxy server configuration."""

    gemini: ProviderConfig = field(default_factory=ProviderConfig)
    openai: ProviderConfig = field(default_factory=ProviderConfig)
    litellm: ProviderConfig = field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = field(default_factory=ProviderConfig)

    family: str = ""  # model family (e.g., "openai", "anthropic", "gemini")
    preferred_provider: str = ""  # set by --template flag
    active_template: str = ""
    default_tier: str = "sonnet"
    backend_dependency: BackendDependency | None = None
    default_port: int = 8082
    host: str = "127.0.0.1"
    tool_prefixes_to_ignore: list[str] = field(default_factory=list)
    costs: CostConfig = field(default_factory=CostConfig)
    wire_shape: str = "openai_translated"
    intercept: InterceptConfig = field(default_factory=InterceptConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    provider_trace: ProviderTraceConfig = field(default_factory=ProviderTraceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def __post_init__(self) -> None:
        # Templates carry wire_shape/intercept/audit/provider_trace/logging/costs/default_tier/
        # tier_overrides too; coerce + validate here so an invalid combo is rejected at
        # 'forge proxy template edit', not late at 'forge proxy create' (parity with ProxyInstanceConfig).
        self.intercept = _coerce_intercept_config(self.intercept)
        self.audit = _coerce_audit_config(self.audit)
        self.provider_trace = _coerce_provider_trace_config(self.provider_trace)
        self.logging = _coerce_logging_config(self.logging)
        self.costs = _coerce_cost_config(self.costs)
        if self.wire_shape not in _VALID_WIRE_SHAPES:
            raise ValueError(
                f"Invalid wire_shape: {self.wire_shape!r} (must be one of: {', '.join(_VALID_WIRE_SHAPES)})"
            )
        _validate_wire_shape_intercept(self.wire_shape, self.intercept)
        _validate_default_tier(self.default_tier)
        # Per-provider overrides: the constraint check skips tiers with no model, so empty/partial
        # providers no-op and only a concrete unsupported override (its tier's model set) is
        # rejected -- no false positives on templates whose model mapping resolves later.
        for _prov in (self.gemini, self.openai, self.litellm, self.openrouter):
            _validate_static_tier_override_constraints(_prov.tiers, _prov.tier_overrides)

    def get_provider(self, name: str | None = None) -> ProviderConfig:
        """Get provider config by name, defaulting to preferred_provider."""
        provider = name or self.preferred_provider or "litellm"
        return getattr(self, provider, self.litellm)

    def get_model_for_tier(self, tier: str) -> str:
        """Get the configured model for a tier based on preferred_provider."""
        provider = self.get_provider()
        return provider.tiers.get(tier)


@dataclass
class SessionConfig:
    """Session management configuration."""

    default_tier: str = "sonnet"
    manifest_filename: str = "forge.session.json"
    forge_home: str = ""  # default: ~/.forge


@dataclass
class ProxyInstanceConfig:
    """Complete proxy instance configuration owned by the user.

    Unlike the previous overlay model where proxies only stored tier_overrides
    and merged with templates at runtime, this dataclass contains the full
    configuration. The user owns the entire file and can edit it directly.

    Flow:
    1. User runs `forge proxy create litellm-gemini`
    2. Template is copied to ~/.forge/proxies/{id}/proxy.yaml
    3. User can edit the file with `forge proxy edit {id}`
    4. Proxy reads this file directly at startup (no merge logic)

    The template and template_digest fields are informational only —
    they enable future `forge proxy rebase` functionality.
    """

    proxy_format: int

    template: str  # e.g., "litellm-gemini"
    template_digest: str  # SHA256 at creation time

    provider: str  # litellm | openai | gemini
    proxy_endpoint: str  # e.g., http://localhost:8085
    port: int
    upstream_base_url: str  # e.g., https://litellm.corp.com

    tiers: TierModels
    family: str = ""  # model family (e.g., "openai", "anthropic", "gemini")
    tier_overrides: TierOverrides = field(default_factory=TierOverrides)
    model_alternatives: dict[str, dict[str, str]] = field(default_factory=dict)
    default_tier: str = "sonnet"

    provider_settings: dict[str, Any] = field(default_factory=dict)

    # Copied from template into proxy.yaml; controls Anthropic/Bedrock prompt caching via LiteLLM.
    prompt_caching: str = "passthrough"
    auto_cache_min_tokens: int = 1024

    costs: CostConfig = field(default_factory=CostConfig)
    wire_shape: str = "openai_translated"
    intercept: InterceptConfig = field(default_factory=InterceptConfig)
    audit: AuditConfig = field(default_factory=AuditConfig)
    provider_trace: ProviderTraceConfig = field(default_factory=ProviderTraceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        """Validate proxy instance configuration fields."""
        if self.proxy_format != 1:
            raise ValueError(f"Unsupported proxy_format: {self.proxy_format} (expected 1)")

        valid_providers = {"litellm", "openai", "gemini", "openrouter"}
        if self.provider not in valid_providers:
            raise ValueError(
                f"Invalid provider: '{self.provider}' (must be one of: {', '.join(sorted(valid_providers))})"
            )

        if not self.proxy_endpoint:
            raise ValueError("proxy_endpoint is required (e.g., 'http://localhost:8085')")
        if not self.upstream_base_url:
            raise ValueError("upstream_base_url is required (e.g., 'https://litellm.corp.com')")

        if not 1 <= self.port <= 65535:
            raise ValueError(f"Invalid port: {self.port} (must be 1-65535)")

        if not self.tiers.sonnet:
            raise ValueError("Tiers must define at least 'sonnet' model")

        _validate_default_tier(self.default_tier)

        self.costs = _coerce_cost_config(self.costs)

        if self.wire_shape not in _VALID_WIRE_SHAPES:
            raise ValueError(
                f"Invalid wire_shape: {self.wire_shape!r} (must be one of: {', '.join(_VALID_WIRE_SHAPES)})"
            )
        self.intercept = _coerce_intercept_config(self.intercept)
        self.audit = _coerce_audit_config(self.audit)
        self.provider_trace = _coerce_provider_trace_config(self.provider_trace)
        self.logging = _coerce_logging_config(self.logging)
        _validate_wire_shape_intercept(self.wire_shape, self.intercept)

        _validate_static_tier_override_constraints(self.tiers, self.tier_overrides)


def _validate_static_tier_override_constraints(tiers: TierModels, overrides: TierOverrides) -> None:
    """Reject Forge-owned config overrides that known models do not support."""
    try:
        from forge.core.models.catalog import (
            ModelCatalogError,
            get_model_spec,
            resolve_model_id,
        )
    except Exception:
        # Catalog import can fail during early bootstrap; provider APIs still
        # reject unsupported overrides at request time as a safety net.
        return

    for tier in ("haiku", "sonnet", "opus"):
        override = overrides.get(tier)
        if override is None:
            continue

        model_name = tiers.get(tier)
        if not model_name:
            continue

        lookup_name = model_name.removesuffix("[1m]")
        try:
            canonical_model = resolve_model_id(lookup_name)
            spec = get_model_spec(canonical_model)
        except ModelCatalogError:
            continue

        if spec.supports_sampling_overrides is False and override.temperature is not None:
            raise ValueError(
                f"tier_overrides.{tier}.temperature is not supported by {canonical_model}; "
                "remove the override or choose a model that supports sampling overrides"
            )

        if spec.thinking_modes == ("adaptive",) and override.thinking_budget_tokens is not None:
            raise ValueError(
                f"tier_overrides.{tier}.thinking_budget_tokens is not supported by {canonical_model}; "
                "this model only supports adaptive thinking"
            )

        if (
            override.reasoning_effort is not None
            and spec.litellm_reasoning_efforts is not None
            and override.reasoning_effort not in spec.litellm_reasoning_efforts
        ):
            supported = ", ".join(spec.litellm_reasoning_efforts)
            raise ValueError(
                f"tier_overrides.{tier}.reasoning_effort={override.reasoning_effort!r} is not supported by "
                f"{canonical_model}; supported values: {supported}"
            )


@dataclass
class ForgeConfig:
    """Root configuration for all Forge components.

    This is the top-level config that aggregates all component configs.
    Access via the singleton: `from forge.config import config`
    """

    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    session: SessionConfig = field(default_factory=SessionConfig)

    # Future: mcp, policy, status

    def to_dict(self) -> dict[str, Any]:
        """Convert config to nested dict (for serialization)."""
        from dataclasses import asdict

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ForgeConfig":
        """Create config from nested dict."""
        from forge.config.dataclass_utils import dict_to_dataclass

        return dict_to_dataclass(cls, data)
