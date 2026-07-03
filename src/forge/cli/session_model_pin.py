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
from forge.core.state import FileLockTimeoutError
from forge.session import SessionState, SessionStore
from forge.session.exceptions import (
    InvalidSessionNameError,
    ManifestCorruptedError,
    ManifestValidationError,
    SessionFileNotFoundError,
)

logger = logging.getLogger(__name__)


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
        print_error(f"--model cannot be combined with sidecar {surface}")
        sys.exit(1)

    _apply_direct_model_override_to_state(state, direct_model)
    _persist_direct_model_override(
        forge_root=forge_root,
        session_name=state.name,
        direct_model=direct_model,
    )
