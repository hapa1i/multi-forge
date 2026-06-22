"""Forge runtime configuration (~/.forge/config.yaml).

Separate from forge.config (which the proxy imports for routing) so runtime
preferences never affect tier->model routing. The proxy MAY read specific
non-routing fields here (auth_ignore_env, log_tool_failures, and the global
provider_trace.inject_provider_user observability toggle); none of them may
influence a routing decision.

File: ~/.forge/config.yaml (optional, fail-open if missing or invalid).

Three-layer resolution (highest precedence wins):
  1. Built-in defaults (dataclass field defaults)
  2. ~/.forge/config.yaml
  3. Environment variables (via _ENV_OVERRIDES mapping)
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from forge.core.paths import get_forge_home

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.yaml"

# Env var → field name mapping. Env vars override YAML values when present.
# This is the single source of truth for env-to-config overrides.
_ENV_OVERRIDES: dict[str, str] = {
    "FORGE_DEBUG": "log_level",
}

# Valid enum values for StatusLineConfig fields.
_VALID_COST_MODES = ("auto", "api", "subscription")
_VALID_PALETTES = ("default", "earthy")
_VALID_GLYPHS = ("ascii", "unicode")
_VALID_CACHE_HIT = ("auto", "off")


@dataclass
class StatusLineConfig:
    """Nested status-line display preferences (``statusline:`` in config.yaml).

    Segment NAMES are deliberately NOT validated here (see
    ``forge.cli.statusline.names``): the renderer drops unknown names and
    ``forge config set``/``edit`` reject them, so this dataclass needs no
    registry import. Enum fields ARE validated strictly — a bad value raises,
    making ``set``/``edit`` fail closed; the disk loader catches that and falls
    back to defaults (fail-open, subtree-scoped).
    """

    segments: list[str] = field(default_factory=list)  # empty -> names.DEFAULT_ORDER
    cost_mode: str = "auto"  # auto | api | subscription
    palette: str = "default"  # default | earthy
    glyphs: str = "ascii"  # ascii | unicode
    cache_hit: str = "auto"  # auto | off
    cache_hit_ttl: int = 12  # direct-mode throttle window (seconds)
    forge_cost_ttl: int = 10  # forge_cost segment throttle window (seconds)

    def __post_init__(self) -> None:
        if self.cost_mode not in _VALID_COST_MODES:
            raise ValueError(
                f"Invalid statusline.cost_mode: '{self.cost_mode}' (must be one of: {', '.join(_VALID_COST_MODES)})"
            )
        if self.palette not in _VALID_PALETTES:
            raise ValueError(
                f"Invalid statusline.palette: '{self.palette}' (must be one of: {', '.join(_VALID_PALETTES)})"
            )
        if self.glyphs not in _VALID_GLYPHS:
            raise ValueError(f"Invalid statusline.glyphs: '{self.glyphs}' (must be one of: {', '.join(_VALID_GLYPHS)})")
        if self.cache_hit not in _VALID_CACHE_HIT:
            raise ValueError(
                f"Invalid statusline.cache_hit: '{self.cache_hit}' (must be one of: {', '.join(_VALID_CACHE_HIT)})"
            )
        if not isinstance(self.segments, list) or not all(isinstance(s, str) for s in self.segments):
            raise ValueError("statusline.segments must be a list of strings")
        if self.cache_hit_ttl < 1:
            raise ValueError(f"statusline.cache_hit_ttl must be >= 1, got {self.cache_hit_ttl}")
        if self.forge_cost_ttl < 1:
            raise ValueError(f"statusline.forge_cost_ttl must be >= 1, got {self.forge_cost_ttl}")


def _coerce_statusline_config(value: Any) -> StatusLineConfig:
    """Normalize a raw ``statusline`` value into ``StatusLineConfig``.

    Mirrors ``_coerce_cost_config`` in the proxy schema. Required because
    ``from __future__ import annotations`` makes field types strings (so the
    generic ``dict_to_dataclass`` won't auto-recurse) and because ``forge config
    set``/``edit`` build ``RuntimeConfig(**dict)`` directly — ``__post_init__``
    is the single convergence point. Unknown sub-keys are dropped (forward
    compat); known fields are validated by ``StatusLineConfig.__post_init__``.
    """
    if value is None:
        return StatusLineConfig()
    if isinstance(value, StatusLineConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("statusline must be a mapping")
    known = {f.name for f in fields(StatusLineConfig)}
    kwargs = {k: v for k, v in value.items() if k in known}
    return StatusLineConfig(**kwargs)


@dataclass
class RuntimeProviderTraceConfig:
    """Nested provider-trace preferences (``provider_trace:`` in config.yaml).

    Home of the single, global ``inject_provider_user`` toggle. It governs BOTH
    Forge's direct ``core.llm`` OpenRouter callers (plan-check, transfer curation)
    AND the proxied path (``proxy/server.py`` reads this, not the per-proxy
    ``proxy.yaml`` key, which is deprecated). One switch, one mental model.

    Retention of the on-disk trace shards stays proxy-owned in ``proxy.yaml``
    (``provider_trace.retention_days``/``max_total_mb``) — that is a proxy-local
    disk concern; whether to group at all is a global observability preference.
    """

    inject_provider_user: bool = False  # opt-in: record the hashed session id in OpenRouter's `user`

    def __post_init__(self) -> None:
        # Strict bool — fail-closed via set/edit; the disk loader's subtree
        # fail-open catches this and degrades to the default (see _coerce_bool).
        if not isinstance(self.inject_provider_user, bool):
            raise ValueError("provider_trace.inject_provider_user must be a bool")


def _coerce_bool(value: Any) -> Any:
    """Coerce a YAML/CLI scalar to bool, or pass through for __post_init__ to reject.

    A quoted ``"true"`` in config.yaml parses as a string; without this it would
    fail the strict bool check and silently degrade to the default (the opposite
    of what the user wrote). Unrecognized values pass through unchanged so the
    dataclass raises a clear error rather than guessing.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"1", "true", "yes", "on"}:
            return True
        if low in {"0", "false", "no", "off", ""}:
            return False
    return value


