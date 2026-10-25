"""Native delegation and memory controls for explicitly selected Forge workers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerNativeProfile:
    """Apply fixed controls after caller overrides, without changing managed roots."""

    runtime: str
    arguments: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()

    def apply(self, argv: list[str], env: dict[str, str]) -> None:
        """Finalize the durable base request, including any format-retry path."""
        argv.extend(self.arguments)
        env.update(self.environment)
        _log.debug(
            "Worker native controls: runtime=%s arguments=%s environment=%s",
            self.runtime,
            self.arguments,
            dict(self.environment),
        )


_CLAUDE_WORKER_ENV = (
    ("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "0"),
    ("CLAUDE_CODE_FORK_SUBAGENT", "0"),
    ("CLAUDE_CODE_DISABLE_WORKFLOWS", "1"),
    ("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1"),
)

CLAUDE_WORKER_PROFILE = WorkerNativeProfile(
    runtime="claude_code",
    arguments=(
        "--disallowedTools",
        "Agent",
        "Workflow",
        "SendMessage",
        # A context: fork skill can spawn without admitting the Agent tool.
        "--disable-slash-commands",
        # Claude settings.env can override the process environment.
        "--settings",
        json.dumps({"env": dict(_CLAUDE_WORKER_ENV)}, sort_keys=True),
    ),
    environment=_CLAUDE_WORKER_ENV,
)

CODEX_WORKER_PROFILE = WorkerNativeProfile(
    runtime="codex",
    arguments=(
        "-c",
        "agents.enabled=false",
        "-c",
        "memories.use_memories=false",
        "-c",
        "memories.generate_memories=false",
    ),
)
