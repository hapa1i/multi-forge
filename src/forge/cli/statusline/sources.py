"""Fail-open source acquisition for one status-line render.

This module owns proxy, transcript, session, and Git facts. It deliberately
contains no palette, segment, or layout knowledge, so the command entrypoint and
render context consume source facts from a lower layer.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from forge.cli.statusline.types import ProxyRuntimeTruth, TranscriptStats
from forge.core.transcript import resolve_entry_role

__all__ = [
    "compute_cache_hit_rate",
    "detect_proxy",
    "discover_session",
    "get_git_branch",
    "get_line_change_values",
    "get_transcript_stats",
    "scan_transcript",
]

logger = logging.getLogger(__name__)

_EMPTY_STATS = TranscriptStats()
_NUMSTAT_TTL_SECS = 5.0

# Order 35 decides whether these process-local caches survive. This extraction
# preserves their current keys, values, and lifetime without widening them.
_transcript_cache: dict[str, tuple[int, int, TranscriptStats]] = {}
_numstat_cache: dict[str, tuple[float, tuple[int, int]]] = {}


def detect_proxy() -> tuple[bool, ProxyRuntimeTruth | None, bool]:
    """Detect proxy use and return runtime truth plus its authority.

    ``is_authoritative=True`` means the live proxy identity endpoint succeeded;
    ``False`` means the result came from registry fallback.
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
    if not base_url:
        return False, None, False

    # Parse as a URL for arbitrary hosts, including scheme-less localhost forms.
    from urllib.parse import urlparse

    normalized = base_url if "://" in base_url else f"http://{base_url}"
    # Query only scheme://netloc/ because the proxy serves identity at root.
    try:
        parsed = urlparse(normalized)
        if not parsed.hostname:
            return False, None, False
    except ValueError as e:
        logger.debug("Invalid ANTHROPIC_BASE_URL %r: %s", base_url, e)
        return False, None, False

    # A failed live probe falls back to reverse lookup in the proxy registry.
    try:
        import urllib.request

        query_url = f"{parsed.scheme}://{parsed.netloc}/"
        with urllib.request.urlopen(query_url, timeout=_status_timeout()) as response:
            proxy_info = json.loads(response.read())

        if proxy_info.get("is_proxy") is True:
            return True, ProxyRuntimeTruth(proxy_info), True
    except Exception:
        pass

    try:
        from forge.proxy.proxies import ProxyRegistryStore

        registry = ProxyRegistryStore().read()
        target_port = parsed.port
        for proxy_id, entry in registry.proxies.items():
            entry_normalized = entry.base_url if "://" in (entry.base_url or "") else f"http://{entry.base_url or ''}"
            entry_parsed = urlparse(entry_normalized)
            match = (target_port is not None and entry_parsed.port == target_port) or (
                target_port is None and parsed.netloc == entry_parsed.netloc
            )
            if match:
                runtime_dict: dict[str, Any] = {}
                try:
                    from forge.config.loader import load_proxy_instance_config
                    from forge.core.models import get_context_window_tokens

                    proxy_config = load_proxy_instance_config(proxy_id)
                    if proxy_config is not None:
                        tier_models = {
                            tier: model
                            for tier, model in [
                                ("haiku", proxy_config.tiers.haiku),
                                ("sonnet", proxy_config.tiers.sonnet),
                                ("opus", proxy_config.tiers.opus),
                            ]
                            if model
                        }
                        context_windows: dict[str, int] = {}
                        for tier, model in tier_models.items():
                            try:
                                context_windows[tier] = get_context_window_tokens(model)
                            except Exception:
                                pass
                        active_tier = proxy_config.default_tier or "sonnet"
                        active_cw = context_windows.get(active_tier) or context_windows.get("sonnet")
                        runtime_dict = {
                            "tier_mappings": tier_models,
                            "context_windows": context_windows,
                            "active_tier": active_tier,
                            "active_context_window": active_cw,
                        }
                except Exception:
                    pass

                fallback_info = {
                    "is_proxy": True,
                    "proxy": {
                        "proxy_id": proxy_id,
                        "template": entry.template,
                        "port": entry.port,
                        "base_url": entry.base_url,
                    },
                    "runtime": runtime_dict,
                    "tiers": {},
                }
                return True, ProxyRuntimeTruth(fallback_info), False
    except Exception:
        pass

    return False, None, False


