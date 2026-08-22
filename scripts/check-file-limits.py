#!/usr/bin/env python3
"""
Check file size limits (lines and tokens) for staged git files.

Loads the repository-owned root policy.
Token counting runs `count-tokens` over the chain in `token_count.methods`.

Usage:
    check-file-limits                          # Check staged files
    check-file-limits file1.py file2.js        # Check specific files
    check-file-limits --dry-run                # Show what would be checked
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

# A repository must opt into provider counting in its tracked policy.
DEFAULT_TOKEN_METHODS = ["local-tiktoken"]


def get_script_dir() -> Path:
    """Get the directory containing this script."""
    return Path(__file__).resolve().parent


def get_git_root() -> Path | None:
    """Return the current repository root without assuming the hook location."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    """Resolve explicit, repository-owned, then personal fallback policy."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    if repo_root := get_git_root():
        candidate = repo_root / ".file-size-limits.json"
        if candidate.is_file():
            return candidate
    return get_script_dir().parent / ".file-size-limits.json"


def load_config(config_path: str | Path | None = None) -> dict:
    """Load the resolved file-size policy."""
    config_path = resolve_config_path(config_path)
    if not config_path.exists():
        print(f"Error: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    config = json.loads(config_path.read_text())
    if "extensions" in config and "rules" not in config:
        print(
            "Error: file-size-limits.json uses old 'extensions' format. Migrate to 'rules'.",
            file=sys.stderr,
        )
        sys.exit(1)
    return config


def get_staged_files() -> list[str]:
    """Get list of staged files from git."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]


def is_whitelisted(file_path: str, config: dict) -> bool:
    """Check if file is in a whitelisted path. Empty whitelist means all paths allowed."""
    whitelisted_paths = config.get("whitelisted_paths", [])
    if not whitelisted_paths:
        return True  # No whitelist = allow all
    for allowed_path in whitelisted_paths:
        if file_path.startswith(allowed_path):
            return True
    return False


def match_pattern(file_path: str, pattern: str) -> bool:
    """Match file path against a glob pattern (gitignore-style: no slash = basename, slash = full path)."""
    if "/" in pattern:
        path_parts = Path(file_path).parts
        pattern_parts = Path(pattern).parts
        if len(path_parts) != len(pattern_parts):
            return False
        return all(fnmatch.fnmatch(p, pat) for p, pat in zip(path_parts, pattern_parts))
    return fnmatch.fnmatch(Path(file_path).name, pattern)


def get_limits(file_path: str, config: dict) -> dict | None:
    """Get limits for a file based on glob rules. First match wins. Returns None if no match."""
    for rule in config.get("rules", []):
        if match_pattern(file_path, rule["pattern"]):
            if rule.get("skip"):
                return None
            return {key: value for key, value in rule.items() if key not in {"pattern", "skip"}}
    return None


def count_lines(file_path: str) -> int:
    """Count lines in a file."""
    try:
        return sum(1 for _ in open(file_path, "r", encoding="utf-8", errors="replace"))
    except (IOError, OSError):
        return 0


def get_token_methods(config: dict, limits: dict | None = None) -> list[str]:
    """Get the ordered token-counting method chain. Falls back to the default chain."""
    methods = (limits or {}).get("token_methods") or config.get("token_count", {}).get("methods")
    if not isinstance(methods, list):
        return list(DEFAULT_TOKEN_METHODS)
    chain = [str(m).strip() for m in methods if str(m).strip()]
    return chain or list(DEFAULT_TOKEN_METHODS)


def count_tokens(file_path: str, methods: list[str]) -> tuple[int, str] | None:
    """Count tokens using count-tokens script."""
    count_tokens_path = get_script_dir() / "count-tokens.py"
    if not count_tokens_path.exists():
        print(f"Warning: count-tokens not found: {count_tokens_path}", file=sys.stderr)
        return None

    # count-tokens walks the chain and always returns a count, so a missing key
    # or a rate limit degrades to the next method instead of failing the commit.
    # The chain leads with a Claude model so limits are enforced against the same
    # token counts Claude Code reports -- see config/file-size-limits.json.
    result = subprocess.run(
        [str(count_tokens_path), "--methods", ",".join(methods), "--json", file_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Warning: count-tokens failed for {file_path}: {result.stderr}", file=sys.stderr)
        return None

    try:
        payload = json.loads(result.stdout)
        return int(payload["tokens"]), str(payload["method"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def format_number(n: int) -> str:
    """Format number with thousands separator."""
    return f"{n:,}"


def check_file(file_path: str, config: dict, check_tokens: bool = True) -> tuple[list[str], list[str]]:
    """Check a file against limits.

    Returns error and target-warning messages.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not is_whitelisted(file_path, config):
        return errors, warnings

    limits = get_limits(file_path, config)
    if limits is None:
        return errors, warnings

    if not Path(file_path).exists():
        return errors, warnings

    max_lines = limits.get("max_lines", 2000)
    max_tokens = limits.get("max_tokens", 25000)

    # Check lines (fast)
    lines = count_lines(file_path)
    if lines > max_lines:
        errors.append(f"{file_path}: {format_number(lines)} lines exceeds limit of {format_number(max_lines)}")
        # Don't bother checking tokens if lines already failed
        return errors, warnings

    # Check tokens (`count-tokens` over the configured method chain)
    if check_tokens:
        methods = get_token_methods(config, limits)
        local_result = count_tokens(file_path, ["local-tiktoken"])
        probe_at = limits.get("provider_probe_local_tokens")
        measured: tuple[int, str] | None
        if local_result is not None and probe_at is not None and local_result[0] < probe_at:
            measured = local_result
        else:
            measured = count_tokens(file_path, methods)
        if measured is not None:
            tokens, method = measured
            target_tokens = limits.get("target_tokens")
            require_authoritative_at = limits.get("authoritative_required_local_tokens")
            is_authoritative = method.startswith("anthropic API")
            if (
                not is_authoritative
                and require_authoritative_at is not None
                and local_result is not None
                and local_result[0] >= require_authoritative_at
            ):
                errors.append(
                    f"{file_path}: authoritative token count required at "
                    f"{format_number(local_result[0])} local tokens (used {method})"
                )
            elif tokens > max_tokens:
                errors.append(
                    f"{file_path}: {format_number(tokens)} tokens exceeds limit of "
                    f"{format_number(max_tokens)} ({method})"
                )
            elif target_tokens is not None and tokens > target_tokens:
                warnings.append(
                    f"{file_path}: {format_number(tokens)} tokens exceeds target of "
                    f"{format_number(target_tokens)} ({method})"
                )

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Check file size limits for staged files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        help="Policy file (default: <git-root>/.file-size-limits.json)",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Files to check (default: staged git files)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be checked without checking",
    )
    parser.add_argument(
        "--skip-tokens",
        action="store_true",
        help="Skip token counting (faster, line check only)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show files being checked",
    )

    args = parser.parse_args()
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)

    # Get files to check
    if args.files:
        files = args.files
    else:
        files = get_staged_files()

    if not files:
        if args.verbose:
            print("No files to check")
        return

    # Filter to whitelisted files with configured limits
    files_to_check = [f for f in files if is_whitelisted(f, config) and get_limits(f, config)]

    if args.dry_run:
        print(f"Config: {config_path}")
        print(f"Token method chain: {' -> '.join(get_token_methods(config))}")
        print(f"Would check {len(files_to_check)} file(s):")
        for f in files_to_check:
            limits = get_limits(f, config)
            print(f"  {f} (max {limits['max_lines']} lines, {limits['max_tokens']} tokens)")
        return

    all_errors = []
    all_warnings = []
    for file_path in files_to_check:
        if args.verbose:
            print(f"Checking: {file_path}")
        errors, warnings = check_file(file_path, config, check_tokens=not args.skip_tokens)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    if all_warnings:
        print("File size target warnings:", file=sys.stderr)
        for warning in all_warnings:
            print(f"  {warning}", file=sys.stderr)

    # Report results
    if all_errors:
        print("File size limit violations:", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"Config: {config_path}")
        print(f"Checked {len(files_to_check)} file(s): OK")


if __name__ == "__main__":
    main()
