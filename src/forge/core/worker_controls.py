"""Native delegation and memory controls for explicitly selected Forge workers."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerNativeProfile:
    """Apply fixed controls after caller overrides, without changing managed roots."""

    runtime: str
    arguments: tuple[str, ...]
    environment: tuple[tuple[str, str], ...] = ()
    settings: dict[str, object] = field(default_factory=dict)

    def apply(self, argv: list[str], env: dict[str, str], *, extra_settings: dict[str, object] | None = None) -> None:
        """Finalize the durable base request, including any format-retry path."""
        argv.extend(arg for arg in self.arguments if arg != "--disable-slash-commands" or arg not in argv)
        env.update(self.environment)
        settings = deepcopy(extra_settings or {})
        # Fixed worker controls retain precedence over projected caller settings.
        settings.update(deepcopy(self.settings))
        if settings:
            argv.extend(["--settings", json.dumps(settings, sort_keys=True)])
        _log.debug(
            "Worker native controls: runtime=%s arguments=%s environment=%s settings=%s",
            self.runtime,
            self.arguments,
            dict(self.environment),
            self.settings,
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
    ),
    environment=_CLAUDE_WORKER_ENV,
    # Claude settings.env can override the process environment.
    settings={"env": dict(_CLAUDE_WORKER_ENV)},
)

CODEX_WORKER_PROFILE = WorkerNativeProfile(
    runtime="codex",
    arguments=(
        "--disable",
        "multi_agent",
        "-c",
        "agents.enabled=false",
        "-c",
        "memories.use_memories=false",
        "-c",
        "memories.generate_memories=false",
    ),
)
