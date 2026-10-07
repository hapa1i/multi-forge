"""The tested, supervisor-only CLI-managed subscription route.

No login material is read or copied. Profile/gateway/managed-policy combinations
are unavailable until separately verified. CLI status and inference share the
same executable, environment, CWD, and settings restrictions.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from time import monotonic

from forge.core.reactive.env import build_claude_env
from forge.core.reactive.watchdog import run_guarded

READ_ONLY_FLAGS = (
    "--restricted",
    "--safe-mode",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--tools",
    "Read,Glob,Grep",
    "--allowedTools",
    "Read,Glob,Grep",
    "--setting-sources",
    "",
)
VERIFIED_CLAUDE_VERSIONS = {"2.1.291"}
_BLOCKED_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "FORGE_SUBPROCESS_", "AWS_", "GOOGLE_", "AZURE_")
_BLOCKED_NAMES = {
    "CLAUDECODE",
    "FORGE_PROXY_WIRE_SHAPE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NODE_OPTIONS",
    "NODE_EXTRA_CA_CERTS",
}


def subscription_environment(extra_vars: dict[str, str] | None = None) -> dict[str, str]:
    """Construct once after dotenv loading, deliberately skipping Forge hydration."""
    env = build_claude_env(direct=True, extra_vars=extra_vars, hydrate_credentials=False)
    return {
        key: value for key, value in env.items() if not key.startswith(_BLOCKED_PREFIXES) and key not in _BLOCKED_NAMES
    }


def _present(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def validate_subscription_location(env: dict[str, str]) -> None:
    """Admit the verified personal-login case without treating HOME as Keychain isolation."""
    if sys.platform not in {"darwin", "linux"}:
        raise ValueError("Subscription-only supervision is unverified on this operating system.")
    if env.get("FORGE_SIDECAR") or env.get("FORGE_LAUNCH_MODE") == "sidecar":
        raise ValueError("Subscription-only supervision requires a host executor.")
    home = Path(env.get("HOME") or str(Path.home()))
    config = home / ".claude"
    if Path(env.get("CLAUDE_CONFIG_DIR") or str(config)).resolve() != config.resolve():
        raise ValueError("Subscription-only review has not verified alternate CLAUDE_CONFIG_DIR/Keychain isolation.")
    profiles = home / ".config/anthropic"
    if _present(profiles / "active_config") or _present(profiles / "configs/default.json"):
        raise ValueError("Subscription-only review is unavailable with active/default Anthropic profiles.")
    system = Path("/Library/Application Support/ClaudeCode" if sys.platform == "darwin" else "/etc/claude-code")
    managed = [system / name for name in ("managed-settings.json", "managed-settings.d", "managed-mcp.json")]
    if sys.platform == "darwin":
        managed.extend(
            [
                Path("/Library/Managed Preferences/com.anthropic.claudecode.plist"),
                Path("/Library/Managed Preferences") / (env.get("USER") or "") / "com.anthropic.claudecode.plist",
                home / "Library/Preferences/com.anthropic.claudecode.plist",
            ]
        )
    if any(_present(path) for path in managed):
        raise ValueError("Subscription-only review is unavailable with managed Claude settings or MCP.")
    remote = config / "remote-settings.json"
    if _present(remote) and json.loads(remote.read_text()) != {}:
        raise ValueError("Subscription-only review is unavailable with server-managed Claude settings.")
    # This non-secret metadata distinguishes personal accounts from unverified
    # organization/gateway configurations which may fetch policy at startup.
    account = json.loads((home / ".claude.json").read_text()).get("oauthAccount", {})
    if account.get("organizationType") not in {"claude_max", "claude_pro"}:
        raise ValueError("Subscription-only review requires a verified personal Claude Pro/Max login.")


def preflight_subscription(*, env: dict[str, str], cwd: str | None, deadline: float) -> str:
    """Return the tested absolute CLI path, or refuse without model inference."""
    validate_subscription_location(env)
    binary = shutil.which("claude", path=env.get("PATH"))
    if not binary:
        raise ValueError("Claude CLI is unavailable; install Claude and sign in before enabling subscription review.")

    def run(argv: list[str]):
        return run_guarded(argv, input="", env=env, cwd=cwd, timeout=min(10.0, deadline - monotonic()))

    version = run([binary, "--version"])
    if version.returncode or version.stdout.split(maxsplit=1)[0] not in VERIFIED_CLAUDE_VERSIONS:
        raise ValueError("Subscription-only review requires a verified Claude version (currently 2.1.291).")
    result = run([binary, *READ_ONLY_FLAGS, "auth", "status", "--json"])
    try:
        status = json.loads(result.stdout)
    except ValueError as exc:
        raise ValueError("Claude subscription auth status is unreadable; no review was dispatched.") from exc
    if (
        result.returncode
        or not isinstance(status, dict)
        or status.get("loggedIn") is not True
        or status.get("authMethod") != "claude.ai"
        or status.get("apiProvider") != "firstParty"
        or status.get("apiKeySource") not in {None, "none"}
        or status.get("subscriptionType") not in {None, "max", "pro"}
    ):
        raise ValueError("Claude CLI-managed subscription login is unavailable; no API fallback was attempted.")
    # Detect settings arriving during preflight before permitting the inference run.
    validate_subscription_location(env)
    return binary
