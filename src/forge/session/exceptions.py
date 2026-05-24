"""Exceptions for Forge Session module."""

from __future__ import annotations


class ForgeSessionError(Exception):
    """Base exception for session module."""


class InvalidSessionNameError(ForgeSessionError):
    """Raised when session name validation fails."""


class SessionNotFoundError(ForgeSessionError):
    """Raised when a session cannot be found."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"session '{name}' not found")


class SessionExistsError(ForgeSessionError):
    """Raised when trying to create a session that already exists."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"session '{name}' already exists")


class SessionFileNotFoundError(ForgeSessionError):
    """Raised when session state file doesn't exist in expected location."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"session file not found at '{path}'")


class PassportError(ForgeSessionError):
    """Raised for invalid memory-doc passport frontmatter."""

    def __init__(self, field_path: str, reason: str, *, hint: str | None = None) -> None:
        self.field_path = field_path
        self.reason = reason
        self.hint = hint
        msg = f"{field_path}: {reason}"
        if hint:
            msg += f"\n  {hint}"
        super().__init__(msg)


class ManifestCorruptedError(ForgeSessionError):
    """Raised when manifest file exists but cannot be parsed."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"manifest at '{path}': {reason}")


class ManifestValidationError(ForgeSessionError):
    """Raised when manifest is missing required fields."""

    def __init__(self, path: str, missing_fields: list[str]) -> None:
        self.path = path
        self.missing_fields = missing_fields
        fields_str = ", ".join(missing_fields)
        super().__init__(f"manifest at '{path}' missing required fields: {fields_str}")


class IndexCorruptedError(ForgeSessionError):
    """Raised when index file exists but cannot be parsed."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"index at '{path}': {reason}")


class CannotForkIncognitoError(ForgeSessionError):
    """Raised when attempting to fork from an incognito session."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"cannot fork from incognito session '{name}'")


class ClaudeInvocationError(ForgeSessionError):
    """Raised when Claude binary invocation fails."""

    def __init__(self, reason: str, exit_code: int | None = None) -> None:
        self.reason = reason
        self.exit_code = exit_code
        msg = reason
        if exit_code is not None:
            msg = f"{reason} (exit code: {exit_code})"
        super().__init__(msg)


class ProjectRootNotFoundError(ForgeSessionError):
    """Raised when no git repository can be found."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"no git repository found at or above '{path}'")


class ForgeNotEnabledError(ForgeSessionError):
    """Raised when session start is attempted without a Forge project.

    Rule 1: sessions require ``forge extension enable`` (which creates ``.forge/``).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"no Forge project at '{path}'. Run 'forge extension enable' first.")


# --- Git Worktree Exceptions ---


class GitNotFoundError(ForgeSessionError):
    """Raised when git binary is not found in PATH."""

    def __init__(self) -> None:
        super().__init__("git binary not found in PATH")


class GitWorktreeError(ForgeSessionError):
    """Raised when a git worktree operation fails."""

    def __init__(self, operation: str, reason: str, exit_code: int | None = None) -> None:
        self.operation = operation
        self.reason = reason
        self.exit_code = exit_code
        msg = f"git worktree {operation} failed: {reason}"
        if exit_code is not None:
            msg = f"{msg} (exit code: {exit_code})"
        super().__init__(msg)


class InvalidBranchNameError(ForgeSessionError):
    """Raised when an explicit --branch name is invalid."""

    def __init__(self, branch: str, reason: str) -> None:
        self.branch = branch
        self.reason = reason
        super().__init__(f"invalid branch name '{branch}': {reason}")


class BranchExistsError(ForgeSessionError):
    """Raised when trying to create a branch that already exists."""

    def __init__(self, branch: str, worktree: str | None = None) -> None:
        self.branch = branch
        self.worktree = worktree
        if worktree:
            msg = f"branch '{branch}' already exists (checked out in '{worktree}')"
        else:
            msg = f"branch '{branch}' already exists"
        super().__init__(msg)


class BranchInUseError(ForgeSessionError):
    """Raised when a branch is checked out in another worktree."""

    def __init__(self, branch: str, worktree: str) -> None:
        self.branch = branch
        self.worktree = worktree
        super().__init__(f"branch '{branch}' is checked out in worktree '{worktree}'")


class BranchNotMergedError(ForgeSessionError):
    """Raised when trying to delete a branch that is not fully merged."""

    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__(f"branch '{branch}' is not fully merged. Use --force to delete anyway")


class WorktreePathExistsError(ForgeSessionError):
    """Raised when the target worktree path already exists."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"worktree path '{path}' already exists")


class DirtyWorktreeError(ForgeSessionError):
    """Raised when a worktree has uncommitted changes during cleanup."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"worktree '{path}' has uncommitted changes. Use --force to remove anyway")


# --- Override Exceptions ---


class InvalidOverrideKeyError(ForgeSessionError):
    """Raised when an override key is invalid.

    Keys can be invalid due to:
    - Empty key or empty segment in path (e.g., "foo..bar")
    - Targeting confirmed.* fields
    - Targeting top-level manifest fields (name, schema_version, etc.)
    - Using intent.* prefix (keys should be relative to intent)
    - Unknown field not in SessionIntent schema
    """

    def __init__(self, key: str, reason: str, hint: str | None = None) -> None:
        self.key = key
        self.reason = reason
        self.hint = hint  # e.g., "valid keys: agent, proxy.*, policy.*, ..."
        msg = f"invalid override key '{key}': {reason}"
        if hint:
            msg = f"{msg} ({hint})"
        super().__init__(msg)


class InvalidOverrideValueError(ForgeSessionError):
    """Raised when an override value has an incompatible type.

    This occurs when the effective config (intent + overrides) cannot be
    converted to a valid SessionIntent due to type mismatches.
    """

    def __init__(self, key: str, expected: str, actual: str) -> None:
        self.key = key
        self.expected = expected  # e.g., "str", "list[str]", "enum"
        self.actual = actual  # e.g., "bool", "True"
        super().__init__(f"invalid value for '{key}': expected {expected}, got {actual}")


# --- Resume Exceptions ---


class AmbiguousSessionError(ForgeSessionError):
    """Raised when a session name matches multiple projects.

    User-facing commands use strict resolution which raises this when
    forge_root is None and duplicate names exist across projects.
    """

    def __init__(self, name: str, forge_roots: list[str]) -> None:
        self.name = name
        self.forge_roots = forge_roots
        roots_str = ", ".join(forge_roots)
        super().__init__(
            f"session '{name}' exists in multiple projects: {roots_str}. "
            f"Run from within the target project directory to disambiguate."
        )


class ContextBudgetExceededError(ForgeSessionError):
    """Raised when parent context exceeds proxy context limit.

    This is a fail-fast check for the 'full' resume strategy. When the parent
    transcript is too large to fit in the target proxy's context window, we
    fail before launching Claude rather than wasting tokens.
    """

    def __init__(self, token_estimate: int, context_limit: int) -> None:
        self.token_estimate = token_estimate
        self.context_limit = context_limit
        super().__init__(
            f"Parent transcript ({token_estimate:,} tokens) exceeds context limit "
            f"({context_limit:,}). Use --strategy structured or --strategy minimal."
        )
