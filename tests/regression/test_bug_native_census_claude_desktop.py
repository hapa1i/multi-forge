"""Regression: the Claude purge census treated Claude Desktop as a Claude Code client.

Bug: native_census_claude_desktop.
Root cause: the census lowercased executable names, so the Electron chat app
(``Claude.app/Contents/MacOS/Claude``) and its ``Claude Helper`` processes
matched ``claude``. Purge and incognito cleanup refused whenever Desktop was
open. Tokenizing unquoted ``ps`` argv also split Desktop's bundled Claude Code
path at ``Application Support``.

Fix: classify the census text case-sensitively by a ``claude`` word or path
component plus known Claude Code install markers. Desktop's bundled Claude Code
still counts as a client; the chat app and helpers do not.

Affected: src/forge/session/purge_native.py
"""

from __future__ import annotations

import subprocess

import pytest

from forge.session import purge_native as native

pytestmark = pytest.mark.regression

_DESKTOP = "/Applications/Claude.app/Contents"
_BUNDLED = "/Users/u/Library/Application Support/Claude/claude-code/2.1.304/ab12/claude.app/Contents/MacOS/claude"


def _census(monkeypatch: pytest.MonkeyPatch, line: str) -> tuple[str, ...]:
    result = subprocess.CompletedProcess([], 0, line + "\n", "")
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: result)
    return native.check_native_inactivity("claude")


@pytest.mark.parametrize(
    "line",
    [
        f"1715 /Applications/Cl {_DESKTOP}/MacOS/Claude",
        f"1724 /Applications/Cl {_DESKTOP}/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper --type=gpu-process"
        " --user-data-dir=/Users/u/Library/Application Support/Claude",
        f"1757 /Applications/Cl {_DESKTOP}/Frameworks/Claude Helper (Renderer).app/Contents/MacOS/Claude Helper"
        " (Renderer) --type=renderer",
        f"1773 /Applications/Cl {_DESKTOP}/Helpers/disclaimer --pgroup -- /opt/homebrew/bin/npx -y mcp-server",
        "4242 python python -m pytest tests/test_claude.py",
    ],
)
def test_desktop_app_and_helpers_are_not_claude_code(monkeypatch: pytest.MonkeyPatch, line: str) -> None:
    assert _census(monkeypatch, line) == ()


@pytest.mark.parametrize(
    "line",
    [
        "96639 claude           claude --mcp-config=/Users/u/.claude/mcp.json",
        "96640 2.1.304          claude --resume",
        "96641 /Users/u/.local/ /Users/u/.local/share/claude/versions/2.1.304 --resume",
        f"96642 /Users/u/Library {_BUNDLED} --output-format stream-json",
        "96643 node             node /usr/local/lib/node_modules/@anthropic-ai/claude-code/cli.js",
        "96644 node             node /opt/tools/claude/cli.js -p hi",
    ],
)
def test_claude_code_clients_still_block_purge(monkeypatch: pytest.MonkeyPatch, line: str) -> None:
    refusals = _census(monkeypatch, line)
    assert refusals and line.split()[0] in refusals[0]
