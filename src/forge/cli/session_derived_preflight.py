"""Early structural admission and recovery for CLI session derivation."""

from __future__ import annotations

import sys

from forge.cli.output import err_console, handle_session_error, print_error, print_tip
from forge.session.derived_overrides import validate_derived_session_overrides
from forge.session.exceptions import (
    ForgeSessionError,
    ManifestCorruptedError,
    ManifestValidationError,
)
from forge.session.models import SessionState


def handle_derived_session_error(error: ForgeSessionError) -> None:
    """Keep strict manifest failures on the explicit repair/restoration path."""
    if isinstance(error, (ManifestCorruptedError, ManifestValidationError)):
        # The legacy version diagnostic embeds deletion advice in its reason.
        reason = error.reason.removesuffix(" Delete this session and recreate it.")
        print_error(f"Cannot derive a session from invalid stored state: manifest at '{error.path}': {reason}")
        print_tip(
            "Repair the named manifest explicitly or restore a known-good copy before retrying.", console=err_console
        )
        sys.exit(1)
    handle_session_error(error)


def preflight_resume(state: SessionState, *, fresh: bool, force_resumable: bool) -> None:
    """Validate only resume paths that will derive a child, before realizing routing."""
    from forge.cli.session import _peek_active_session_entry

    if not fresh and (
        not force_resumable or _peek_active_session_entry(state.name, forge_root=state.forge_root) is None
    ):
        return
    try:
        validate_derived_session_overrides(state)
    except ForgeSessionError as error:
        handle_derived_session_error(error)
