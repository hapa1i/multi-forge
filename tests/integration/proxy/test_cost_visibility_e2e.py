"""End-to-end smoke tests for proxy cost visibility.

These tests intentionally make real upstream LLM calls. They stay out of the
unit suite via integration/slow markers and keep prompts/tokens tiny.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from click.testing import CliRunner

from forge.cli.main import main
from forge.review.models import DEFAULT_MODELS, ModelSpec
from tests.integration.proxy.conftest import RegisteredProxyServer

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _read_jsonl_dir(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.is_dir():
        return records

    for jsonl in sorted(path.glob("*.jsonl")):
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def _request_records(forge_home: Path) -> list[dict[str, Any]]:
    return _read_jsonl_dir(forge_home / "costs" / "requests")


def _verb_records(forge_home: Path) -> list[dict[str, Any]]:
    return _read_jsonl_dir(forge_home / "costs" / "verbs")


def _wait_for_matching_records(
    reader,
    previous_matching_count: int,
    *,
    proxy_id: str,
    timeout_s: float = 10.0,
) -> list[dict[str, Any]]:
    """Wait until the number of records matching proxy_id exceeds previous_matching_count."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        all_records = reader()
        matching = [r for r in all_records if r.get("proxy_id") == proxy_id]
        if len(matching) > previous_matching_count:
            return matching[previous_matching_count:]
        time.sleep(0.1)
    all_records = reader()
    matching = [r for r in all_records if r.get("proxy_id") == proxy_id]
    return matching[previous_matching_count:]


def _tiny_message_payload(*, stream: bool = False) -> dict[str, Any]:
    return {
        "model": "claude-3-5-haiku-20241022",
        "max_tokens": 8,
        "temperature": 0,
        "messages": [{"role": "user", "content": "Reply with exactly one word: ok"}],
        "stream": stream,
    }


def _post_tiny_message(proxy: RegisteredProxyServer) -> httpx.Response:
    with httpx.Client(timeout=60) as client:
        return client.post(
            f"{proxy.base_url}/v1/messages",
            json=_tiny_message_payload(),
            headers={"x-api-key": "test", "user-agent": "claude-code/cost-e2e"},
        )


@pytest.mark.parametrize(
    "fixture_name,expected_reporter,expected_confidence",
    [
        # OpenRouter reports actual spend in the response body (usage.cost).
        ("registered_proxy_server_openrouter", "openrouter", "reported"),
        # A LiteLLM gateway computes spend and returns it in x-litellm-response-cost.
        ("registered_proxy_server_local_gemini", "litellm", "gateway_calculated"),
    ],
)
def test_proxy_non_streaming_cost_smoke(
    request: pytest.FixtureRequest,
    fixture_name: str,
    expected_reporter: str,
    expected_confidence: str,
    module_forge_home: Path,
) -> None:
    """A real proxy request writes a route-reported cost record and returns cost headers."""
    proxy: RegisteredProxyServer = request.getfixturevalue(fixture_name)
    all_before = _request_records(module_forge_home)
    before_matching = len([r for r in all_before if r.get("proxy_id") == proxy.proxy_id])

    resp = _post_tiny_message(proxy)

    assert resp.status_code == 200, resp.text[:500]
    assert resp.headers.get("X-Resolved-Tier") == "haiku"
    assert float(resp.headers["X-Request-Cost"]) > 0
    assert float(resp.headers["X-Cumulative-Cost"]) > 0

    new_records = _wait_for_matching_records(
        lambda: _request_records(module_forge_home),
        before_matching,
        proxy_id=proxy.proxy_id,
    )
    assert new_records, f"No cost records for proxy_id={proxy.proxy_id}"

    record = new_records[-1]
    assert record["tier"] == "haiku"
    assert record["input_tokens"] > 0
    assert record["output_tokens"] > 0
    assert record["cost_micros"] > 0
    assert record["failed"] is False
    # Provenance proves the figure is route-reported, not a catalog estimate.
    # This is the gate for Step 3: if a gateway can't report cost, this fails here
    # rather than silently regressing to 'unavailable' once the catalog is gone.
    assert record["reporter"] == expected_reporter
    assert record["confidence"] == expected_confidence


