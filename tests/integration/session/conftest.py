"""Shared fixtures for host-based real-``codex exec`` smoke tests (epic consumer_lanes T6b/T6c).

These smokes spawn the host ``codex`` binary on the ChatGPT (``codex_store``) **subscription**
lane, so they need the host's real auth store restored past the autouse isolation fixtures and the
live preflight seeded into the cache the dispatch arms read. Extracted here (rather than copied per
file) because ``real_codex_home`` is correctness-critical: it suppresses ``CODEX_API_KEY`` so the
subscription lane wins -- a drifted copy could silently assert ``subscription_quota`` while actually
running on an API key.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from forge.core.runtime.codex_preflight import CodexPreflight, preflight_codex
from forge.core.runtime.codex_preflight_cache import write_codex_preflight_cache

# Captured at import time -- BEFORE the autouse ``isolate_codex_home`` fixture overrides CODEX_HOME --
# so the fixtures below can restore the host's real codex auth store for the real ``codex exec`` run.
_REAL_CODEX_HOME = os.environ.get("CODEX_HOME") or str(Path.home() / ".codex")


@pytest.fixture
def real_codex_home(monkeypatch: pytest.MonkeyPatch) -> str:
    """Restore the host ChatGPT (``codex_store``) auth and force it to win.

    These E2Es exercise the codex/chatgpt **subscription** lane, so they need the host's ChatGPT
    login -- not an API key. Two env adjustments:

    - Restore CODEX_HOME (the autouse ``isolate_codex_home`` fixture repoints it at an empty temp
      dir) so the ``codex doctor`` probe and the spawned ``codex exec`` see ``~/.codex/auth.json``.
    - Clear CODEX_API_KEY / CODEX_ACCESS_TOKEN, which ``preflight_codex`` resolves *before*
      ``codex_store`` (codex_preflight.py): on a machine with both an API key and a ChatGPT login
      they would win and resolve ``billing_mode="api"``, failing the ``subscription_quota`` assertion.
      The isolated FORGE_HOME already hides any credentials.yaml key.
    """
    auth = Path(_REAL_CODEX_HOME) / "auth.json"
    if not auth.is_file():
        pytest.fail(f"no codex auth store at {auth}. Run 'codex login --device-auth' (ChatGPT).")
    monkeypatch.setenv("CODEX_HOME", _REAL_CODEX_HOME)
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_ACCESS_TOKEN", raising=False)
    return _REAL_CODEX_HOME


@pytest.fixture
def codex_ready_cached(real_codex_home: str) -> CodexPreflight:
    """Live preflight (must resolve the ChatGPT subscription lane), then seed the cache the arm reads.

    The dispatch arms read ``read_fresh_codex_preflight()`` (the cache), not the live probe -- and
    the autouse ``isolate_forge_home`` fixture points FORGE_HOME at a fresh temp dir, so the cache is
    empty until this writes it. Fails loud unless auth resolves to ``codex_store`` /
    ``subscription_quota`` -- the exact lane these E2Es assert -- so an API-key-only machine gets an
    actionable message instead of a confusing ``billing_mode`` mismatch downstream.
    """
    pf = preflight_codex()
    if not pf.ready:
        pytest.fail(f"codex not ready ({pf.blocking_reason}). Run 'codex login --device-auth' (ChatGPT).")
    if pf.auth_source != "codex_store" or pf.billing_mode != "subscription_quota":
        pytest.fail(
            "this E2E exercises the codex/chatgpt subscription lane, but preflight resolved "
            f"auth_source={pf.auth_source!r} billing_mode={pf.billing_mode!r}. "
            "Log in with 'codex login --device-auth' (ChatGPT)."
        )
    write_codex_preflight_cache(pf)
    return pf


@pytest.fixture
def codex_git_forge_root(tmp_path: Path) -> Path:
    """A git-initialized ``forge_root`` (codex exec refuses to run outside a git repo)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "smoke@test.local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "smoke"], cwd=tmp_path, check=True)
    return tmp_path
