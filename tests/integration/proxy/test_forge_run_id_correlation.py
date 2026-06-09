"""Slice 4g canary: a real proxy reads, VALIDATES, and stamps the Forge run-tree
correlation headers onto its cost records, on the real wire.

This is the proxy half of 4g (the write side) against a live Forge proxy + real
upstream: a request carrying ``X-Forge-Run-ID``/``X-Forge-Root-Run-ID`` produces a
cost record whose ``forge_run_id``/``forge_root_run_id`` match, so proxied
``claude -p`` cost can later join to the run tree by ``forge_root_run_id``. A
malformed/spoofed header is dropped (stored ``None``), never trusted into telemetry.

The complementary external claim -- that the real ``claude`` binary forwards
``ANTHROPIC_CUSTOM_HEADERS`` on **every** ``/v1/messages`` request -- is covered by the
``test_real_claude_*`` cases below: plain ``claude -p``, ``claude -p --bare`` (env vars
survive ``--bare``; settings.json does not), and a multi-request tool loop that asserts
EVERY cost record in the window is stamped (a harness that set the header on only the
first request would fail here). This is the load-bearing external dependency of Slice 4g
and its standing version-regression guard.

These make real upstream calls; tiny prompts, integration/slow markers. The Claude Code
version is captured and reported on failure (``CLAUDE_VERSION_VALIDATED`` records the
version this guard was last confirmed against -- update it when re-validating).

Run:
    ./scripts/test-integration.sh tests/integration/proxy/test_forge_run_id_correlation.py -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.integration.proxy.conftest import RegisteredProxyServer

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_RUN = "run_4a1b2c3d4e5f"
_ROOT = "run_0011223344ff"


def _request_records(forge_home: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    d = forge_home / "costs" / "requests"
    if not d.is_dir():
        return out
    for jsonl in sorted(d.glob("*.jsonl")):
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
    return out


def _wait_for_new_record(forge_home: Path, proxy_id: str, before: int, timeout_s: float = 12.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        matching = [r for r in _request_records(forge_home) if r.get("proxy_id") == proxy_id]
        if len(matching) > before:
            return matching[-1]
        time.sleep(0.1)
    pytest.fail(f"no new cost record for proxy_id={proxy_id}")


def _wait_for_records(
    forge_home: Path, proxy_id: str, before: int, *, min_count: int = 1, timeout_s: float = 20.0
) -> list[dict[str, Any]]:
    """Return the cost records for ``proxy_id`` written AFTER ``before``, once at least
    ``min_count`` of them exist. Lets a multi-request run assert EVERY record is stamped."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        matching = [r for r in _request_records(forge_home) if r.get("proxy_id") == proxy_id]
        if len(matching) - before >= min_count:
            return matching[before:]
        time.sleep(0.1)
    matching = [r for r in _request_records(forge_home) if r.get("proxy_id") == proxy_id]
    pytest.fail(f"expected >= {min_count} new records for proxy_id={proxy_id}, got {len(matching) - before}")


def _post(proxy: RegisteredProxyServer, *, headers: dict[str, str]) -> httpx.Response:
    base = {"x-api-key": "test", "user-agent": "claude-code/4g-canary"}
    base.update(headers)
    payload = {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 8,
        "temperature": 0,
        "messages": [{"role": "user", "content": "Reply with exactly one word: ok"}],
        "stream": False,
    }
    with httpx.Client(timeout=60) as client:
        return client.post(f"{proxy.base_url}/v1/messages", json=payload, headers=base)


def test_valid_headers_stamped_on_cost_record(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
) -> None:
    proxy = registered_proxy_server_openrouter
    before = len([r for r in _request_records(module_forge_home) if r.get("proxy_id") == proxy.proxy_id])

    resp = _post(proxy, headers={"X-Forge-Run-ID": _RUN, "X-Forge-Root-Run-ID": _ROOT})
    assert resp.status_code == 200, resp.text[:500]

    record = _wait_for_new_record(module_forge_home, proxy.proxy_id, before)
    assert record["forge_run_id"] == _RUN
    assert record["forge_root_run_id"] == _ROOT


def test_malformed_header_dropped_not_trusted(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
) -> None:
    proxy = registered_proxy_server_openrouter
    before = len([r for r in _request_records(module_forge_home) if r.get("proxy_id") == proxy.proxy_id])

    # A spoof / header-injection attempt and a wrong-shaped id are both rejected by the
    # validator -> persisted as None, never written verbatim into the cost log.
    resp = _post(
        proxy,
        headers={"X-Forge-Run-ID": "not-a-run-id; rm -rf", "X-Forge-Root-Run-ID": _ROOT},
    )
    assert resp.status_code == 200, resp.text[:500]

    record = _wait_for_new_record(module_forge_home, proxy.proxy_id, before)
    assert record["forge_run_id"] is None  # malformed dropped
    assert record["forge_root_run_id"] == _ROOT  # the valid one still stamped


