"""Claude binary invocation utilities.

This module provides utilities for invoking the Claude Code CLI binary
with proper argument handling and environment setup.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def invoke_claude(
    *,
    session_id: str | None = None,
    resume_id: str | None = None,
    fork_session: bool = False,
    name: str | None = None,
    model: str | None = None,
    system_prompt_file: str | None = None,
    env_vars: dict[str, str] | None = None,
    unset_env_vars: list[str] | None = None,
    cwd: str | None = None,
    extra_args: list[str] | None = None,
) -> int:
    """Invoke the Claude Code CLI binary.

    Builds the command line arguments, sets up environment variables,
    and runs Claude as a subprocess.

    Args:
        session_id: UUID for new session (--session-id flag).
        resume_id: UUID to resume (--resume flag).
        fork_session: Whether to fork (--fork-session flag).
        name: Display name for Claude's session (--name flag).
        model: Model tier to use (--model flag).
        system_prompt_file: Path to system prompt file (--append-system-prompt-file flag).
        env_vars: Additional environment variables to set.
        unset_env_vars: Environment variables to remove from the child process.
        cwd: Working directory for Claude process.
        extra_args: Additional CLI arguments to pass through to Claude.

    Returns:
        Claude's exit code.

    Raises:
        FileNotFoundError: If claude binary is not found.

    Example:
        >>> # Start new session
        >>> exit_code = invoke_claude(
        ...     session_id="abc-123",
        ...     model="opus",
        ...     env_vars={"FORGE_SESSION": "my-session"},
        ... )

        >>> # Resume session
        >>> exit_code = invoke_claude(
        ...     resume_id="abc-123",
        ...     env_vars={"FORGE_SESSION": "my-session"},
        ... )

        >>> # Fork session
        >>> exit_code = invoke_claude(
        ...     resume_id="parent-uuid",
        ...     fork_session=True,
        ...     env_vars={
        ...         "FORGE_SESSION": "fork-name",
        ...         "FORGE_FORK_NAME": "fork-name",
        ...         "FORGE_PARENT_SESSION": "parent-session",
        ...     },
        ... )
    """
    cmd = _build_command(
        session_id=session_id,
        resume_id=resume_id,
        fork_session=fork_session,
        name=name,
        model=model,
        system_prompt_file=system_prompt_file,
        extra_args=extra_args,
    )

    env = _build_environment(env_vars, unset_env_vars)

    return _run_claude(cmd, env=env, cwd=cwd)


def build_claude_args(
    *,
    session_id: str | None = None,
    resume_id: str | None = None,
    fork_session: bool = False,
    name: str | None = None,
    model: str | None = None,
    system_prompt_file: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build Claude CLI arguments without the executable prefix."""
    args: list[str] = []

    if session_id:
        args.extend(["--session-id", session_id])
    elif resume_id:
        args.extend(["--resume", resume_id])
        if fork_session:
            args.append("--fork-session")

    # --name works with both --session-id and --resume
    if name:
        args.extend(["--name", name])

    if model:
        args.extend(["--model", model])

    if system_prompt_file:
        args.extend(["--append-system-prompt-file", system_prompt_file])

    if extra_args:  # e.g. -- --debug
        args.extend(extra_args)
    return args


def _build_command(
    *,
    session_id: str | None = None,
    resume_id: str | None = None,
    fork_session: bool = False,
    name: str | None = None,
    model: str | None = None,
    system_prompt_file: str | None = None,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Build the command line arguments for Claude.

    Args:
        session_id: UUID for new session.
        resume_id: UUID to resume.
        fork_session: Whether to fork.
        model: Model tier.
        system_prompt_file: Path to system prompt file.
        extra_args: Additional CLI arguments appended after all other flags.

    Returns:
        List of command line arguments.
    """
    # No --bare: interactive sessions need hooks, LSP, and plugin sync
    return [
        "claude",
        *build_claude_args(
            session_id=session_id,
            resume_id=resume_id,
            fork_session=fork_session,
            name=name,
            model=model,
            system_prompt_file=system_prompt_file,
            extra_args=extra_args,
        ),
    ]


def _build_environment(
    extra_vars: dict[str, str] | None = None,
    unset_vars: list[str] | None = None,
) -> dict[str, str]:
    """Build the environment for Claude process.

    Delegates to the shared ``build_claude_env`` utility.

    Args:
        extra_vars: Additional environment variables to set.
        unset_vars: Environment variables to remove from the child process.

    Returns:
        Complete environment dictionary.
    """
    from forge.core.reactive.env import build_claude_env

    env = build_claude_env(extra_vars=extra_vars)
    for key in unset_vars or ():
        env.pop(key, None)
    return env


def _run_claude(
    cmd: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> int:
    """Run the Claude binary as a subprocess.

    Args:
        cmd: Command line arguments.
        env: Environment variables.
        cwd: Working directory.

    Returns:
        Claude's exit code.

    Raises:
        FileNotFoundError: If claude binary is not found.
    """
    if cwd:
        cwd = str(Path(cwd).resolve())

    result = subprocess.run(
        cmd,
        env=env,
        cwd=cwd,
        # Let Claude take over the terminal
        stdin=None,
        stdout=None,
        stderr=None,
    )

    return result.returncode


def find_claude_binary() -> str | None:
    """Find the claude binary in PATH.

    Returns:
        Path to claude binary, or None if not found.
    """
    import shutil

    return shutil.which("claude")


def is_claude_available() -> bool:
    """Check if claude binary is available.

    Returns:
        True if claude is in PATH, False otherwise.
    """
    return find_claude_binary() is not None
