"""Render context for the status line.

Built once per ``status_line()`` invocation and passed to every segment producer.
Expensive derivations (transcript scan, git branch, context parsing) are
``cached_property`` so they run at most once AND only if an enabled segment
actually accesses them — e.g. ``segments: [path, model]`` does no transcript
scan and no git subprocess.

Helpers come from ``forge.cli.status_line`` via module-attribute lookup at call
time (so tests can patch them, and so the import direction stays acyclic — see
the module docstring in ``registry.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

from forge.cli import status_line as sl
from forge.cli.status_line import ProxyRuntimeTruth, TranscriptStats
from forge.cli.statusline.palette import (
    Glyphs,
    Palette,
    resolve_glyphs,
    resolve_palette,
)
from forge.runtime_config import RuntimeConfig


@dataclass
class RenderContext:
    """Inputs + lazily-derived values shared across segment producers."""

    data: dict[str, Any]
    is_proxy: bool
    runtime: ProxyRuntimeTruth | None
    is_proxy_authoritative: bool
    manifest: dict[str, Any] | None
    is_session_authoritative: bool
    config: RuntimeConfig

    # Set by render_segments() to the resolved render order, so a producer can
    # see what else is active (e.g. rate_limits suppresses itself when cost
    # already shows the quota). Empty until render_segments runs.
    active_segments: set[str] = field(default_factory=set)

    # --- Cheap raw accessors (no I/O) ---

    @property
    def workspace_dir(self) -> str:
        return self.data.get("workspace", {}).get("current_dir", "")

    @property
    def raw_model_name(self) -> str:
        return self.data.get("model", {}).get("display_name", "Claude")

    @property
    def transcript_path(self) -> str:
        return self.data.get("transcript_path", "")

    @property
    def session_id(self) -> str | None:
        return self.data.get("session_id")

    @property
    def cost_data(self) -> dict[str, Any]:
        return self.data.get("cost") or {}

    @property
    def palette(self) -> Palette:
        return resolve_palette(self.config.statusline.palette)

    @property
    def glyphs(self) -> Glyphs:
        return resolve_glyphs(self.config.statusline.glyphs)

    @property
    def has_api_key(self) -> bool:
        # RAW env only. resolve_env_or_credential would fall back to the Forge
        # credential file (and honor auth_ignore_env), misclassifying an OAuth
        # session as API. The status line wants the main session's actual auth.
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    @property
    def billing_mode(self) -> str:
        """``api`` | ``subscription`` | ``ambiguous`` (declare + heuristic).

        ``auto`` resolves to ``api`` when ANTHROPIC_API_KEY is set, else
        ``ambiguous`` (we lean subscription but aren't certain).
        """
        mode = self.config.statusline.cost_mode
        if mode in ("api", "subscription"):
            return mode
        return "api" if self.has_api_key else "ambiguous"

    # --- Lazy derivations (run once, only if accessed) ---

    @cached_property
    def transcript_stats(self) -> TranscriptStats:
        return sl._cached_scan_transcript(self.transcript_path)

    @cached_property
    def git_branch(self) -> str | None:
        return sl.get_git_branch(self.workspace_dir)

    @cached_property
    def context_info(self) -> dict[str, Any] | None:
        info = sl.parse_context_from_json(self.data)
        # Proxy runtime truth overrides the context window when available.
        if self.is_proxy and self.runtime and self.runtime.active_context_window and info:
            tokens = info.get("tokens", 0)
            window = self.runtime.active_context_window
            info["context_window"] = window
            info["percent"] = min(100, int((tokens / window) * 100))
        return info

    @cached_property
    def effective_context_window(self) -> int | None:
        return sl.get_effective_context_window(self.data, self.runtime, self.context_info)
