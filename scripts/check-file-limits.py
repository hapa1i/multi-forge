#!/usr/bin/env python3
"""
Check file size limits (lines and tokens) for staged git files.

Loads repository-owned config when present, then falls back to its bundled default.
Token counting runs `count-tokens` over the chain in `token_count.methods`; the
tokenizer that answers selects which per-family limit applies, since a count from
one tokenizer family is not comparable to a limit written for another.

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

# Method name and tokenizer family for offline counting, as `count-tokens`
# names them on the wire (`--methods` input, `--json` "family" output).
LOCAL_METHOD = "local-tiktoken"
FAMILY_TIKTOKEN = "tiktoken"

# A repository must opt into provider counting in its tracked policy.
DEFAULT_TOKEN_METHODS = [LOCAL_METHOD]


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


def count_tokens(file_path: str, methods: list[str]) -> tuple[int, str, str] | None:
    """Count tokens using count-tokens script.

    Returns (count, method_description, tokenizer_family), or None when no count
    could be obtained. count-tokens walks the chain and degrades to its offline
    tokenizer, so a missing key or a rate limit yields a count from a different
    family rather than no count at all.
    """
    count_tokens_path = get_script_dir() / "count-tokens.py"
    if not count_tokens_path.exists():
        print(f"Warning: count-tokens not found: {count_tokens_path}", file=sys.stderr)
        return None

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
        return int(payload["tokens"]), str(payload["method"]), str(payload["family"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def count_tokens_many(file_paths: list[str], methods: list[str]) -> dict[str, tuple[int, str, str]]:
    """Count files independently in one token-counter process."""
    if not file_paths:
        return {}

    count_tokens_path = get_script_dir() / "count-tokens.py"
    if not count_tokens_path.exists():
        print(f"Warning: count-tokens not found: {count_tokens_path}", file=sys.stderr)
        return {}

    result = subprocess.run(
        [
            str(count_tokens_path),
            "--methods",
            ",".join(methods),
            "--per-file",
            "--json",
            *file_paths,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Warning: count-tokens failed for {len(file_paths)} file(s): {result.stderr}", file=sys.stderr)
        return {}

    counts: dict[str, tuple[int, str, str]] = {}
    try:
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            counts[str(payload["path"])] = (
                int(payload["tokens"]),
                str(payload["method"]),
                str(payload["family"]),
            )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print("Warning: count-tokens returned malformed per-file output", file=sys.stderr)
        return {}
    return counts


def format_number(n: int) -> str:
    """Format number with thousands separator."""
    return f"{n:,}"


def limit_for_family(spec: object, family: str) -> int | None:
    """Resolve a token limit for the tokenizer family that produced a count.

    A mapping keys limits per family; a bare number applies to whichever family
    ran, which keeps older single-limit rules working. Returns None when this
    family has no configured limit instead of borrowing another tokenizer's
    incomparable threshold.
    """
    if isinstance(spec, bool) or spec is None:
        return None
    if isinstance(spec, (int, float)):
        return int(spec)
    if isinstance(spec, dict):
        value = spec.get(family)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return int(value)
    return None


def measure_tokens(file_path: str, methods: list[str], max_spec: object) -> tuple[int, str, str] | None:
    """Count tokens, skipping the provider when the local count already clears.

    A policy may set the local-family limit conservatively enough that clearing
    it proves the provider-family limit also clears. In that case the local
    ceiling doubles as the provider probe threshold, with no second knob to
    drift. Only a local failure needs an authoritative provider count that may
    overturn the estimate.
    """
    if all(method == LOCAL_METHOD for method in methods):
        # The chain is already the probe; running both would count twice.
        return count_tokens(file_path, methods)

    local_limit = limit_for_family(max_spec, FAMILY_TIKTOKEN)
    if local_limit is not None:
        local = count_tokens(file_path, [LOCAL_METHOD])
        if local is not None and local[0] <= local_limit:
            return local
    return count_tokens(file_path, methods)


def describe_token_limits(spec: object) -> str:
    """Render scalar or per-family token thresholds for dry-run output."""
    if isinstance(spec, dict):
        if not spec:
            return "none configured"
        return ", ".join(f"{family} {format_number(int(value))}" for family, value in spec.items())
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return f"{format_number(int(spec))} (any tokenizer)"
    return "none configured"


def _evaluate_token_count(
    file_path: str,
    limits: dict,
    measured: tuple[int, str, str] | None,
) -> tuple[list[str], list[str]]:
    """Evaluate one measured token count against its configured thresholds."""
    if measured is None:
        return [], []

    errors: list[str] = []
    warnings: list[str] = []
    tokens, method, family = measured
    max_tokens = limit_for_family(limits.get("max_tokens"), family)
    target_tokens = limit_for_family(limits.get("target_tokens"), family)
    if max_tokens is None:
        if tokens > 0:
            warnings.append(
                f"{file_path}: no max_tokens configured for the '{family}' tokenizer "
                f"({method}); token limit not enforced"
            )
    elif tokens > max_tokens:
        errors.append(
            f"{file_path}: {format_number(tokens)} tokens exceeds limit of {format_number(max_tokens)} ({method})"
        )
    elif target_tokens is not None and tokens > target_tokens:
        warnings.append(
            f"{file_path}: {format_number(tokens)} tokens exceeds target of "
            f"{format_number(target_tokens)} ({method})"
        )
    return errors, warnings


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

    # Check lines (fast)
    lines = count_lines(file_path)
    if lines > max_lines:
        errors.append(f"{file_path}: {format_number(lines)} lines exceeds limit of {format_number(max_lines)}")
        # Don't bother checking tokens if lines already failed
        return errors, warnings

    # Whichever tokenizer answers decides which limit applies. An unreachable
    # provider degrades to the offline tokenizer and its separately calibrated
    # limit instead of blocking the commit.
    if check_tokens:
        methods = get_token_methods(config, limits)
        measured = measure_tokens(file_path, methods, limits.get("max_tokens"))
        token_errors, token_warnings = _evaluate_token_count(file_path, limits, measured)
        errors.extend(token_errors)
        warnings.extend(token_warnings)

    return errors, warnings


def check_files(file_paths: list[str], config: dict, check_tokens: bool = True) -> tuple[list[str], list[str]]:
    """Check files while batching token-counter process startup."""
    all_errors: list[str] = []
    all_warnings: list[str] = []
    token_candidates: list[str] = []

    for file_path in file_paths:
        errors, warnings = check_file(file_path, config, check_tokens=False)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        if (
            check_tokens
            and not errors
            and is_whitelisted(file_path, config)
            and get_limits(file_path, config) is not None
            and Path(file_path).exists()
        ):
            token_candidates.append(file_path)

    if not token_candidates:
        return all_errors, all_warnings

    local_results = count_tokens_many(token_candidates, [LOCAL_METHOD])
    measured_results: dict[str, tuple[int, str, str]] = {}
    provider_groups: dict[tuple[str, ...], list[str]] = {}

    for file_path in token_candidates:
        limits = get_limits(file_path, config)
        if limits is None:
            continue
        methods = get_token_methods(config, limits)
        local_result = local_results.get(file_path)
        if all(method == LOCAL_METHOD for method in methods):
            if local_result is not None:
                measured_results[file_path] = local_result
            continue

        local_limit = limit_for_family(limits.get("max_tokens"), FAMILY_TIKTOKEN)
        if local_result is not None and local_limit is not None and local_result[0] <= local_limit:
            measured_results[file_path] = local_result
            continue
        provider_groups.setdefault(tuple(methods), []).append(file_path)

    for group_methods, grouped_paths in provider_groups.items():
        measured_results.update(count_tokens_many(grouped_paths, list(group_methods)))

    for file_path in token_candidates:
        limits = get_limits(file_path, config)
        if limits is None:
            continue
        errors, warnings = _evaluate_token_count(
            file_path,
            limits,
            measured_results.get(file_path),
        )
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    return all_errors, all_warnings


def main():
    parser = argparse.ArgumentParser(
        description="Check file size limits for staged files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config",
        help="Policy file (default: <git-root>/.file-size-limits.json, then bundled fallback)",
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
        print(f"Default token method chain: {' -> '.join(get_token_methods(config))}")
        print(f"Would check {len(files_to_check)} file(s):")
        for f in files_to_check:
            limits = get_limits(f, config) or {}
            chain = " -> ".join(get_token_methods(config, limits))
            print(f"  {f}")
            print(f"      lines:  max {format_number(limits.get('max_lines', 2000))}")
            print(f"      tokens: {describe_token_limits(limits.get('max_tokens'))}")
            print(f"      chain:  {chain}")
        return

    if args.verbose:
        for file_path in files_to_check:
            print(f"Checking: {file_path}")
    all_errors, all_warnings = check_files(files_to_check, config, check_tokens=not args.skip_tokens)

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