def _coerce_provider_trace_config(value: Any) -> RuntimeProviderTraceConfig:
    """Normalize a raw ``provider_trace`` value into ``RuntimeProviderTraceConfig``.

    Mirrors ``_coerce_statusline_config``: required because ``from __future__
    import annotations`` makes field types strings, and because set/edit build
    ``RuntimeConfig(**dict)`` directly. Unknown sub-keys are dropped (forward
    compat); ``inject_provider_user`` is bool-coerced before validation.
    """
    if value is None:
        return RuntimeProviderTraceConfig()
    if isinstance(value, RuntimeProviderTraceConfig):
        return value
    if not isinstance(value, dict):
        raise ValueError("provider_trace must be a mapping")
    known = {f.name for f in fields(RuntimeProviderTraceConfig)}
    kwargs = {k: v for k, v in value.items() if k in known}
    if "inject_provider_user" in kwargs:
        kwargs["inject_provider_user"] = _coerce_bool(kwargs["inject_provider_user"])
    return RuntimeProviderTraceConfig(**kwargs)


@dataclass
class RuntimeConfig:
    """Global Forge runtime preferences — always reflects effective values.

    Three-layer resolution: built-in defaults → config.yaml → env vars.
    After loading, all fields represent the effective runtime state.
    They do NOT affect proxy routing (that's ForgeConfig's domain).

    All fields have sensible defaults — the config file is optional.
    """

    # Proxy execution mode: "host" runs proxy on host, "sidecar" bundles in Docker
    proxy_mode: str = "host"

    sidecar_image: str = "forge-sidecar:latest"

    # Version string sent in the User-Agent header to upstream LLM providers.
    user_agent_claude_code_version: str = ""

    # Optional model override for direct (non-proxy) sessions.
    # Passed to Claude Code via ANTHROPIC_MODEL + ANTHROPIC_DEFAULT_*_MODEL.
    # Empty string = let Claude Code decide.
    default_direct_model: str = ""

    # Fallback auto-compact window for proxy mode when model lookup fails.
    # Passed as CLAUDE_CODE_AUTO_COMPACT_WINDOW to Claude Code.
    # Direct sessions don't use this — Claude Code handles its own context.
    context_limit: int = 200000

    # Status line timeout for proxy/git subprocess calls (seconds)
    status_timeout: float = 2.0

    # Memory writer default timeout (seconds)
    memory_writer_timeout: int = 300

    # File logging level: "off" (no file logging), "debug", "info", "warning"
    # Override: FORGE_DEBUG env var (1/true/yes → "debug", 0/false/no/off → "off")
    log_level: str = "off"

    # Auto-delete log files older than N days on CLI startup.
    # 0 = disabled (no auto-cleanup). Positive integer = retention window in days.
    log_retention_days: int = 0

    # Auto-delete sessions older than N days on CLI startup.
    # 0 = disabled (no auto-cleanup). Positive integer = retention window in days.
    # Keeps worktrees and branches; removes manifests, index entries, and Claude
    # transcripts (*.jsonl in ~/.claude/projects/). Forge artifact snapshots
    # under .forge/artifacts/ are NOT removed.
    session_retention_days: int = 0

    # Policy summary feedback after evaluations: "on" (default), "off".
    # Gates post-hoc "[forge] Policy: checked ..." summary lines and additionalContext.
    # Does NOT affect deny output or substantive warning lines -- those stay visible always.
    policy_summary_feedback: str = "on"

    # Upstream telemetry volume: "non_success" records failure/exception outcomes;
    # "all" also records successful deterministic passes and cached allows.
    upstream_event_volume: str = "non_success"

    # Log tool failures to ~/.forge/logs/tool_failures/ even without debug mode.
    # Off by default because records may include tool inputs and error payloads.
    log_tool_failures: bool = False

    # Ignore environment variables for credential resolution.
    # When true, Forge reads credentials only from ~/.forge/credentials.yaml,
    # ignoring shell env vars (ANTHROPIC_API_KEY, OPENROUTER_API_KEY, etc.).
    # Useful when shell API keys are for Claude Code (not Forge subprocesses).
    auth_ignore_env: bool = False

    # ANTHROPIC_API_KEY policy for Forge-managed interactive `claude` launches:
    # "inherit" (default) keeps the normal resolution (shell env, then credential
    # file); "omit" strips the key from the interactive child only, so a
    # subscription/OAuth session is not silently billed against a key meant for
    # other tools. Headless subprocesses (supervisor, memory writer, panel workers)
    # are unaffected and always keep normal credential resolution.
    interactive_anthropic_api_key: str = "inherit"

    # Nested status-line display preferences (statusline: section in config.yaml).
    statusline: StatusLineConfig = field(default_factory=StatusLineConfig)

    # Nested provider-trace preferences (provider_trace: section in config.yaml).
    # Home of the global inject_provider_user toggle (governs proxied + direct paths).
    provider_trace: RuntimeProviderTraceConfig = field(default_factory=RuntimeProviderTraceConfig)

    def __post_init__(self) -> None:
        # Coerce a raw dict (from YAML or `forge config set`/`edit`) into the
        # nested dataclass. This is the single convergence point for the load,
        # set, and edit paths (see _coerce_statusline_config).
        self.statusline = _coerce_statusline_config(self.statusline)
        self.provider_trace = _coerce_provider_trace_config(self.provider_trace)

        valid_modes = {"host", "sidecar"}
        if self.proxy_mode not in valid_modes:
            raise ValueError(
                f"Invalid proxy_mode: '{self.proxy_mode}' " f"(must be one of: {', '.join(sorted(valid_modes))})"
            )
        if self.context_limit < 1:
            raise ValueError(f"context_limit must be >= 1, got {self.context_limit}")
        if self.status_timeout <= 0:
            raise ValueError(f"status_timeout must be > 0, got {self.status_timeout}")
        if self.memory_writer_timeout < 1:
            raise ValueError(f"memory_writer_timeout must be >= 1, got {self.memory_writer_timeout}")
        valid_log_levels = {"off", "debug", "info", "warning"}
        if self.log_level not in valid_log_levels:
            raise ValueError(
                f"Invalid log_level: '{self.log_level}' (must be one of: {', '.join(sorted(valid_log_levels))})"
            )
        if self.log_retention_days < 0:
            raise ValueError(f"log_retention_days must be >= 0, got {self.log_retention_days}")
        if self.session_retention_days < 0:
            raise ValueError(f"session_retention_days must be >= 0, got {self.session_retention_days}")
        valid_feedback = {"on", "off"}
        if self.policy_summary_feedback not in valid_feedback:
            raise ValueError(
                f"Invalid policy_summary_feedback: '{self.policy_summary_feedback}' "
                f"(must be one of: {', '.join(sorted(valid_feedback))})"
            )
        valid_upstream_event_volume = {"non_success", "all"}
        if self.upstream_event_volume not in valid_upstream_event_volume:
            raise ValueError(
                f"Invalid upstream_event_volume: '{self.upstream_event_volume}' "
                f"(must be one of: {', '.join(sorted(valid_upstream_event_volume))})"
            )
        valid_interactive_key_modes = {"inherit", "omit"}
        if self.interactive_anthropic_api_key not in valid_interactive_key_modes:
            raise ValueError(
                f"Invalid interactive_anthropic_api_key: '{self.interactive_anthropic_api_key}' "
                f"(must be one of: {', '.join(sorted(valid_interactive_key_modes))})"
            )


