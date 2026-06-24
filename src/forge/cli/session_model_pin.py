"""Direct Claude model pin (--model) helpers for session commands.

Split from session_lifecycle.py for file-size compliance. Validation,
env application, and manifest persistence for the `--model` pin shared by
start/resume/fork/incognito.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from forge.cli.output import console, print_error, print_tip
from forge.config.schema import ProxyInstanceConfig
from forge.core.state import FileLockTimeoutError
from forge.session import SessionState, SessionStore
from forge.session.direct_model import (
    DirectModelPin,
    apply_direct_model_env,
    resolve_direct_model_pin,
)
from forge.session.exceptions import (
    InvalidSessionNameError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionFileNotFoundError,
)

logger = logging.getLogger(__name__)


def _proxy_supports_model_pin(proxy_cfg: ProxyInstanceConfig, pin: DirectModelPin) -> bool:
    """Whether a proxy can honor a Claude model pin via tier default or alternatives."""
    alt_models = proxy_cfg.model_alternatives.get(pin.tier, {})
    if pin.canonical_model in alt_models:
        return True

    tier_model = proxy_cfg.tiers.get(pin.tier)
    if not tier_model:
        return False

    from forge.core.models.catalog import ModelCatalogError, resolve_model_id

    try:
        default_model = resolve_model_id(str(tier_model)).removesuffix("-1m")
    except ModelCatalogError:
        return False
    return default_model == pin.canonical_model


def _apply_direct_model_env_if_supported(
    env_vars: dict[str, str],
    proxy_id: str,
    direct_model: str,
) -> str | None:
    """Apply --model env vars when the proxy can honor the pin.

    No-op (returns None) when the proxy is missing or cannot honor the pin.
    Returns an error message only when env application itself fails.
    """
    from forge.config.loader import load_proxy_instance_config

    proxy_cfg = load_proxy_instance_config(proxy_id)
    if proxy_cfg is None:
        return None
    if not _proxy_supports_model_pin(proxy_cfg, resolve_direct_model_pin(direct_model)):
        return None
    return apply_direct_model_env(env_vars, direct_model)


def _validate_proxy_model_pin(proxy_id: str, pin: DirectModelPin) -> str | None:
    """Return a user-facing error if a proxy cannot honor a Claude model pin."""
    from forge.config.loader import load_proxy_instance_config

    try:
        proxy_cfg = load_proxy_instance_config(proxy_id)
    except (FileNotFoundError, TypeError, ValueError) as e:
        return f"Could not load proxy config for '{proxy_id}': {e}"

    if proxy_cfg is None:
        return f"Could not load proxy config for '{proxy_id}'"

    if _proxy_supports_model_pin(proxy_cfg, pin):
        return None

    alt_models = proxy_cfg.model_alternatives.get(pin.tier, {})
    available = ", ".join(sorted(alt_models.keys())) if alt_models else "(none configured)"
    return (
        f"Proxy '{proxy_id}' does not configure model alternative or tier default "
        f"for '{pin.canonical_model}' in tier '{pin.tier}'. Available alternatives: {available}"
    )


def _validate_direct_model_pin_for_routing(
    *,
    pin: DirectModelPin | None,
    proxy_id: str | None,
    base_url: str | None,
    surface: str,
) -> str | None:
    """Validate a --model pin against explicit or inherited routing."""
    if pin is None:
        return None
    if proxy_id:
        return _validate_proxy_model_pin(proxy_id, pin)
    if base_url is not None:
        return (
            f"--model with inherited proxy routing requires an active proxy id for {surface}. "
            "Pass --proxy <proxy_id> to select the proxy explicitly."
        )
    return None


def _apply_direct_model_override_to_state(state: SessionState, direct_model: str | None) -> None:
    """Apply a normalized --model override to an in-memory session state."""
    if direct_model is None:
        return
    if state.intent.launch is None:
        from forge.session.models import LaunchIntent

        state.intent.launch = LaunchIntent()
    state.intent.launch.direct_model = direct_model


def _persist_direct_model_override(
    *,
    forge_root: Path,
    session_name: str,
    direct_model: str | None,
) -> None:
    """Persist a --model override into the session manifest."""
    if direct_model is None:
        return

    store = SessionStore(str(forge_root), session_name)

    def _mutate(m: SessionState) -> None:
        _apply_direct_model_override_to_state(m, direct_model)

    try:
        store.update(timeout_s=5.0, mutate=_mutate)
    except FileLockTimeoutError as e:
        logger.warning("Failed to persist direct model override to manifest", exc_info=True)
        console.print(
            f"[yellow]Warning:[/yellow] Could not persist --model override for session "
            f"[green]{session_name}[/green]: {e}"
        )
        print_tip(
            "If this command launches Claude, it will use the requested model for this run, "
            "but future resumes may use the previous stored model. Retry after current Forge state updates finish.",
            blank_before=False,
            console=console,
        )
    except (
        InvalidSessionNameError,
        ManifestCorruptedError,
        ManifestValidationError,
        OSError,
        SessionFileNotFoundError,
        ValueError,
    ) as e:
        logger.warning("Failed to persist direct model override to manifest", exc_info=True)
        console.print(
            f"[yellow]Warning:[/yellow] Could not persist --model override for session "
            f"[green]{session_name}[/green]: {e}"
        )
        print_tip(
            "If this command launches Claude, it will use the requested model for this run, "
            "but future resumes may use the previous stored model. Check the session manifest before relying on this pin.",
            blank_before=False,
            console=console,
        )


def _apply_and_persist_direct_model_override(
    *,
    state: SessionState,
    direct_model: str | None,
    forge_root: Path,
    use_sidecar: bool,
    surface: str,
) -> None:
    """Apply a --model override to a launch state and persist it when requested."""
    if direct_model is None:
        return
    if use_sidecar:
        print_error(f"--model cannot be combined with sidecar {surface}", console=console)
        sys.exit(1)

    _apply_direct_model_override_to_state(state, direct_model)
    _persist_direct_model_override(
        forge_root=forge_root,
        session_name=state.name,
        direct_model=direct_model,
    )
