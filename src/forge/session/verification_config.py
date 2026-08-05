"""Authoring validation for Stop verification configuration.

Persisted manifests deliberately retain string fields so legacy unknown values
remain readable and can fail open visibly at the hook boundary. New values are
validated only at supported authoring seams.
"""

from __future__ import annotations

from forge.session.exceptions import InvalidOverrideValueError
from forge.session.models import VerificationConfig

VERIFICATION_TYPES = ("completion_promise", "test_suite")
VERIFICATION_INCOMPLETE_MODES = ("block", "warn", "allow")


def validate_verification_type_for_authoring(config: VerificationConfig | None) -> None:
    """Reject a newly authored verification type outside the shipped schema."""
    if config is not None and config.type not in VERIFICATION_TYPES:
        raise InvalidOverrideValueError(
            "verification.type",
            f"one of {', '.join(VERIFICATION_TYPES)}",
            repr(config.type),
        )


def validate_verification_mode_for_authoring(config: VerificationConfig | None) -> None:
    """Reject a newly authored incomplete mode outside the shipped schema."""
    if config is not None and config.on_incomplete not in VERIFICATION_INCOMPLETE_MODES:
        raise InvalidOverrideValueError(
            "verification.on_incomplete",
            f"one of {', '.join(VERIFICATION_INCOMPLETE_MODES)}",
            repr(config.on_incomplete),
        )