def _coerce_debug_to_log_level(raw: str) -> str:
    """Coerce FORGE_DEBUG env var to a log_level string."""
    low = raw.lower()
    if low in ("1", "true", "yes"):
        return "debug"
    if low in ("0", "false", "no", "off"):
        return "off"
    if low in ("debug", "info", "warning"):
        return low
    raise ValueError(f"Cannot coerce FORGE_DEBUG={raw!r} to log level")


def _coerce_env_value(raw: str, field_info: Any) -> Any:
    """Coerce a raw env var string to the field's expected Python type."""
    ftype = field_info.type
    if ftype is int or ftype == "int":
        val = int(raw)
        if val < 1:
            raise ValueError(f"must be >= 1, got {val}")
        return val
    if ftype is float or ftype == "float":
        return float(raw)
    if ftype is bool or ftype == "bool":
        if raw.lower() in ("1", "true", "yes"):
            return True
        if raw.lower() in ("0", "false", "no"):
            return False
        raise ValueError(f"Cannot coerce {raw!r} to bool")
    return raw


def _apply_env_overrides(config: RuntimeConfig) -> RuntimeConfig:
    """Apply environment variable overrides to config values.

    Per-field: each env var is applied independently. If one parse fails,
    others still apply (fail-open per field, not all-or-nothing).
    Attaches _env_sources dict for display annotation by %config.
    """
    field_map = {f.name: f for f in fields(RuntimeConfig)}
    overrides: dict[str, Any] = {}
    env_sources: dict[str, str] = {}

    for env_var, field_name in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var, "").strip()
        if not raw:
            continue
        try:
            if field_name == "log_level":
                coerced = _coerce_debug_to_log_level(raw)
            else:
                coerced = _coerce_env_value(raw, field_map[field_name])
            overrides[field_name] = coerced
            env_sources[field_name] = env_var
        except (ValueError, TypeError) as e:
            logger.warning("Ignoring env %s=%r: %s", env_var, raw, e)

    if not overrides:
        object.__setattr__(config, "_env_sources", {})
        return config

    merged = asdict(config)
    merged.update(overrides)
    try:
        result = RuntimeConfig(**merged)
    except (ValueError, TypeError) as e:
        logger.warning("Env override produced invalid config: %s — ignoring overrides", e)
        object.__setattr__(config, "_env_sources", {})
        return config

    object.__setattr__(result, "_env_sources", env_sources)
    return result


