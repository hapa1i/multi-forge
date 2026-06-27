"""Disk cache for the native-Codex headless preflight (epic consumer_lanes, T4).

The supervisor's codex lane runs per Write/Edit hook, where the ~20s ``codex doctor``
probe is far too slow -- but ``preflight_codex(run_doctor=False)`` falls back to env-only
auth and cannot see ``codex_store`` (ChatGPT-login) auth, which is exactly the ``chatgpt``
backend the lane declares. Without this cache the lane would be permanently
``codex_unavailable`` for its own subscription backend.

The cache breaks the tension: a setup-time command (``forge runtime preflight codex``)
runs the full ``run_doctor=True`` preflight ONCE and writes the secret-free
:class:`CodexPreflight` here; the hot-path hook reads it with cheap ``stat()`` calls only
(no subprocess). Invalidation keys on the readiness inputs Forge can cheaply ``stat`` -- the
codex binary (an upgrade changes its mtime), ``$CODEX_HOME/auth.json`` (codex's own
login/logout), and ``~/.forge/credentials.yaml`` (the ``CODEX_API_KEY`` ``_resolve_codex_auth``
reads *before* the store) -- plus a TTL backstop. Process **env vars** (``CODEX_API_KEY`` /
``CODEX_ACCESS_TOKEN`` in the environment) can't be ``stat``-ed, so they are covered by the TTL
only; both stale directions are fail-open-safe and self-correct (a stale positive fails open
when ``codex exec`` errors; a stale negative just re-runs ``forge runtime preflight codex``).

Runtime-only state: a missing file, a parse failure, a version/shape mismatch, or a stale
key is treated as a **cache miss** (returns ``None``), never an error -- the cache is
always regenerable by re-running the preflight. A stale *positive* is safe too: the codex
arm still fails open if ``codex exec`` errors in-stream, so an over-optimistic cache
self-corrects rather than bricking the hook.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from forge.core.auth.credentials_file import get_credentials_path
from forge.core.paths import get_forge_home
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.core.runtime.codex_rollouts import codex_home
from forge.core.runtime.registry import RuntimeSpec, get_runtime
from forge.core.state.exceptions import StateCorruptedError, StateNotFoundError
from forge.core.state.io import atomic_write_json, read_json

_log = logging.getLogger(__name__)

CODEX_PREFLIGHT_CACHE_VERSION = 1
# TTL backstop for when the auth-store mtime is unavailable (e.g. no auth.json yet): bounds
# how long a stale readiness can be trusted before a fresh `forge runtime preflight codex`.
DEFAULT_PREFLIGHT_TTL_SECONDS = 30 * 60


def _now() -> float:
    """Wall-clock seconds. A seam so tests can pin TTL behavior deterministically."""
    return time.time()


def _cache_path() -> Path:
    return get_forge_home() / "cache" / "codex_preflight.json"


def _auth_store_mtime() -> float | None:
    """mtime of ``$CODEX_HOME/auth.json`` (codex's login store), or None if absent.

    A login/logout rewrites this file, so its mtime is a cheap, precise invalidation
    signal. Absent (never logged in, or a store layout we don't recognize) -> the cache
    falls back to the TTL backstop.
    """
    try:
        return (codex_home() / "auth.json").stat().st_mtime
    except OSError:
        return None


def _credentials_mtime() -> float | None:
    """mtime of ``~/.forge/credentials.yaml``, or None if absent.

    ``_resolve_codex_auth`` reads ``CODEX_API_KEY`` from this file (and env) *before* the codex
    store, so editing it changes readiness -- but unlike auth.json it is a Forge-owned file we
    can ``stat`` cheaply. Env-var auth still can't be stat-ed and stays TTL-only.
    """
    try:
        return get_credentials_path().stat().st_mtime
    except OSError:
        return None


def _codex_binary_signature(runtime: RuntimeSpec) -> tuple[str | None, float | None]:
    """(resolved path, mtime) of the codex binary -- invalidates the cache on an upgrade."""
    path = shutil.which(runtime.headless_cmd[0])
    if not path:
        return None, None
    try:
        return path, Path(path).stat().st_mtime
    except OSError:
        return path, None


def write_codex_preflight_cache(
    preflight: CodexPreflight,
    *,
    runtime: RuntimeSpec | None = None,
) -> Path:
    """Persist a secret-free ``CodexPreflight`` plus its invalidation key. Returns the path.

    Call this only for the **direct** (no-proxy) preflight: the cache answers "is direct
    ``codex exec`` ready?", which is what the supervisor lane needs.
    """
    runtime = runtime or get_runtime("codex")
    bin_path, bin_mtime = _codex_binary_signature(runtime)
    payload: dict[str, Any] = {
        "version": CODEX_PREFLIGHT_CACHE_VERSION,
        "written_at": _now(),
        "codex_bin_path": bin_path,
        "codex_bin_mtime": bin_mtime,
        "auth_store_mtime": _auth_store_mtime(),
        "credentials_mtime": _credentials_mtime(),
        "preflight": asdict(preflight),
    }
    path = _cache_path()
    atomic_write_json(path, payload)
    _log.debug("Wrote codex preflight cache (ready=%s) to %s", preflight.ready, path)
    return path


def read_fresh_codex_preflight(
    *,
    runtime: RuntimeSpec | None = None,
    ttl_seconds: int = DEFAULT_PREFLIGHT_TTL_SECONDS,
) -> CodexPreflight | None:
    """Return the cached ``CodexPreflight`` iff still fresh, else ``None`` (cache miss).

    Fresh = schema version matches, the codex binary signature matches, the auth-store and
    credentials.yaml mtimes match, and ``written_at`` is within ``ttl_seconds``. Any mismatch,
    a missing file, or a corrupt/shape-drifted payload is a miss -- never an exception. Pure
    reads (``which`` + a few ``stat`` calls); no ``codex doctor`` subprocess.

    The "never an exception" contract rests on a narrow ``read_json`` catch plus stat helpers
    that swallow ``OSError`` -- it is a caller convenience, not the safety boundary. The sole
    hot-path caller (``_dispatch_codex_supervisor``) wraps this read in ``except Exception`` ->
    ``codex_unavailable``, so a future helper that broke totality would fail the lane open, not
    leak through the supervisor.
    """
    runtime = runtime or get_runtime("codex")
    try:
        raw = read_json(_cache_path())
    except (StateNotFoundError, StateCorruptedError):
        return None

    if raw.get("version") != CODEX_PREFLIGHT_CACHE_VERSION:
        return None  # discard: a different (older/newer) cache shape, always regenerable

    written_at = raw.get("written_at")
    if not isinstance(written_at, (int, float)) or _now() - written_at > ttl_seconds:
        return None

    bin_path, bin_mtime = _codex_binary_signature(runtime)
    if raw.get("codex_bin_path") != bin_path or raw.get("codex_bin_mtime") != bin_mtime:
        return None  # codex upgraded/moved/removed since the cache was written

    if raw.get("auth_store_mtime") != _auth_store_mtime():
        return None  # login/logout changed the auth store

    if raw.get("credentials_mtime") != _credentials_mtime():
        return None  # ~/.forge/credentials.yaml (CODEX_API_KEY) changed since the cache was written

    fields = raw.get("preflight")
    if not isinstance(fields, dict):
        return None
    try:
        return CodexPreflight(**fields)
    except TypeError:
        return None  # CodexPreflight shape drifted since the cache was written -> discard
