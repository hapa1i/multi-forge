"""Template-aware credential capability helpers.

Credential data lives in ``credential_registry`` so source/template resolution
can depend on it without importing this template-aware module.
"""

from __future__ import annotations

from forge.core.auth.template_secrets import TEMPLATE_ENV_VARS
from forge.core.credential_registry import (
    CREDENTIALS,
    RETIRED_NAMES,
    Credential,
    EnvVar,
    credential_for_env_var,
)

__all__ = [
    "CREDENTIALS",
    "RETIRED_NAMES",
    "Credential",
    "EnvVar",
    "credential_for_env_var",
    "credentials_for_template",
    "format_missing_credential_error",
]


def credentials_for_template(template: str) -> list[Credential]:
    """Which credentials does a template need?

    Bridges TEMPLATE_ENV_VARS (template -> env var names) to CREDENTIALS
    (credential -> env var metadata) via reverse lookup.
    """
    required_vars = TEMPLATE_ENV_VARS.get(template, [])
    if not required_vars:
        return []

    seen: set[str] = set()
    result: list[Credential] = []
    for var_name in required_vars:
        cred = credential_for_env_var(var_name)
        if cred and cred.name not in seen:
            seen.add(cred.name)
            result.append(cred)
    return result


def format_missing_credential_error(
    credential: Credential,
    *,
    missing_vars: list[str],
    template: str | None = None,
    context: str | None = None,
    extra_hint: str | None = None,
    profile: str | None = None,
    env_ignored: bool = False,
) -> str:
    """Build an actionable error message for missing credentials.

    Includes what failed, which key(s), signup URL, and the exact
    ``forge auth login`` command. Renders ``not_needed_for`` when the credential
    defines it (anthropic-api, codex-api -- where false urgency is common).
    """
    key_word = "key" if len(missing_vars) == 1 else "keys"
    var_list = ", ".join(missing_vars)

    if context and template:
        header = f"{context} requires {var_list} (template '{template}')."
    elif context:
        header = f"{context} requires {var_list}."
    elif template:
        header = f"Template '{template}' requires {key_word}: {var_list}."
    else:
        header = f"Missing {key_word}: {var_list}."

    lines = [f"Error: {header}"]

    if credential.note:
        lines.append(f"\n  {credential.note}")

    if credential.not_needed_for:
        lines.append("")
        lines.append("  NOT needed for:")
        for item in credential.not_needed_for:
            lines.append(f"    - {item}")

    unlocks = credential.unlocks_features
    if unlocks:
        lines.append(f"\n  Unlocks: {', '.join(unlocks)}")

    if credential.signup_url:
        lines.append(f"  Get one at {credential.signup_url}")

    login_cmd = f"forge auth login -c {credential.name}"
    if profile:
        login_cmd += f" --profile {profile}"
    lines.append(f"  Tip: Run '{login_cmd}' to configure.")

    if extra_hint:
        lines.append(f"       {extra_hint}")

    if env_ignored:
        present_in_env = [v for v in missing_vars if _env_has(v)]
        if present_in_env:
            env_list = ", ".join(present_in_env)
            verb = "is" if len(present_in_env) == 1 else "are"
            pronoun = "it" if len(present_in_env) == 1 else "them"
            lines.append(
                f"\n  Note: {env_list} {verb} set in env but auth_ignore_env is active."
                f"\n  Run 'forge config set auth_ignore_env=false' to use {pronoun}."
            )

    return "\n".join(lines)


def _env_has(var_name: str) -> bool:
    """Check if an env var is set (for env_ignored diagnostic only)."""
    import os

    return bool(os.environ.get(var_name))