# Singleton cache (must be after RuntimeConfig definition)
_config: RuntimeConfig | None = None


def get_config_path() -> Path:
    """Get the path to ~/.forge/config.yaml."""
    return get_forge_home() / CONFIG_FILENAME


def ensure_config() -> Path:
    """Ensure the config file exists, creating with defaults if missing.

    Returns the path to the config file. Idempotent — existing files
    are never overwritten.
    """
    config_path = get_config_path()
    if not config_path.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(get_default_config_content())
        os.chmod(str(config_path), 0o600)
    return config_path


def load_runtime_config(path: Path | None = None) -> RuntimeConfig:
    """Load runtime config from YAML file, then apply env var overrides.

    Three-layer resolution: built-in defaults → config.yaml → env vars.
    Fail-open: returns defaults if file is missing, unreadable, or invalid YAML.
    Unknown keys are warned and ignored (forward compatibility).

    Args:
        path: Override config file path (for testing). Defaults to ~/.forge/config.yaml.
    """
    config_path = path or get_config_path()

    if not config_path.is_file():
        return _apply_env_overrides(RuntimeConfig())

    try:
        import yaml

        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except Exception as e:
        logger.warning("Failed to read %s: %s — using defaults", config_path, e)
        return _apply_env_overrides(RuntimeConfig())

    if not isinstance(data, dict):
        logger.warning("%s is not a YAML mapping — using defaults", config_path)
        return _apply_env_overrides(RuntimeConfig())

    return _apply_env_overrides(_dict_to_runtime_config(data, config_path))


