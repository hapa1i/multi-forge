"""Print the fixed native-layout probe proposal; never dispatch a native client."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CLAUDE_VERSION = "2.1.245"
MODEL = "claude-haiku-4-5-20251001"
PROMPT = (
    "Invoke the purge-probe subagent exactly once with this prompt: Reply with exactly PURGE_CHILD_OK. "
    "After it returns, reply with exactly PURGE_PARENT_OK. Do not inspect files, run shell commands, "
    "use another agent, or retry a failed operation."
)


def manifest() -> dict[str, Any]:
    """Return reviewable arguments, fixed payloads and bounds without reading auth."""
    agents = {
        "purge-probe": {
            "description": "Return the fixed synthetic native-layout probe acknowledgement.",
            "prompt": "Reply with exactly PURGE_CHILD_OK. Do not invoke tools or delegate.",
            "tools": [],
            "model": "haiku",
        }
    }
    command = [
        "claude",
        "--print",
        "--model",
        MODEL,
        "--max-turns",
        "2",
        "--max-budget-usd",
        "0.10",
        "--output-format",
        "json",
        "--tools",
        "Agent,Task",
        "--allowedTools",
        "Agent,Task",
        "--agents",
        json.dumps(agents, separators=(",", ":")),
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--disable-slash-commands",
        PROMPT,
    ]
    return {
        "schema_version": 1,
        "status": "proposal_only_not_authorized_or_executed",
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runtime": {"claude": CLAUDE_VERSION, "codex": "no new invocation"},
        "image": "forge-native-purge:claude-2.1.245-codex-0.149.1",
        "build_argv": [
            "docker",
            "build",
            "-f",
            "docker/Dockerfile.forge",
            "--build-arg",
            "CLAUDE_VERSION=2.1.245",
            "--build-arg",
            "CODEX_VERSION=0.149.1",
            "-t",
            "forge-native-purge:claude-2.1.245-codex-0.149.1",
            ".",
        ],
        "container_name": "forge-native-purge-20261020",
        "container_workspace": "/probe/workspace",
        "container_environment": {
            "HOME": "/probe/home",
            "CLAUDE_HOME": "/probe/home/.claude",
            "CLAUDE_CONFIG_DIR": "/probe/home/.claude",
            "CODEX_HOME": "/probe/home/.codex",
            "FORGE_HOME": "/probe/home/.forge",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "512",
            "MAX_THINKING_TOKENS": "0",
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
        },
        "auth": "Forward ANTHROPIC_API_KEY by environment name only; do not mount host homes or copy login stores",
        "native_argv": command,
        "max_native_invocations": 1,
        "max_parent_agentic_turns": 2,
        "max_requested_subagents": 1,
        "max_output_tokens_per_completion": 512,
        "wall_seconds": 90,
        "cli_budget_usd": 0.10,
        "limits": "The CLI cap and timeout are operational bounds, not a guaranteed HTTP-request count or invoice cap.",
        "preflight": [
            "Assert actual claude --version is exactly 2.1.245 before any inference",
            "Record image ID and native executable SHA-256",
            "Refuse missing ANTHROPIC_API_KEY",
        ],
        "observations": [
            "Record exact synthetic native files, JSONL metadata, SHA-256 and runtime PID census",
            "Observe census refusal while the native process lives and admission after it exits",
            "Inventory original and agent files; copy source bytes for offline relocation/rewind cases",
            "Assert delete preserves bytes, purge removes only preview paths, unrelated sentinel survives",
        ],
        "no_retry": True,
        "export": "Only synthetic transcripts, redacted metadata, arguments, image/binary identity and assertions",
        "cleanup": "Stop/remove only the exact named disposable container after exporting its probe evidence",
    }


if __name__ == "__main__":
    print(json.dumps(manifest(), indent=2))
