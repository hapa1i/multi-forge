"""Template-to-credential mapping and credential resolution.

Maps proxy templates to required environment variable names and provides
``resolve_env_or_credential()`` — the single lookup that checks os.environ
first, then falls back to ``~/.forge/credentials.yaml``.

Extracted from ``forge.sidecar.secrets`` so proxy orchestration, review
engine, and sidecar can all share the same resolution logic.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

from forge.backend.sources import (
    BackendInstanceResolutionError,
    resolve_backend_instance,
    template_env_vars_by_template,
)

logger = logging.getLogger(__name__)
TEMPLATE_ENV_VARS: dict[str, list[str]] = template_env_vars_by_template()


def _declared_backend_env_vars(template: str) -> list[str] | None:
    """Return env vars for a template's declared backend, if it can be read.

    ``TEMPLATE_ENV_VARS`` is built from shipped catalog aliases. User templates
    can have arbitrary names, so their credential requirements must come from
    ``proxy.backend`` instead of the filename.
    """

    try:
        from forge.config.loader import read_template

        raw = read_template(template)
    except FileNotFoundError:
        # Not a known template name (e.g. a shipped alias served by the catalog
        # map). Expected control flow; the caller falls back to TEMPLATE_ENV_VARS.
        return None
    except Exception as e:
        # The file exists but could not be read (permissions, IO, encoding) or the
        # loader import failed. For a custom template this would otherwise silently
        # skip credential preflight, so warn rather than degrade quietly. Still
        # returns None so callers never fail on a best-effort lookup.
        logger.warning("Could not read template %s for backend credential lookup: %s", template, e)
        return None

    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.warning("Template %s is not valid YAML; skipping backend credential lookup: %s", template, e)
        return None

    if not isinstance(data, dict):
        return None
    proxy = data.get("proxy")
    if not isinstance(proxy, dict):
        return None
    raw_backend = proxy.get("backend")
    if not isinstance(raw_backend, str) or not raw_backend.strip():
        return None

    try:
        return list(resolve_backend_instance(raw_backend.strip()).source.required_env_vars)
    except BackendInstanceResolutionError as e:
        logger.debug("Template %s references unknown backend %r: %s", template, raw_backend, e)
        return None


def required_env_vars_for_template(template: str) -> list[str]:
    """Return env vars required by a template or its declared model source."""

    declared = _declared_backend_env_vars(template)
    if declared is not None:
        return declared
    return list(TEMPLATE_ENV_VARS.get(template, []))


def _get_file_secrets() -> dict[str, str]:
    """Load all secrets from the credential file for the active profile.

    Returns empty dict on any error so callers never fail due to
    credential file issues.
    """
    try:
        from forge.core.auth.credentials_file import load_profile, resolve_profile

        profile = resolve_profile()
        return load_profile(profile)
    except Exception as e:
        logger.debug("Credential file load failed (non-critical): %s", e)
        return {}


def _auth_ignore_env() -> bool:
    """Check if auth_ignore_env is active without importing runtime config at module load."""
    try:
        from forge.runtime_config import get_runtime_config

        return get_runtime_config().auth_ignore_env
    except Exception as e:
        logger.debug("Could not read auth_ignore_env; using environment credentials: %s", e)
        return False


def resolve_env_or_credential_with_source(var_name: str) -> tuple[str | None, str]:
    """Resolve a value and report which source supplied it.

    Source is ``"env"`` (shell environment), ``"credential_file"`` (the Forge
    credential file), or ``"none"`` (unresolved). When ``auth_ignore_env`` is
    active the shell environment is skipped, so a value present in both places is
    reported as ``credential_file`` -- the source the child actually uses. Callers
    recording provenance (e.g. interactive launch metadata) must use this rather
    than re-deriving the branch, which would drift from the value actually chosen.
    """
    if not _auth_ignore_env():
        value = os.environ.get(var_name)
        if value:
            return value, "env"
    file_value = _get_file_secrets().get(var_name) or None
    if file_value:
        return file_value, "credential_file"
    return None, "none"


def resolve_env_or_credential(var_name: str) -> str | None:
    """Resolve a single value from environment, then credential file.

    When ``auth_ignore_env`` is active, skips os.environ and reads from
    the credential file only. Returns the first truthy (non-empty) value, or None.
    """
    return resolve_env_or_credential_with_source(var_name)[0]


def get_secrets_for_template(template: str) -> dict[str, str]:
    """Get credentials required by a template.

    Resolves each key from environment first, then falls back to the
    credential file. When ``auth_ignore_env`` is active, skips environment.
    Only includes values that resolve to non-empty strings.
    """
    required = required_env_vars_for_template(template)
    if not required:
        return {}

    ignore_env = _auth_ignore_env()
    secrets: dict[str, str] = {}
    file_secrets: dict[str, str] | None = None

    for var_name in required:
        if not ignore_env:
            value = os.environ.get(var_name)
            if value:
                secrets[var_name] = value
                continue

        if file_secrets is None:
            file_secrets = _get_file_secrets()
        value = file_secrets.get(var_name)
        if value:
            logger.debug("Credential %s resolved from credential file", var_name)
            secrets[var_name] = value

    return secrets