def _dict_to_runtime_config(data: dict[str, Any], source: Path) -> RuntimeConfig:
    """Convert a dict to RuntimeConfig, warning on unknown keys.

    System boundary: user-edited config. Strict on value validation, best-effort
    on unknown keys for forward compat (coding_standards.md §5, system boundaries).
    """
    known_fields = {f.name for f in fields(RuntimeConfig)}
    unknown = set(data.keys()) - known_fields

    if unknown:
        logger.warning(
            "Unknown keys in %s (ignored): %s",
            source,
            ", ".join(sorted(unknown)),
        )

    kwargs: dict[str, Any] = {}
    for f in fields(RuntimeConfig):
        if f.name in data:
            val = data[f.name]
            # YAML parses "off"/"on"/"yes"/"no" as booleans — coerce back
            # for string fields (e.g., log_level: off → False → "off")
            if isinstance(val, bool) and f.type in ("str", str):
                val = "on" if val else "off"
            # Coerce quoted strings to bool for bool fields
            # (auth_ignore_env: "false" should be False, not truthy string)
            elif isinstance(val, str) and f.type in (bool, "bool"):
                low = val.strip().lower()
                if low in {"1", "true", "yes", "on"}:
                    val = True
                elif low in {"0", "false", "no", "off", ""}:
                    val = False
                else:
                    logger.warning("Invalid boolean for %s: %r — using default", f.name, val)
                    continue
            kwargs[f.name] = val

    # Subtree fail-open: a bad statusline block must reset only statusline, not
    # discard other valid keys or trip the whole-config fallback below. (set/edit
    # construct RuntimeConfig directly and keep the strict raise — fail-closed.)
    if "statusline" in kwargs:
        try:
            _coerce_statusline_config(kwargs["statusline"])
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid statusline config in %s: %s — using statusline defaults",
                source,
                e,
            )
            kwargs["statusline"] = StatusLineConfig()

    # Same subtree fail-open for provider_trace: a bad block resets only this
    # section, never the whole config (set/edit keep the strict raise).
    if "provider_trace" in kwargs:
        try:
            _coerce_provider_trace_config(kwargs["provider_trace"])
        except (ValueError, TypeError) as e:
            logger.warning(
                "Invalid provider_trace config in %s: %s — using provider_trace defaults",
                source,
                e,
            )
            kwargs["provider_trace"] = RuntimeProviderTraceConfig()

    try:
        return RuntimeConfig(**kwargs)
    except (ValueError, TypeError) as e:
        logger.warning("Invalid config in %s: %s — using defaults", source, e)
        return RuntimeConfig()


def get_runtime_config() -> RuntimeConfig:
    """Get cached runtime config singleton (lazy-loaded on first access)."""
    global _config
    if _config is None:
        _config = load_runtime_config()
    return _config


def get_default_direct_model() -> str | None:
    """Get the configured direct-session model override, or None if unset."""
    return get_runtime_config().default_direct_model.strip() or None


def reset_runtime_config() -> None:
    """Reset the cached singleton (for testing)."""
    global _config
    _config = None


def write_runtime_config(config_data: dict[str, Any], path: Path | None = None) -> Path:
    """Write runtime config to YAML file atomically.

    Args:
        config_data: Dict of config values to write.
        path: Override path (for testing).

    Returns:
        Path to the written file.
    """
    config_path = path or get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    from ruamel.yaml import YAML

    ruamel = YAML()
    ruamel.preserve_quotes = True
    ruamel.default_flow_style = False

    # Atomic write: unique temp file + os.replace (matches proxy config pattern)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(config_path.parent),
        prefix=f".{config_path.stem}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            ruamel.dump(config_data, f)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, str(config_path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    reset_runtime_config()

    return config_path