def test_openrouter_streaming_cost_smoke(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
) -> None:
    """Streaming has no per-request header, but logs cost after the stream completes."""
    proxy = registered_proxy_server_openrouter
    all_before = _request_records(module_forge_home)
    before_matching = len([r for r in all_before if r.get("proxy_id") == proxy.proxy_id])

    with httpx.Client(timeout=60) as client:
        with client.stream(
            "POST",
            f"{proxy.base_url}/v1/messages",
            json=_tiny_message_payload(stream=True),
            headers={"x-api-key": "test", "user-agent": "claude-code/cost-e2e"},
        ) as resp:
            assert resp.status_code == 200
            assert "X-Request-Cost" not in resp.headers
            assert "X-Cumulative-Cost" in resp.headers
            events = [line for line in resp.iter_lines() if line.startswith("data: ")]

    assert events
    new_records = _wait_for_matching_records(
        lambda: _request_records(module_forge_home),
        before_matching,
        proxy_id=proxy.proxy_id,
    )
    assert new_records, f"No cost records for proxy_id={proxy.proxy_id}"
    assert new_records[-1]["cost_micros"] > 0
    # Streaming reported cost rides the final usage chunk (OpenRouter usage.cost).
    assert new_records[-1]["reporter"] == "openrouter"
    assert new_records[-1]["confidence"] == "reported"


def test_local_litellm_streaming_cost_unavailable(
    registered_proxy_server_local_gemini: RegisteredProxyServer,
    module_forge_home: Path,
) -> None:
    """A LiteLLM gateway does NOT report cost on the streaming (SSE) path.

    Verified gap (card risk): LiteLLM's x-litellm-response-cost header is emitted at
    stream start, before token counts/cost exist, and this gateway does not put cost
    in the final usage chunk body. So streaming LiteLLM cost is never route-reported —
    catalog-inferred while the catalog exists (Step 2), 'unavailable' once Step 3
    removes it. Tokens are always captured regardless. This asserts the durable
    invariant (never a false gateway/reported claim) so it survives the Step 3 flip.
    """
    proxy = registered_proxy_server_local_gemini
    all_before = _request_records(module_forge_home)
    before_matching = len([r for r in all_before if r.get("proxy_id") == proxy.proxy_id])

    with httpx.Client(timeout=60) as client:
        with client.stream(
            "POST",
            f"{proxy.base_url}/v1/messages",
            json=_tiny_message_payload(stream=True),
            headers={"x-api-key": "test", "user-agent": "claude-code/cost-e2e"},
        ) as resp:
            assert resp.status_code == 200
            events = [line for line in resp.iter_lines() if line.startswith("data: ")]

    assert events
    new_records = _wait_for_matching_records(
        lambda: _request_records(module_forge_home),
        before_matching,
        proxy_id=proxy.proxy_id,
    )
    assert new_records, f"No cost records for proxy_id={proxy.proxy_id}"
    record = new_records[-1]
    # Tokens are captured even when cost is unavailable.
    assert record["output_tokens"] > 0
    # Never a false route-reported cost on the LiteLLM stream (the documented gap).
    assert record["reporter"] != "litellm"
    assert record["confidence"] not in ("reported", "gateway_calculated")


