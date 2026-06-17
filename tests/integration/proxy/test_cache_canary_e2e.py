"""Paid cache canaries for real Claude Code traffic through Forge proxies."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from forge.core.reactive.env import CLAUDE_CODE_ATTRIBUTION_HEADER_VAR, build_claude_env
from tests.integration.proxy.conftest import RegisteredProxyServer

pytestmark = [pytest.mark.integration, pytest.mark.slow]


_CACHE_CANARY_MIN_CACHED_TOKENS = 500
_CACHE_CANARY_REPEAT_ATTEMPTS = 3
_CACHE_CANARY_MODEL = "claude-haiku-4-5-20251001"
_CACHE_CANARY_PROMPT = "Reply with exactly one word: ok"


def _request_records(forge_home: Path) -> list[dict[str, Any]]:
    records_dir = forge_home / "costs" / "requests"
    if not records_dir.is_dir():
        return []
    indexed_records: list[tuple[str, str, int, dict[str, Any]]] = []
    for records_path in sorted(records_dir.glob("*.jsonl")):
        for line_no, line in enumerate(records_path.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                record = json.loads(line)
                indexed_records.append((str(record.get("ts") or ""), records_path.name, line_no, record))
    return [record for *_ordering, record in sorted(indexed_records)]


def _matching_records(forge_home: Path, *, proxy_id: str) -> list[dict[str, Any]]:
    return [record for record in _request_records(forge_home) if record.get("proxy_id") == proxy_id]


def _wait_for_new_matching_records(
    forge_home: Path,
    *,
    proxy_id: str,
    previous_count: int,
    min_new_records: int,
    timeout_s: float = 20.0,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        records = _matching_records(forge_home, proxy_id=proxy_id)
        new_records = records[previous_count:]
        if len(new_records) >= min_new_records:
            return new_records
        time.sleep(0.2)
    records = _matching_records(forge_home, proxy_id=proxy_id)
    return records[previous_count:]


def _require_claude() -> str:
    claude = shutil.which("claude")
    if not claude:
        pytest.fail("claude CLI is required for the paid cache canary")
    try:
        version = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=15)
    except Exception as exc:  # pragma: no cover - defensive diagnostics
        pytest.fail(f"claude CLI is not runnable: {exc}")
    if version.returncode != 0:
        pytest.fail(f"claude --version failed: {version.stderr or version.stdout}")
    return version.stdout.strip() or version.stderr.strip()


def _write_stable_cache_prefix(tmp_path: Path) -> Path:
    prefix_path = tmp_path / "forge-cache-canary-prefix.md"
    stable_terms = " ".join(f"forge-cache-canary-stable-token-{index:04d}" for index in range(1400))
    prefix_path.write_text(
        "\n".join(
            [
                "Forge cache canary prefix.",
                "This text is intentionally stable and repeated across both canary requests.",
                stable_terms,
                "The expected answer is the lowercase word ok.",
            ]
        ),
        encoding="utf-8",
    )
    return prefix_path


def _run_claude_cache_probe(
    proxy: RegisteredProxyServer,
    *,
    cwd: Path,
    prompt_file: Path,
) -> subprocess.CompletedProcess[str]:
    env = build_claude_env(
        base_url=proxy.base_url,
        extra_vars={"ANTHROPIC_API_KEY": "forge-proxy-cache-canary"},
        derive_run_identity=False,
    )
    # Unit tests pin the exact env-policy matrix; this paid canary verifies that
    # those preconditions still produce a cache read through the real CLI/proxy/upstream path.
    assert env["ANTHROPIC_BASE_URL"] == proxy.base_url
    assert env[CLAUDE_CODE_ATTRIBUTION_HEADER_VAR] == "0"

    return subprocess.run(
        [
            "claude",
            "-p",
            _CACHE_CANARY_PROMPT,
            "--model",
            _CACHE_CANARY_MODEL,
            "--append-system-prompt-file",
            str(prompt_file),
            "--output-format",
            "json",
            "--bare",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )


def _cached_tokens(records: list[dict[str, Any]]) -> list[int]:
    return [int(record.get("cached_tokens") or 0) for record in records]


def _format_probe_failure(proc: subprocess.CompletedProcess[str]) -> str:
    return f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"


def test_claude_code_proxy_cache_canary_hits_on_repeat(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
    tmp_path: Path,
) -> None:
    """Verify the real Claude Code proxy path still produces prompt-cache reads.

    The test spends real OpenRouter credits and is intentionally marked slow.
    Unit tests pin the exact env scoping for ``CLAUDE_CODE_ATTRIBUTION_HEADER``;
    this canary protects the real-world outcome by failing when repeated Claude
    Code proxy calls stop producing prompt-cache reads.
    """

    version = _require_claude()
    prompt_file = _write_stable_cache_prefix(tmp_path)
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    proxy = registered_proxy_server_openrouter
    before_count = len(_matching_records(module_forge_home, proxy_id=proxy.proxy_id))

    first = _run_claude_cache_probe(proxy, cwd=cwd, prompt_file=prompt_file)
    assert first.returncode == 0, f"first claude cache canary failed with {version}\n" f"{_format_probe_failure(first)}"
    first_records = _wait_for_new_matching_records(
        module_forge_home,
        proxy_id=proxy.proxy_id,
        previous_count=before_count,
        min_new_records=1,
    )
    assert first_records, "first claude cache canary did not produce a proxy cost record"

    repeat_diagnostics: list[dict[str, Any]] = []
    for attempt in range(1, _CACHE_CANARY_REPEAT_ATTEMPTS + 1):
        repeat_before_count = len(_matching_records(module_forge_home, proxy_id=proxy.proxy_id))
        repeat = _run_claude_cache_probe(proxy, cwd=cwd, prompt_file=prompt_file)
        assert repeat.returncode == 0, (
            f"repeat claude cache canary attempt {attempt} failed with {version}\n" f"{_format_probe_failure(repeat)}"
        )
        repeat_records = _wait_for_new_matching_records(
            module_forge_home,
            proxy_id=proxy.proxy_id,
            previous_count=repeat_before_count,
            min_new_records=1,
        )
        assert repeat_records, f"repeat claude cache canary attempt {attempt} did not produce a proxy cost record"

        cached_tokens = _cached_tokens(repeat_records)
        repeat_diagnostics.append(
            {
                "attempt": attempt,
                "cached_tokens": cached_tokens,
                "records": repeat_records,
                "stdout": repeat.stdout,
                "stderr": repeat.stderr,
            }
        )
        if max(cached_tokens, default=0) >= _CACHE_CANARY_MIN_CACHED_TOKENS:
            return

        time.sleep(1.0)

    pytest.fail(
        "real Claude Code proxy repeats did not report a meaningful prompt-cache read; "
        "this can indicate the attribution-header workaround is no longer effective, "
        "Claude Code added another volatile prompt prefix, OpenRouter stopped surfacing "
        "cache reads, or upstream cache semantics changed.\n"
        f"claude_version={version}\n"
        f"first_records={first_records}\n"
        f"repeat_diagnostics={repeat_diagnostics}"
    )
