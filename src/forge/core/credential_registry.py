"""Dependency-light credential registry data.

This module owns Forge credential definitions and has no dependency on template
or source resolution. Template-aware auth logic belongs in capabilities.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVar:
    """Metadata for one environment variable within a credential."""

    name: str
    required: bool = True
    secret: bool = True
    connection_value: bool = False
    default_value: str | None = None


@dataclass(frozen=True)
class Credential:
    """A Forge credential with its env vars and capability metadata."""

    name: str
    env_vars: tuple[EnvVar, ...] = ()
    unlocks_features: tuple[str, ...] = ()
    signup_url: str | None = None
    note: str | None = None
    not_needed_for: tuple[str, ...] | None = None


CREDENTIALS: dict[str, Credential] = {
    "openrouter": Credential(
        name="openrouter",
        env_vars=(
            EnvVar("OPENROUTER_API_KEY"),
            EnvVar(
                "OPENROUTER_BASE_URL",
                required=False,
                secret=False,
                connection_value=True,
                default_value="https://openrouter.ai/api/v1",
            ),
        ),
        unlocks_features=("OpenRouter proxy templates", "OSS workflow model workers"),
        signup_url="https://openrouter.ai/keys",
        note="Routes to Claude, GPT, Gemini, DeepSeek, etc. via OpenRouter",
    ),
    "anthropic-api": Credential(
        name="anthropic-api",
        env_vars=(EnvVar("ANTHROPIC_API_KEY"),),
        unlocks_features=(
            "Forge subprocesses (supervisor, memory writer)",
            "direct Anthropic panel/debate workers",
            "litellm-anthropic-local proxy",
            "anthropic-passthrough proxy template",
        ),
        signup_url="https://console.anthropic.com/",
        note="Pay-per-token API key. Not Claude Code login.",
        not_needed_for=(
            "forge session start (uses Claude Code's own auth)",
            "Claude via openrouter-anthropic (uses OPENROUTER_API_KEY)",
            "Claude via litellm-anthropic (uses LITELLM_API_KEY)",
        ),
    ),
    "openai-api": Credential(
        name="openai-api",
        env_vars=(EnvVar("OPENAI_API_KEY"),),
        unlocks_features=("litellm-openai-local proxy",),
        signup_url="https://platform.openai.com/api-keys",
        note="OpenAI API key for local LiteLLM proxy routing",
    ),
    "gemini-api": Credential(
        name="gemini-api",
        env_vars=(EnvVar("GEMINI_API_KEY"),),
        unlocks_features=("litellm-gemini-local proxy",),
        signup_url="https://aistudio.google.com/apikey",
        note="Gemini API key for local LiteLLM proxy routing",
    ),
    "codex-api": Credential(
        name="codex-api",
        env_vars=(EnvVar("CODEX_API_KEY"),),
        unlocks_features=("Native Codex headless runs (codex exec)",),
        signup_url="https://platform.openai.com/api-keys",
        note=(
            "Non-interactive Codex override. Codex keeps its OWN credential store; run "
            "'codex doctor' to see resolved auth. Not your ChatGPT login (codex login "
            "--device-auth) and not OPENAI_API_KEY."
        ),
        not_needed_for=(
            "Codex already logged in via 'codex login'",
            "Codex via ChatGPT subscription (codex login --device-auth)",
        ),
    ),
    "litellm-remote": Credential(
        name="litellm-remote",
        env_vars=(
            EnvVar("LITELLM_API_KEY"),
            EnvVar("LITELLM_BASE_URL", secret=False, connection_value=True),
        ),
        unlocks_features=("Remote LiteLLM proxy templates",),
        note="Shared/internal LiteLLM server (team setups)",
    ),
}

RETIRED_NAMES: dict[str, str] = {
    "anthropic": (
        "Unknown credential 'anthropic'. Did you mean 'anthropic-api'?\n"
        "\n"
        "  'anthropic-api' is for Forge subprocess auth (pay-per-token API key).\n"
        "  It is NOT your Claude Code login.\n"
        "\n"
        "  Run: forge auth login -c anthropic-api"
    ),
    "litellm-local": (
        "'litellm-local' is not a credential. It's a setup that uses upstream API keys.\n"
        "\n"
        "  Configure the providers you need:\n"
        "    forge auth login -c gemini-api       # for litellm-gemini-local\n"
        "    forge auth login -c openai-api       # for litellm-openai-local\n"
        "    forge auth login -c anthropic-api    # for litellm-anthropic-local"
    ),
}


def credential_for_env_var(var_name: str) -> Credential | None:
    """Find the credential that owns a given env var name."""

    for cred in CREDENTIALS.values():
        if any(ev.name == var_name for ev in cred.env_vars):
            return cred
    return None


__all__ = [
    "CREDENTIALS",
    "RETIRED_NAMES",
    "Credential",
    "EnvVar",
    "credential_for_env_var",
]
