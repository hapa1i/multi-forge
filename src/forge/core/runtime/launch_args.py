"""Launch-only runtime arguments for managed session launches.

``forge session start|resume|fork|incognito`` accept ``--effort`` and a ``--`` tail
of runtime flags. Both apply to one launch and are never persisted in session
intent. This module owns the per-runtime effort vocabulary check, the denylist of
runtime flags Forge already manages, the advisory-authority refusal, and the argv
each runtime receives.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

from forge.core.effort import CLAUDE_EFFORT_LEVELS, CODEX_EFFORT_LEVELS

LaunchRuntime = Literal["claude_code", "codex"]

_RUNTIME_LABELS: dict[str, str] = {"claude_code": "Claude", "codex": "Codex"}
_EFFORT_LEVELS: dict[str, tuple[str, ...]] = {
    "claude_code": CLAUDE_EFFORT_LEVELS,
    "codex": CODEX_EFFORT_LEVELS,
}

# Every level accepted by at least one runtime; the CLI offers this set and the
# runtime-specific check runs once the session runtime is known.
ALL_EFFORT_LEVELS: tuple[str, ...] = tuple(dict.fromkeys((*CODEX_EFFORT_LEVELS, *CLAUDE_EFFORT_LEVELS)))


class LaunchArgsError(ValueError):
    """A launch-argument combination refused before any session mutation."""


@dataclass(frozen=True)
class _ReservedFlag:
    spellings: tuple[str, ...]
    reason: str


_CLAUDE_RESERVED: tuple[_ReservedFlag, ...] = (
    _ReservedFlag(("--session-id",), "Forge assigns the Claude conversation id"),
    _ReservedFlag(("-r", "--resume", "-c", "--continue", "--from-pr"), "Forge selects the conversation to resume"),
    _ReservedFlag(("--fork-session",), "use 'forge session fork' or 'forge session resume --fresh'"),
    _ReservedFlag(("-w", "--worktree"), "use Forge '--worktree' so the session worktree stays recorded"),
    _ReservedFlag(("-n", "--name"), "Forge names the Claude session after the Forge session"),
    _ReservedFlag(("--model",), "use Forge '--model' so the session route stays recorded"),
    _ReservedFlag(("--effort",), "use Forge '--effort'"),
    _ReservedFlag(
        ("--append-system-prompt-file",),
        "Forge delivers transfer context through it; use '--system-prompt-file' on 'forge session start'",
    ),
    _ReservedFlag(("-p", "--print"), "managed sessions are interactive"),
    _ReservedFlag(("--bare",), "it skips the hooks that record Forge session state"),
)

_CODEX_RESERVED: tuple[_ReservedFlag, ...] = (
    _ReservedFlag(("-s", "--sandbox"), "use '--sandbox' on 'forge session start --runtime codex'"),
    _ReservedFlag(("-C", "--cd"), "Forge runs Codex in the session worktree"),
    _ReservedFlag(("--worktree",), "use Forge '--worktree' so the session worktree stays recorded"),
    _ReservedFlag(("-p", "--profile"), "a profile can change the provider and auth Forge preflighted"),
    _ReservedFlag(
        ("--oss", "--local-provider", "--remote", "--remote-auth-token-env"),
        "managed Codex sessions use the native provider and auth Forge preflighted",
    ),
    _ReservedFlag(("--ephemeral",), "Forge needs the persisted Codex thread for resume and artifact reconciliation"),
    _ReservedFlag(("--json",), "Forge parses the headless Codex event stream"),
    _ReservedFlag(
        ("--dangerously-bypass-hook-trust",),
        "it changes the hook trust boundary Forge enforcement relies on",
    ),
    _ReservedFlag(
        ("--dangerously-bypass-approvals-and-sandbox", "--yolo"),
        "it overrides the Forge-managed sandbox",
    ),
)

# Codex `-c key=value` overrides that collide with a Forge-owned launch fact.
_CODEX_RESERVED_CONFIG_KEYS: dict[str, str] = {
    "model_reasoning_effort": "use Forge '--effort'",
    "model_provider": "a provider override changes the auth Forge preflighted",
    "model_providers": "a provider override changes the auth Forge preflighted",
}


@dataclass(frozen=True)
class RuntimeLaunchArgs:
    """User-requested runtime options for one managed launch."""

    effort: str | None = None
    passthrough: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return self.effort is None and not self.passthrough

    def runtime_argv(self, runtime: LaunchRuntime) -> list[str]:
        """Return the arguments appended to the runtime command for this launch."""
        argv: list[str] = []
        if self.effort is not None:
            if runtime == "claude_code":
                argv.extend(("--effort", self.effort))
            else:
                argv.extend(("-c", f'model_reasoning_effort="{self.effort}"'))
        argv.extend(self.passthrough)
        return argv

    def recovery_argv(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Return ``(options, passthrough)`` for reproducing this launch in a command."""
        options = ("--effort", self.effort) if self.effort is not None else ()
        return options, self.passthrough


def validate_launch_args(
    args: RuntimeLaunchArgs,
    *,
    runtime: LaunchRuntime,
    advisory: bool,
) -> RuntimeLaunchArgs:
    """Validate launch arguments for ``runtime``; raise :class:`LaunchArgsError` on refusal.

    ``advisory`` is whether the launched session will carry advisory artifact
    authority. Runtime flags such as ``claude --bare`` or Codex hook-trust bypasses
    can disable the hooks that enforce it, so advisory launches accept effort only.
    """
    label = _RUNTIME_LABELS[runtime]
    if args.effort is not None and args.effort not in _EFFORT_LEVELS[runtime]:
        raise LaunchArgsError(
            f"--effort for {label} sessions must be one of {', '.join(_EFFORT_LEVELS[runtime])}; got {args.effort!r}"
        )
    if not args.passthrough:
        return args
    if advisory:
        raise LaunchArgsError(
            "runtime arguments after '--' are not accepted for advisory-authority launches because runtime "
            "flags can disable the hooks that enforce authority; remove them (--effort remains available)"
        )
    reserved = _CLAUDE_RESERVED if runtime == "claude_code" else _CODEX_RESERVED
    for token in args.passthrough:
        for flag in reserved:
            if _matches(token, flag.spellings):
                raise LaunchArgsError(f"{label} flag {token.split('=', 1)[0]!r} is managed by Forge: {flag.reason}")
    if runtime == "codex":
        for key in _codex_config_keys(args.passthrough):
            root = key.split(".", 1)[0]
            if root in _CODEX_RESERVED_CONFIG_KEYS:
                raise LaunchArgsError(
                    f"Codex config override {key!r} is managed by Forge: {_CODEX_RESERVED_CONFIG_KEYS[root]}"
                )
    return args


def _matches(token: str, spellings: Sequence[str]) -> bool:
    for spelling in spellings:
        if spelling.startswith("--"):
            if token == spelling or token.startswith(f"{spelling}="):
                return True
        # A short flag may carry its value or further short flags attached ("-rID").
        elif not token.startswith("--") and token.startswith(spelling):
            return True
    return False


def _codex_config_keys(tokens: Sequence[str]) -> Iterator[str]:
    """Yield the key of every ``-c``/``--config`` override in ``tokens``."""
    pending = False
    for token in tokens:
        if pending:
            pending = False
            yield token.split("=", 1)[0].strip()
            continue
        if token in ("-c", "--config"):
            pending = True
        elif token.startswith("--config="):
            yield token.removeprefix("--config=").split("=", 1)[0].strip()
        elif token.startswith("-c") and not token.startswith("--"):
            yield token[2:].lstrip("=").split("=", 1)[0].strip()