def _install_proxying_claude_shim(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "claude"
    shim.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.request


def _arg_value(flag, default=None):
    if flag not in sys.argv:
        return default
    index = sys.argv.index(flag)
    if index + 1 >= len(sys.argv):
        return default
    return sys.argv[index + 1]


def _response_text(data):
    content = data.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


base_url = os.environ.get("ANTHROPIC_BASE_URL")
if not base_url:
    print("ANTHROPIC_BASE_URL missing", file=sys.stderr)
    sys.exit(2)

prompt = sys.stdin.read()
capture_path = os.environ.get("FORGE_E2E_CLAUDE_CAPTURE")
if capture_path:
    with open(capture_path, "a") as capture:
        capture.write(json.dumps({
            "argv": sys.argv[1:],
            "anthropic_base_url": base_url,
            "subprocess_proxy": os.environ.get("FORGE_SUBPROCESS_PROXY"),
        }) + "\\n")

payload = {
    "model": _arg_value("--model", "claude-3-5-haiku-20241022"),
    "max_tokens": 8,
    "temperature": 0,
    "messages": [{"role": "user", "content": prompt}],
}
request = urllib.request.Request(
    base_url.rstrip("/") + "/v1/messages",
    data=json.dumps(payload).encode(),
    headers={
        "content-type": "application/json",
        "x-api-key": "test",
        "user-agent": "claude-code/panel-e2e",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read())
except urllib.error.HTTPError as exc:
    print(exc.read().decode(errors="replace"), file=sys.stderr)
    sys.exit(1)

text = _response_text(data).strip()
print(text or "ok")
""",
        encoding="utf-8",
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def test_panel_with_subprocess_proxy_records_verb_cost(
    registered_proxy_server_openrouter: RegisteredProxyServer,
    module_forge_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A minimal real panel worker routes through FORGE_SUBPROCESS_PROXY and logs panel cost."""
    proxy = registered_proxy_server_openrouter
    bin_dir = _install_proxying_claude_shim(tmp_path)
    capture_path = tmp_path / "claude-capture.jsonl"

    monkeypatch.setenv("FORGE_HOME", str(module_forge_home))
    monkeypatch.setenv("FORGE_SUBPROCESS_PROXY", proxy.proxy_id)
    monkeypatch.setenv("FORGE_E2E_CLAUDE_CAPTURE", str(capture_path))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setitem(
        DEFAULT_MODELS,
        "e2e-haiku-subprocess",
        ModelSpec(
            name="e2e-haiku-subprocess",
            model_id="e2e-haiku-subprocess",
            family="anthropic",
            provider_refs=(("openrouter", "claude-3-5-haiku-20241022"),),
            description="e2e subprocess-proxy panel canary",
        ),
    )

    all_req_before = _request_records(module_forge_home)
    before_request_matching = len([r for r in all_req_before if r.get("proxy_id") == proxy.proxy_id])
    before_verb_count = len(_verb_records(module_forge_home))

    result = CliRunner().invoke(
        main,
        [
            "workflow",
            "panel",
            "-p",
            "Reply with exactly one word: ok",
            "--models",
            "e2e-haiku-subprocess",
            "--timeout",
            "60",
            "--json",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["successful"] == 1
    assert payload["failed"] == 0

    capture_records = [json.loads(line) for line in capture_path.read_text().splitlines()]
    assert capture_records
    assert capture_records[-1]["anthropic_base_url"] == proxy.base_url
    assert capture_records[-1]["subprocess_proxy"] == proxy.proxy_id

    request_records = _wait_for_matching_records(
        lambda: _request_records(module_forge_home),
        before_request_matching,
        proxy_id=proxy.proxy_id,
    )
    assert request_records, f"No cost records for proxy_id={proxy.proxy_id}"
    assert any(r.get("cost_micros", 0) > 0 for r in request_records)

    all_verbs = _verb_records(module_forge_home)
    verb_records = all_verbs[before_verb_count:]
    panel_records = [r for r in verb_records if r.get("verb") == "panel"]
    assert panel_records, verb_records
    panel = panel_records[-1]
    assert panel["total_cost_micros"] > 0
    assert panel["request_count"] >= 1
    assert any(p.get("base_url") == proxy.base_url and p.get("cost_micros", 0) > 0 for p in panel["per_proxy"])

    costs = CliRunner().invoke(main, ["proxy", "costs", proxy.proxy_id, "--period", "today", "--json"])
    assert costs.exit_code == 0, costs.output
    summary = json.loads(costs.output)
    assert summary["by_verb"]["panel"]["cost_micros"] > 0
    assert summary["by_verb"]["panel"]["request_count"] >= 1
