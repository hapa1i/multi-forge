"""Tests for sidecar launch diagnostics."""

from __future__ import annotations

from io import StringIO

from rich.console import Console

from forge.cli import session_lifecycle
from forge.core.ops.claude_session import (
    SIDECAR_RUNTIME_HOOK_WARNING,
    ClaudeSidecarLaunch,
)


def test_sidecar_launch_renders_hookless_warning_before_start(monkeypatch) -> None:
    buf = StringIO()
    monkeypatch.setattr(session_lifecycle, "console", Console(file=buf, width=120))

    session_lifecycle._render_sidecar_launch(
        ClaudeSidecarLaunch(
            image="forge-sidecar:test",
            proxy_id=None,
            warnings=(SIDECAR_RUNTIME_HOOK_WARNING,),
        )
    )

    output = buf.getvalue()
    assert "Warning:" in output
    assert "without Forge runtime hooks" in output
    assert output.index("Warning:") < output.index("Starting sidecar session")