def get_transcript_stats(transcript_path: str) -> TranscriptStats:
    """Return transcript stats, reusing an unchanged file's process-local scan.

    The cache key remains ``(path, mtime_ns, size)`` until order 35 decides the
    process-cache disposition.
    """
    if not transcript_path:
        return _EMPTY_STATS

    try:
        st = Path(transcript_path).stat()
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        return _EMPTY_STATS

    cached = _transcript_cache.get(transcript_path)
    if cached is not None and (cached[0], cached[1]) == key:
        return cached[2]

    stats = scan_transcript(transcript_path)
    _transcript_cache[transcript_path] = (key[0], key[1], stats)
    return stats


def scan_transcript(transcript_path: str) -> TranscriptStats:
    """Scan a transcript once for thinking, counts, and token metrics.

    Supports old top-level ``type`` rows and newer ``message.role`` rows. One
    pass extracts the thinking indicator, user-turn/tool-call counts, and
    cumulative input/output/cache token usage.
    """
    if not transcript_path:
        return _EMPTY_STATS

    path = Path(transcript_path)
    if not path.is_file():
        return _EMPTY_STATS

    user_count = 0
    tool_count = 0
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    last_assistant_content: list[Any] | None = None

    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    role = resolve_entry_role(entry)

                    if role == "user":
                        # New-format tool results also use role=user; only count
                        # actual human turns.
                        content = entry.get("message", {}).get("content", [])
                        is_tool_result = isinstance(content, list) and any(
                            isinstance(block, dict) and block.get("type") == "tool_result" for block in content
                        )
                        if not is_tool_result:
                            user_count += 1
                    elif role == "assistant":
                        content = entry.get("message", {}).get("content", [])
                        last_assistant_content = content
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                tool_count += 1

                    usage = entry.get("message", {}).get("usage")
                    if usage:
                        input_tokens += usage.get("input_tokens", 0)
                        output_tokens += usage.get("output_tokens", 0)
                        cached_tokens += usage.get("cache_read_input_tokens", 0)
                        cached_tokens += usage.get("cache_creation_input_tokens", 0)
                except json.JSONDecodeError:
                    continue
    except Exception:
        return _EMPTY_STATS

    has_thinking = False
    if last_assistant_content:
        for block in last_assistant_content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                has_thinking = True
                break

    return TranscriptStats(
        has_thinking=has_thinking,
        user_count=user_count,
        tool_count=tool_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )


def compute_cache_hit_rate(transcript_path: str) -> float | None:
    """Return the proxy-compatible cache-read rate for a transcript.

    Formula: ``sum(cache_read_input_tokens) / sum(input_tokens) * 100``.
    Entries are deduped by ``requestId`` (fallback ``message.id``), keeping the
    snapshot with the largest input count because streaming appends growing
    usage records. Returns ``0.0`` for input without cache reads and ``None``
    for missing or unreadable data.
    """
    if not transcript_path:
        return None
    path = Path(transcript_path)
    if not path.is_file():
        return None

    by_request: dict[str, tuple[int, int]] = {}
    try:
        with path.open(encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                # Claude transcripts are external artifacts: skip unexpected
                # row shapes/types instead of crashing an opt-in segment.
                try:
                    entry = json.loads(line)
                    message = entry.get("message")
                    if not isinstance(message, dict):
                        continue
                    usage = message.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    request_id = entry.get("requestId") or message.get("id")
                    key = str(request_id) if request_id is not None else f"_line_{idx}"
                    input_tokens = _safe_int(usage.get("input_tokens"))
                    cache_read = _safe_int(usage.get("cache_read_input_tokens"))
                except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                    continue
                previous = by_request.get(key)
                if previous is None or input_tokens >= previous[0]:
                    by_request[key] = (input_tokens, cache_read)
    except OSError:
        return None

    if not by_request:
        return None
    total_input = sum(value[0] for value in by_request.values())
    total_cache_read = sum(value[1] for value in by_request.values())
    if total_input <= 0:
        return 0.0
    return round(total_cache_read / total_input * 100, 1)


def get_git_branch(current_dir: str) -> str | None:
    """Return the current branch or detached-head revision for a directory."""
    if not current_dir:
        return None

    try:
        timeout = _status_timeout()
        result = subprocess.run(
            ["git", "-C", current_dir, "symbolic-ref", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()

        result = subprocess.run(
            ["git", "-C", current_dir, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return None


def get_line_change_values(cost_data: dict[str, Any], current_dir: str = "") -> tuple[int, int]:
    """Prefer Claude line totals, then fall back to cached Git numstat facts."""
    if cost_data:
        lines_added = int(cost_data.get("total_lines_added", 0) or 0)
        lines_removed = int(cost_data.get("total_lines_removed", 0) or 0)
        if lines_added > 0 or lines_removed > 0:
            return lines_added, lines_removed

    if not current_dir:
        return 0, 0

    return _git_numstat(current_dir)


def discover_session() -> tuple[dict[str, Any] | None, bool]:
    """Discover a session through FORGE_SESSION without a CWD fallback.

    Returns ``(manifest, True)`` after environment identity plus index lookup,
    or ``(None, False)`` when no authoritative session is available.
    """
    session_name = os.environ.get("FORGE_SESSION")
    if not session_name:
        return None, False

    forge_root = os.environ.get("FORGE_FORGE_ROOT")

    try:
        # Lazy imports keep status-line startup independent of session modules
        # when the source is not requested.
        from forge.session.index import IndexStore
        from forge.session.store import get_manifest_path

        entry = IndexStore().get_session(session_name, forge_root=forge_root)
        if entry:
            manifest_path = get_manifest_path(entry.forge_root or entry.worktree_path, session_name)
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                return manifest, True
    except Exception as e:
        logger.debug("Index lookup failed for FORGE_SESSION=%s: %s", session_name, e)

    return None, False


def _status_timeout() -> float:
    from forge.runtime_config import get_runtime_config

    return get_runtime_config().status_timeout


def _safe_int(value: Any) -> int:
    """Coerce a transcript usage field to int; return zero on bad input."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _parse_numstat(output: str) -> tuple[int, int]:
    """Parse ``git diff --numstat`` output into added/removed totals."""
    added = 0
    removed = 0

    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        add_str, remove_str = parts[0], parts[1]
        if add_str.isdigit():
            added += int(add_str)
        if remove_str.isdigit():
            removed += int(remove_str)

    return added, removed


def _git_numstat(current_dir: str) -> tuple[int, int]:
    """Read staged and unstaged Git numstat totals with the existing TTL."""
    now = time.monotonic()
    cached = _numstat_cache.get(current_dir)
    if cached is not None and (now - cached[0]) < _NUMSTAT_TTL_SECS:
        return cached[1]

    try:
        timeout = _status_timeout()
        unstaged = subprocess.run(
            ["git", "-C", current_dir, "diff", "--numstat"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        staged = subprocess.run(
            ["git", "-C", current_dir, "diff", "--cached", "--numstat"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if unstaged.returncode != 0 or staged.returncode != 0:
            result = (0, 0)
        else:
            unstaged_added, unstaged_removed = _parse_numstat(unstaged.stdout)
            staged_added, staged_removed = _parse_numstat(staged.stdout)
            result = (unstaged_added + staged_added, unstaged_removed + staged_removed)
    except Exception:
        result = (0, 0)

    _numstat_cache[current_dir] = (now, result)
    return result
