"""Configuration for team quality gate hooks."""

from __future__ import annotations

from dataclasses import dataclass

from forge.core.effort import validate_claude_effort


@dataclass
class TeamSupervisorConfig:
    """Configuration for team quality gate hooks.

    Lives on ``PolicyIntent.team_supervisor``. When ``None``, team hooks
    are no-ops (allow everything, fail-open).
    """

    enabled: bool = False
    tagger_model: str = "gemini/gemini-2.0-flash"
    resume_id: str | None = None
    proxy: str | None = None
    direct: bool = False
    base_url: str | None = None
    timeout_seconds: int = 45
    throttle_seconds: int = 60
    max_blocks_per_task: int = 3
    effort: str | None = None  # `claude --effort` level for the team supervisor's claude -p run; None = tier default

    def __post_init__(self) -> None:
        validate_claude_effort(self.effort)
