"""One immutable approved-plan read shared by the checker, frontier, and audit."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from forge.policy.types import ActionContext
from forge.session.models import SupervisorConfig


@dataclass(frozen=True)
class PlanSnapshot:
    path: str | None
    text: str | None
    digest: str | None

    @property
    def fingerprint(self) -> str:
        return f"{self.path}:{self.digest or 'unavailable'}"


def read_plan(config: SupervisorConfig) -> PlanSnapshot:
    """Read UTF-8 bytes once, preserving the exact text whose digest is recorded."""
    if not config.plan_override_path:
        return PlanSnapshot(None, None, None)
    path = Path(config.plan_override_path)
    if not path.is_absolute() and config.forge_root:
        path = Path(config.forge_root) / path
    try:
        if not path.is_file():
            return PlanSnapshot(str(path), None, None)
        if config.review_trigger == "stop":
            # A Stop hook has a fixed wall-clock and prompt budget. Never block
            # on a FIFO/device or silently treat a truncated plan as approved.
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 64_000:
                    return PlanSnapshot(str(path), None, None)
                raw = stream.read(64_001)
                if len(raw) > 64_000:
                    return PlanSnapshot(str(path), None, None)
        else:
            raw = path.read_bytes()
        text = raw.decode("utf-8")
        if text.strip():
            return PlanSnapshot(str(path), text, hashlib.sha256(raw).hexdigest())
    except (OSError, UnicodeError):
        pass
    return PlanSnapshot(str(path), None, None)


class ReviewSource:
    """Hand one checker's snapshot to its resolver without retaining it across actions.

    The hook constructs one instance for both policies. A checker always starts a new
    read, including on cache hits; the frontier consumes it only for that exact action.
    Standalone frontier evaluations perform their own fresh read.
    """

    def __init__(self) -> None:
        self._pending: tuple[ActionContext, PlanSnapshot] | None = None

    def begin(self, config: SupervisorConfig, context: ActionContext) -> PlanSnapshot:
        snapshot = read_plan(config)
        self._pending = (context, snapshot)
        return snapshot

    def take(self, config: SupervisorConfig, context: ActionContext) -> PlanSnapshot:
        pending, self._pending = self._pending, None
        return pending[1] if pending is not None and pending[0] is context else read_plan(config)
