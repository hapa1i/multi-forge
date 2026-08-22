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
    check-file-limits --all-files              # Check every tracked file
    check-file-limits --refresh-token-cache    # Refresh all required provider evidence
    check-file-limits --dry-run                # Show what would be checked
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path

# Method name and tokenizer family for offline counting, as `count-tokens`
# names them on the wire (`--methods` input, `--json` "family" output).
LOCAL_METHOD = "local-tiktoken"
FAMILY_TIKTOKEN = "tiktoken"
FAMILY_ANTHROPIC = "anthropic"
FAMILY_GEMINI = "gemini"
PROVIDER_FAMILIES = {FAMILY_ANTHROPIC, FAMILY_GEMINI}
CACHE_SCHEMA_VERSION = 1

# A repository must opt into provider counting in its tracked policy.
DEFAULT_TOKEN_METHODS = [LOCAL_METHOD]


class TokenCacheError(ValueError):
    """Raised when repository-owned token-count evidence is malformed."""


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
    try:
        config = json.loads(config_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: Cannot read config {config_path}: {exc}", file=sys.stderr)
        sys.exit(1)
    if "extensions" in config and "rules" not in config:
        print(
            "Error: file-size-limits.json uses old 'extensions' format. Migrate to 'rules'.",
            file=sys.stderr,
        )
        sys.exit(1)
    invalid_methods = sorted(
        {
            method
            for rule in config.get("rules", [{}])
            for method in get_token_methods(config, rule)
            if family_for_method(method) is None
        }
    )
    if invalid_methods:
        print(
            "Error: Unknown token counting method(s) in file-size policy: " + ", ".join(invalid_methods),
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


def get_tracked_files() -> list[str]:
    """Get tracked repository files for an explicit all-files check or cache refresh."""
    result = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


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


def family_for_method(method: str) -> str | None:
    """Return the tokenizer family selected by a configured method name."""
    if method == LOCAL_METHOD:
        return FAMILY_TIKTOKEN
    if method.startswith("claude-"):
        return FAMILY_ANTHROPIC
    if method.startswith("gemini-"):
        return FAMILY_GEMINI
    if method.startswith(("gpt-", "o1-", "o3-", "o4-", "chatgpt-")):
        return FAMILY_TIKTOKEN
    return None


def provider_families(methods: list[str]) -> set[str]:
    """Return provider tokenizer families reachable from a method chain."""
    return {family for method in methods if (family := family_for_method(method)) in PROVIDER_FAMILIES}


def method_for_family(methods: list[str], family: str) -> str | None:
    """Return the first configured method that can produce ``family`` counts."""
    return next((method for method in methods if family_for_method(method) == family), None)


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


def resolve_token_cache_path(config: dict, config_path: Path | None = None) -> Path | None:
    """Resolve the repository-owned provider-count cache beside its policy file."""
    configured = config.get("token_count", {}).get("cache")
    if not configured:
        return None
    if not isinstance(configured, str):
        raise TokenCacheError("token_count.cache must be a non-empty path string")
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    base = config_path.parent if config_path is not None else (get_git_root() or Path.cwd())
    return (base / path).resolve()


def load_token_cache(cache_path: Path | None) -> dict[str, dict[str, object]] | None:
    """Load and strictly validate cached provider counts; None means caching is disabled."""
    if cache_path is None:
        return None
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise TokenCacheError(f"cannot read token cache {cache_path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise TokenCacheError(f"token cache {cache_path} must use schema_version {CACHE_SCHEMA_VERSION}")
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        raise TokenCacheError(f"token cache {cache_path} must contain an entries object")
    validated: dict[str, dict[str, object]] = {}
    for file_path, entry in entries.items():
        if not isinstance(file_path, str) or not isinstance(entry, dict):
            raise TokenCacheError(f"token cache {cache_path} contains a malformed entry")
        digest = entry.get("sha256")
        method = entry.get("method")
        family = entry.get("family")
        tokens = entry.get("tokens")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not isinstance(method, str)
            or not method
            or family not in PROVIDER_FAMILIES
            or isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or tokens < 0
        ):
            raise TokenCacheError(f"token cache {cache_path} contains an invalid entry for {file_path}")
        validated[file_path] = {
            "sha256": digest,
            "method": method,
            "family": family,
            "tokens": tokens,
        }
    return validated


def _cache_key(file_path: str, cache_root: Path) -> str:
    """Return a stable repository-relative cache key where possible."""
    path = Path(file_path)
    resolved = path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    try:
        return resolved.relative_to(cache_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _content_sha256(file_path: str) -> str:
    """Hash exact file bytes so cached provider evidence never survives an edit."""
    return hashlib.sha256(Path(file_path).read_bytes()).hexdigest()


def _cached_measurement(
    file_path: str,
    methods: list[str],
    cache_entries: dict[str, dict[str, object]],
    cache_root: Path,
) -> tuple[tuple[int, str, str] | None, str]:
    """Return matching cached provider evidence and a reason when it is unusable."""
    key = _cache_key(file_path, cache_root)
    entry = cache_entries.get(key)
    if entry is None:
        return None, "missing"
    try:
        digest = _content_sha256(file_path)
    except OSError:
        return None, "unreadable"
    if entry["sha256"] != digest:
        return None, "stale"
    method = str(entry["method"])
    family = str(entry["family"])
    tokens = entry["tokens"]
    if method not in methods or family_for_method(method) != family:
        return None, "method-mismatch"
    if isinstance(tokens, bool) or not isinstance(tokens, int):
        return None, "malformed"
    return (
        tokens,
        f"cached provider count ({method})",
        family,
    ), "current"


def write_token_cache(cache_path: Path, entries: dict[str, dict[str, object]]) -> None:
    """Write deterministic repository-owned provider evidence."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_comment": "Authoritative provider counts keyed by exact file bytes; refresh with check-file-limits.py.",
        "schema_version": CACHE_SCHEMA_VERSION,
        "entries": {key: entries[key] for key in sorted(entries)},
    }
    temporary = cache_path.with_name(f".{cache_path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    temporary.replace(cache_path)


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


def provider_probe_threshold(limits: dict) -> int | None:
    """Return the lowest configured threshold for the conservative local screen.

    New provider-backed rules normally configure only a local target. Taking
    the lower value also preserves the conservative behavior of older policies
    that carry both local target and maximum thresholds.
    """
    thresholds = [
        threshold
        for spec in (limits.get("target_tokens"), limits.get("max_tokens"))
        if (threshold := limit_for_family(spec, FAMILY_TIKTOKEN)) is not None
    ]
    return min(thresholds) if thresholds else None


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


def check_file(
    file_path: str,
    config: dict,
    check_tokens: bool = True,
    *,
    cache_entries: dict[str, dict[str, object]] | None = None,
    cache_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Check a file against limits.

    Returns error and target-warning messages.
    """
    if check_tokens:
        return check_files(
            [file_path],
            config,
            cache_entries=cache_entries,
            cache_root=cache_root,
        )

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

    return errors, warnings


def check_files(
    file_paths: list[str],
    config: dict,
    check_tokens: bool = True,
    *,
    cache_entries: dict[str, dict[str, object]] | None = None,
    cache_root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Check files while batching local screens and required provider probes."""
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
    if not local_results:
        all_errors.append(
            f"token counter failed: no local counts returned for {len(token_candidates)} candidate file(s)"
        )
        return all_errors, all_warnings

    measured_results: dict[str, tuple[int, str, str]] = {}
    provider_groups: dict[tuple[str, ...], list[str]] = {}
    direct_groups: dict[tuple[str, ...], list[str]] = {}
    provider_cache_state: dict[str, str] = {}
    provider_pending: set[str] = set()
    screen_passes: set[str] = set()
    cache_root = cache_root or Path.cwd()

    for file_path in token_candidates:
        limits = get_limits(file_path, config)
        if limits is None:
            continue
        methods = get_token_methods(config, limits)
        local_result = local_results.get(file_path)
        if local_result is None:
            all_errors.append(f"{file_path}: local token count unavailable; token limit not enforced")
            continue

        reachable_providers = provider_families(methods)
        if not reachable_providers:
            if methods == [LOCAL_METHOD]:
                measured_results[file_path] = local_result
            else:
                direct_groups.setdefault(tuple(methods), []).append(file_path)
            continue

        local_threshold = provider_probe_threshold(limits)
        if local_threshold is None:
            all_errors.append(
                f"{file_path}: provider-backed rule has no tiktoken target for its conservative local screen"
            )
            continue
        if local_result[0] <= local_threshold:
            screen_passes.add(file_path)
            continue

        if cache_entries is not None:
            cached, cache_state = _cached_measurement(file_path, methods, cache_entries, cache_root)
            provider_cache_state[file_path] = cache_state
            if cached is not None:
                measured_results[file_path] = cached
                continue
        provider_groups.setdefault(tuple(methods), []).append(file_path)
        provider_pending.add(file_path)

    for group_methods, grouped_paths in direct_groups.items():
        measured_results.update(count_tokens_many(grouped_paths, list(group_methods)))

    live_provider_results: dict[str, tuple[int, str, str]] = {}
    for group_methods, grouped_paths in provider_groups.items():
        live_provider_results.update(count_tokens_many(grouped_paths, list(group_methods)))

    for file_path in token_candidates:
        if file_path not in provider_pending:
            continue
        limits = get_limits(file_path, config)
        if limits is None:
            continue
        methods = get_token_methods(config, limits)
        result = live_provider_results.get(file_path)
        if result is None or result[2] not in provider_families(methods):
            cache_state = provider_cache_state.get(file_path, "disabled")
            recovery = (
                f"; run ./scripts/check-file-limits.py --refresh-token-cache {file_path}"
                if cache_entries is not None
                else ""
            )
            all_errors.append(
                f"{file_path}: authoritative provider count unavailable; token cache is {cache_state}{recovery}"
            )
            continue
        measured_results[file_path] = result

    for file_path in token_candidates:
        if file_path in screen_passes:
            continue
        limits = get_limits(file_path, config)
        if limits is None:
            continue
        measured = measured_results.get(file_path)
        if measured is None:
            if not any(error.startswith(f"{file_path}:") for error in all_errors):
                all_errors.append(f"{file_path}: token count unavailable; token limit not enforced")
            continue
        errors, warnings = _evaluate_token_count(
            file_path,
            limits,
            measured,
        )
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        if (
            file_path in live_provider_results
            and cache_entries is not None
            and not errors
            and provider_cache_state.get(file_path) != "current"
        ):
            all_errors.append(
                f"{file_path}: provider count verified but token cache is "
                f"{provider_cache_state.get(file_path, 'missing')}; run "
                "./scripts/check-file-limits.py --refresh-token-cache " + file_path
            )

    return all_errors, all_warnings


def refresh_token_cache(
    file_paths: list[str],
    config: dict,
    cache_path: Path,
    cache_root: Path,
    *,
    replace_all: bool,
) -> tuple[list[str], int]:
    """Refresh provider evidence for files that do not clear their local screen."""
    candidates = [
        file_path
        for file_path in file_paths
        if Path(file_path).exists() and is_whitelisted(file_path, config) and get_limits(file_path, config) is not None
    ]
    if not candidates:
        return [], 0

    local_results = count_tokens_many(candidates, [LOCAL_METHOD])
    if not local_results:
        return [f"token counter failed: no local counts returned for {len(candidates)} candidate file(s)"], 0

    existing = load_token_cache(cache_path) or {}
    entries = {} if replace_all else dict(existing)
    provider_groups: dict[tuple[str, ...], list[str]] = {}
    errors: list[str] = []

    for file_path in candidates:
        key = _cache_key(file_path, cache_root)
        limits = get_limits(file_path, config)
        if limits is None:
            continue
        methods = get_token_methods(config, limits)
        reachable_providers = provider_families(methods)
        local_result = local_results.get(file_path)
        if local_result is None:
            errors.append(f"{file_path}: local token count unavailable")
            continue
        if not reachable_providers:
            entries.pop(key, None)
            continue
        threshold = provider_probe_threshold(limits)
        if threshold is None:
            errors.append(f"{file_path}: provider-backed rule has no tiktoken target")
            continue
        if local_result[0] <= threshold:
            entries.pop(key, None)
            continue
        provider_groups.setdefault(tuple(methods), []).append(file_path)

    provider_results: dict[str, tuple[int, str, str]] = {}
    for method_chain, grouped_paths in provider_groups.items():
        provider_results.update(count_tokens_many(grouped_paths, list(method_chain)))

    refreshed = 0
    for methods_tuple, grouped_paths in provider_groups.items():
        methods = list(methods_tuple)
        reachable_providers = provider_families(methods)
        for file_path in grouped_paths:
            result = provider_results.get(file_path)
            if result is None or result[2] not in reachable_providers:
                errors.append(f"{file_path}: authoritative provider count unavailable; cache not updated")
                continue
            method = method_for_family(methods, result[2])
            if method is None:
                errors.append(f"{file_path}: provider returned an unconfigured tokenizer family {result[2]}")
                continue
            try:
                digest = _content_sha256(file_path)
            except OSError as exc:
                errors.append(f"{file_path}: cannot hash file for token cache: {exc}")
                continue
            entries[_cache_key(file_path, cache_root)] = {
                "sha256": digest,
                "method": method,
                "family": result[2],
                "tokens": result[0],
            }
            refreshed += 1

    if errors:
        return errors, 0
    write_token_cache(cache_path, entries)
    return [], refreshed


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
        "--all-files",
        action="store_true",
        help="Check every tracked file instead of staged or explicitly named files",
    )
    parser.add_argument(
        "--refresh-token-cache",
        action="store_true",
        help="Refresh authoritative provider counts; with no paths, considers every tracked file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show files being checked",
    )

    args = parser.parse_args()
    if args.all_files and args.files:
        parser.error("--all-files cannot be combined with explicit file paths")
    if args.refresh_token_cache and (args.dry_run or args.skip_tokens):
        parser.error("--refresh-token-cache cannot be combined with --dry-run or --skip-tokens")
    config_path = resolve_config_path(args.config)
    config = load_config(config_path)
    try:
        cache_path = resolve_token_cache_path(config, config_path)
    except TokenCacheError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Get files to check
    if args.all_files or (args.refresh_token_cache and not args.files):
        files = get_tracked_files()
    elif args.files:
        files = args.files
    else:
        files = get_staged_files()

    if not files:
        if args.verbose:
            print("No files to check")
        return

    # Filter to whitelisted files with configured limits
    files_to_check = [f for f in files if is_whitelisted(f, config) and get_limits(f, config)]

    if args.refresh_token_cache:
        if cache_path is None:
            print("Error: token_count.cache is required to refresh provider evidence", file=sys.stderr)
            sys.exit(1)
        try:
            errors, refreshed = refresh_token_cache(
                files_to_check,
                config,
                cache_path,
                config_path.parent,
                replace_all=args.all_files or not args.files,
            )
        except TokenCacheError as exc:
            errors = [str(exc)]
            refreshed = 0
        if errors:
            print("Token cache refresh failed:", file=sys.stderr)
            for error in errors:
                print(f"  {error}", file=sys.stderr)
            sys.exit(1)
        print(f"Updated {cache_path} with {refreshed} provider count(s)")
        return

    if args.dry_run:
        print(f"Config: {config_path}")
        print(f"Provider count cache: {cache_path or 'disabled'}")
        print(f"Default token method chain: {' -> '.join(get_token_methods(config))}")
        print(f"Would check {len(files_to_check)} file(s):")
        for f in files_to_check:
            limits = get_limits(f, config) or {}
            chain = " -> ".join(get_token_methods(config, limits))
            print(f"  {f}")
            print(f"      lines:  max {format_number(limits.get('max_lines', 2000))}")
            if probe := provider_probe_threshold(limits):
                print(f"      probe:  local pass through {format_number(probe)} tokens")
            print(f"      tokens: {describe_token_limits(limits.get('max_tokens'))}")
            print(f"      chain:  {chain}")
        return

    if args.verbose:
        for file_path in files_to_check:
            print(f"Checking: {file_path}")
    try:
        cache_entries = load_token_cache(cache_path)
    except TokenCacheError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    all_errors, all_warnings = check_files(
        files_to_check,
        config,
        check_tokens=not args.skip_tokens,
        cache_entries=cache_entries,
        cache_root=config_path.parent,
    )

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
