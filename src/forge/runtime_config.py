"""Forge runtime configuration (~/.forge/config.yaml).

Separate from forge.config (which the proxy imports) to avoid leaking
runtime preferences into routing. The proxy singleton must never see
these values — they control CLI/session behavior only.

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

# Renamed config keys: old name -> new name. Surfaced with migration guidance
# instead of the generic "unknown key" path. The old value is NOT migrated --
# runtime config is a system boundary that degrades to the built-in default
# (coding-standards.md §5).
_RENAMED_KEYS: dict[str, str] = {
    "handoff_timeout": "memory_writer_timeout",
}

# Removed config keys: old name -> actionable guidance naming the replacement
# path. Unlike a rename, there is no 1:1 successor key, so the guidance is a
# human sentence. Surfaced on load (one-time warning) and rejected by
# set/edit/reset with the same guidance (clean break, coding-standards.md §5:
# "known legacy state that is intentionally ignored must still be surfaced with
# an actionable warning").
_REMOVED_KEYS: dict[str, str] = {
    "show_rate_limits": (
        "add 'rate_limits' to statusline.segments "
        "(e.g. 'forge config set statusline.segments=path,model,rate_limits')"
    ),
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

    # Log tool failures to ~/.forge/logs/tool_failures/ even without debug mode.
    # Off by default because records may include tool inputs and error payloads.
    log_tool_failures: bool = False

    # Ignore environment variables for credential resolution.
    # When true, Forge reads credentials only from ~/.forge/credentials.yaml,
    # ignoring shell env vars (ANTHROPIC_API_KEY, OPENROUTER_API_KEY, etc.).
    # Useful when shell API keys are for Claude Code (not Forge subprocesses).
    auth_ignore_env: bool = False

    # Nested status-line display preferences (statusline: section in config.yaml).
    statusline: StatusLineConfig = field(default_factory=StatusLineConfig)

    def __post_init__(self) -> None:
        # Coerce a raw dict (from YAML or `forge config set`/`edit`) into the
        # nested dataclass. This is the single convergence point for the load,
        # set, and edit paths (see _coerce_statusline_config).
        self.statusline = _coerce_statusline_config(self.statusline)

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
    on unknown keys for forward compat (coding-standards.md §5, system boundaries).
    """
    known_fields = {f.name for f in fields(RuntimeConfig)}
    unknown = set(data.keys()) - known_fields

    # Renamed keys get migration guidance, not the generic "unknown" warning.
    # The old value is ignored (degrade to default) -- see _RENAMED_KEYS.
    renamed = unknown & set(_RENAMED_KEYS)
    for old in sorted(renamed):
        logger.warning(
            "%s: '%s' was renamed to '%s' and is ignored. " "Update your config (the old value is not applied).",
            source,
            old,
            _RENAMED_KEYS[old],
        )

    # Removed keys get a specific replacement hint (not the generic warning), so
    # stale recognized config doesn't silently degrade to default.
    removed = unknown & set(_REMOVED_KEYS)
    for old in sorted(removed):
        logger.warning(
            "%s: '%s' was removed and is ignored; %s.",
            source,
            old,
            _REMOVED_KEYS[old],
        )

    truly_unknown = unknown - renamed - removed
    if truly_unknown:
        logger.warning(
            "Unknown keys in %s (ignored): %s",
            source,
            ", ".join(sorted(truly_unknown)),
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

# Tool failure telemetry for proxied sessions.
# Records failed tool call inputs and errors to help refine model-family prompt addendums.
# Off by default because payloads may include file paths, command text, or content snippets.
# log_tool_failures: false

# Ignore environment variables for credential resolution.
# When true, Forge reads credentials only from ~/.forge/credentials.yaml.
# Useful when your shell ANTHROPIC_API_KEY is for Claude Code (OAuth/Max),
# but you want Forge subprocesses to use a separate key from the credential file.
# auth_ignore_env: false

# Status line display (nested section). Choose which segments show, the cost
# model, palette, and glyphs. Set values with: forge config set statusline.<key>=<value>
#   cost_mode: auto | api | subscription   (auto detects from ANTHROPIC_API_KEY;
#              subscription shows quota instead of dollars)
#   palette:   default | earthy
#   glyphs:    ascii | unicode
#   segments:  ordered list; empty = default layout. Valid names: path, branch,
#              breadcrumb, model, cost, rate_limits, lines, tokens, think, loop,
#              sidecar, cache_hit (more segments are added in later versions)
#   cache_hit: auto | off    cache_hit_ttl: <seconds, direct-mode throttle window>
# statusline:
#   cost_mode: auto
#   palette: default
#   segments: []
"""