def get_default_config_content() -> str:
    """Generate default config.yaml content with comments."""
    return """\
# Forge Runtime Configuration
# This file is optional — Forge works with built-in defaults.
# Edit with: forge config edit
# Set values: forge config set <key>=<value>

# Proxy execution mode:
#   host    — proxy runs on host (default, no Docker required)
#   sidecar — proxy bundled with Claude in Docker container
proxy_mode: host

# Docker image for sidecar mode
# sidecar_image: forge-sidecar:latest

# Version string for User-Agent header to upstream LLM providers
# user_agent_claude_code_version: "2.1.76"

# Optional model override for direct (non-proxy) sessions.
# Forge pins this through Claude Code's ANTHROPIC_DEFAULT_*_MODEL env vars.
# Set to "" to let Claude Code pick. Aliases like "opus" or "sonnet" also work.
# default_direct_model: claude-opus-4-6

# Fallback auto-compact window for proxy mode when model lookup fails.
# Passed as CLAUDE_CODE_AUTO_COMPACT_WINDOW to Claude Code.
# Direct sessions don't use this — Claude Code handles its own context.
# context_limit: 200000

# Status line timeout for proxy/git calls (seconds)
# status_timeout: 2.0

# Memory writer timeout (seconds)
# memory_writer_timeout: 300

# File logging level: off (no file logging), debug, info, warning
# Logs written to $FORGE_HOME/logs/
# Override: FORGE_DEBUG env var (1/true/yes for debug, 0/false/no/off to disable)
# log_level: "off"

# Auto-delete log files older than N days on CLI startup.
# 0 = disabled (no auto-cleanup). Example: 30 = keep last 30 days.
# Manual cleanup: forge logs --clean [--older-than DAYS]
# log_retention_days: 0

# Auto-delete sessions older than N days on CLI startup.
# 0 = disabled (no auto-cleanup). Example: 90 = keep last 90 days.
# Keeps worktrees and branches; removes manifests, index entries, and
# Claude transcripts (*.jsonl in ~/.claude/projects/).
# Forge artifact snapshots (.forge/artifacts/) are NOT removed.
# Manual cleanup: forge session clean --older-than DAYS
# session_retention_days: 0

# Policy summary feedback: show post-evaluation summary lines and additionalContext.
# "on" (default) prints what was checked and the verdict after each policy evaluation.
# "off" silences summary lines. Deny messages and substantive warnings stay visible always.
# policy_summary_feedback: "on"

# Upstream outcome telemetry volume: non_success (failure/exception log) or all.
# upstream_event_volume: "non_success"

# Tool failure telemetry for proxied sessions.
# Records failed tool call inputs and errors to help refine model-family prompt addendums.
# Off by default because payloads may include file paths, command text, or content snippets.
# log_tool_failures: false

# Ignore environment variables for credential resolution.
# When true, Forge reads credentials only from ~/.forge/credentials.yaml.
# Useful when your shell ANTHROPIC_API_KEY is for Claude Code (OAuth/Max),
# but you want Forge subprocesses to use a separate key from the credential file.
# auth_ignore_env: false

# ANTHROPIC_API_KEY policy for interactive `forge session`/`forge claude` launches.
# inherit (default) — the session uses the same key as everything else.
# omit              — keep the key out of the interactive session only, so a
#                     subscription/OAuth session isn't billed against a key meant
#                     for other tools. Headless subprocesses keep their key.
# interactive_anthropic_api_key: inherit

# Status line display (nested section). Choose which segments show, the cost
# model, palette, and glyphs. Set values with: forge config set statusline.<key>=<value>
#   cost_mode: auto | api | subscription
#              auto         shows the 5h quota when present, else hedges the cost
#                           with a leading ~= (never inferred from an API key)
#              api          shows real dollars (you bill per-token)
#              subscription shows quota instead of dollars
#   palette:   default | earthy
#   glyphs:    ascii | unicode
#   segments:  ordered list; empty = default layout. Valid names: path, branch,
#              breadcrumb, model, cost, rate_limits, lines, tokens, think, loop,
#              sidecar, cache_hit, supervisor, policy, audit, drift, spend_cap,
#              forge_cost
#   cache_hit: auto | off    cache_hit_ttl: <seconds, direct-mode throttle window>
#   forge_cost_ttl: <seconds, forge_cost segment throttle window (default 10)>
# statusline:
#   cost_mode: auto
#   palette: default
#   segments: []

# Provider-trace observability (nested section).
#   inject_provider_user: record the hashed Forge session id in OpenRouter's
#   top-level `user` field so a session/fork is grouped in OpenRouter's
#   account-side /generation records. One global switch governs BOTH proxied
#   OpenRouter traffic AND Forge's direct core.llm callers (plan-check, transfer
#   curation). Only a hashed id is sent (forge_sess_<hash>), never the raw name.
#   Off by default. Set with: forge config set provider_trace.inject_provider_user=true
# provider_trace:
#   inject_provider_user: false
"""
