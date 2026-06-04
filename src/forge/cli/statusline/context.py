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

from dataclasses import dataclass
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
    def cost_data(self) -> dict[str, Any]:
        return self.data.get("cost") or {}

    @property
    def palette(self) -> Palette:
        return resolve_palette(self.config.statusline.palette)

    @property
    def glyphs(self) -> Glyphs:
        return resolve_glyphs(self.config.statusline.glyphs)

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