def test_absent_headers_are_none(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
) -> None:
    proxy = registered_proxy_server_openrouter
    before = len([r for r in _request_records(module_forge_home) if r.get("proxy_id") == proxy.proxy_id])

    resp = _post(proxy, headers={})
    assert resp.status_code == 200, resp.text[:500]

    record = _wait_for_new_record(module_forge_home, proxy.proxy_id, before)
    assert record["forge_run_id"] is None
    assert record["forge_root_run_id"] is None


# The Claude Code version this forwarding guard was last confirmed against (all six cases
# green on 2026-06-08, incl. --bare and the multi-request tool loop). Update it when
# re-validating; it is reported (not hard-asserted) so a routine CLI bump doesn't red the
# suite, but a forwarding REGRESSION still fails on the record assertions below.
CLAUDE_VERSION_VALIDATED = "2.1.168"


def _claude_version() -> str:
    proc = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        pytest.fail(f"`claude --version` failed (rc={proc.returncode}): {proc.stderr[:200]!r}")
    version = proc.stdout.strip()
    assert version, "`claude --version` returned empty output"
    return version


def _run_claude_with_headers(
    proxy: RegisteredProxyServer, prompt: str, *, bare: bool, allowed_tools: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["ANTHROPIC_BASE_URL"] = proxy.base_url
    env["ANTHROPIC_CUSTOM_HEADERS"] = f"X-Forge-Run-ID: {_RUN}\nX-Forge-Root-Run-ID: {_ROOT}"
    argv = ["claude", "-p", prompt, "--output-format", "json"]
    if bare:
        argv.append("--bare")
    if allowed_tools:
        argv.extend(["--allowedTools", allowed_tools])
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=180)


def _require_claude() -> str:
    if shutil.which("claude") is None:
        pytest.fail("`claude` binary not on PATH; required for the 4g forwarding canary.")
    return _claude_version()


@pytest.mark.parametrize("bare", [False, True], ids=["plain", "bare"])
def test_real_claude_forwards_custom_headers(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
    bare: bool,
) -> None:
    """The load-bearing external dependency: a real ``claude -p`` (and ``--bare``) routed
    at a live Forge proxy forwards ``ANTHROPIC_CUSTOM_HEADERS`` so the proxy stamps the
    run ids. Env vars survive ``--bare`` (settings.json does not), so both modes must
    forward. If a future Claude Code drops/renames the env var, THIS fails (the
    version-regression guard), not the unit tests. Requires ``claude`` on PATH (never skip).
    """
    version = _require_claude()
    proxy = registered_proxy_server_openrouter
    before = len([r for r in _request_records(module_forge_home) if r.get("proxy_id") == proxy.proxy_id])

    proc = _run_claude_with_headers(proxy, "Reply with exactly one word: ok", bare=bare)
    assert proc.returncode == 0, (
        f"claude -p{' --bare' if bare else ''} failed on {version}: "
        f"stdout={proc.stdout[:300]!r} stderr={proc.stderr[:300]!r}"
    )

    record = _wait_for_new_record(module_forge_home, proxy.proxy_id, before)
    # Proof the real binary forwarded both Forge-owned headers to the proxy (claude {version}).
    assert (
        record["forge_run_id"] == _RUN
    ), f"header not forwarded on claude {version} (validated {CLAUDE_VERSION_VALIDATED})"
    assert record["forge_root_run_id"] == _ROOT


def test_real_claude_multi_request_stamps_every_record(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
) -> None:
    """A tool loop forces >= 2 ``/v1/messages`` requests; EVERY resulting cost record must
    carry the run ids. A harness that set the header on only the first request (or dropped
    it on tool-result follow-ups) would pass the single-request case but fail here.
    """
    version = _require_claude()
    proxy = registered_proxy_server_openrouter
    before = len([r for r in _request_records(module_forge_home) if r.get("proxy_id") == proxy.proxy_id])

    # A prompt that requires a tool call -> the model requests, gets the tool result, then
    # responds: at least two upstream requests, hence at least two cost records.
    proc = _run_claude_with_headers(
        proxy,
        "Use the Bash tool to run `echo forge-4g-canary` and report its exact output. "
        "You must run the command; do not guess.",
        bare=False,
        allowed_tools="Bash",
    )
    assert proc.returncode == 0, f"claude -p tool loop failed on {version}: stderr={proc.stderr[:300]!r}"

    records = _wait_for_records(module_forge_home, proxy.proxy_id, before, min_count=2)
    assert (
        len(records) >= 2
    ), f"expected a multi-request tool loop (>= 2 records) on claude {version}, got {len(records)}"
    for i, record in enumerate(records):
        assert record["forge_run_id"] == _RUN, f"record {i} of {len(records)} unstamped on claude {version}"
        assert record["forge_root_run_id"] == _ROOT, f"record {i} of {len(records)} missing root on claude {version}"
