"""Fixtures for Docker-based integration tests.

Re-exports shared Docker fixtures for pytest discovery in this subtree,
plus additional fixtures for session lifecycle tests and hook tests.
"""

from __future__ import annotations

import json
import os
import shlex
from typing import Generator

import pytest

from forge.session.direct_model import direct_model_env
from tests.fixtures.docker import (
    ContainerLike,
    clean_workspace,
    docker_available,
    forge_test_image,
    local_claude_available,
    synced_container,
)

__all__ = [
    "ContainerLike",
    "clean_workspace",
    "docker_available",
    "forge_test_image",
    "forge_workspace",
    "local_claude_available",
    "policy_workspace",
    "precompact_workspace",
    "relocate_and_resume",
    "run_claude_print",
    "setup_real_claude",
    "synced_container",
]


# ---------------------------------------------------------------------------
# Shared helpers for tests that use real Claude Code (not the mock binary).
# ---------------------------------------------------------------------------


def setup_real_claude(
    workspace: ContainerLike,
    *,
    session_name: str = "real-claude-test",
    root: str = "/workspace",
) -> None:
    """Restore real Claude binary and set up a session for testing.

    1. Restores real claude binary (forge_workspace replaces it with mock)
    2. Enables forge hooks (required for hooks to fire)
    3. Creates a named session with --no-launch

    Args:
        root: Project dir to set up (defaults to /workspace). Parameterized so
            native-relocate can set up a parent in a non-default CWD.

    SECURITY: API key is passed via environment, NOT in command strings.
    """
    result = workspace.exec("""
        if [ -f /usr/local/bin/claude-real ]; then
            mv /usr/local/bin/claude-real /usr/local/bin/claude
        fi
        """)
    if result.returncode != 0:
        pytest.fail(f"Failed to restore claude: {result.stderr}")

    root_q = shlex.quote(root)
    result = workspace.exec(f"mkdir -p {root_q}/.claude {root_q}/.forge")
    if result.returncode != 0:
        pytest.fail(f"Failed to create .claude/.forge directories: {result.stderr}")

    result = workspace.exec(f"cd {root_q} && forge hook enable")
    if result.returncode != 0:
        pytest.fail(f"Failed to enable hooks: {result.stderr}")

    result = workspace.exec(f"cd {root_q} && forge session start --no-launch {shlex.quote(session_name)}")
    if result.returncode != 0:
        pytest.fail(f"Failed to create session: {result.stderr}")


def run_claude_print(
    workspace: ContainerLike,
    prompt: str,
    *,
    session_name: str | None = "real-claude-test",
    resume_id: str | None = None,
    fork_session: bool = False,
    timeout: int = 60,
    cwd: str = "/workspace",
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Run ``claude --print`` with the given prompt.

    Args:
        workspace: Container to execute in.
        prompt: Prompt to send to Claude. Written to a temp file and passed via
            ``"$(cat ...)"`` -- never interpolated into the command string, so
            quotes/``$``/backticks/newlines are safe.
        session_name: ``FORGE_SESSION`` value for hook dispatch. ``None`` leaves
            ``FORGE_SESSION`` UNSET so no Forge hooks fire -- used by the
            native-relocate child resume so the gate measures Claude, not hooks.
        resume_id: If set, pass ``--resume <id>`` to Claude.
        fork_session: If True, pass ``--fork-session`` (use with resume_id).
        timeout: Timeout in seconds.
        cwd: Working directory for the claude invocation.
        extra_env: Extra environment variables (e.g. model pin, MAX_THINKING_TOKENS).
        extra_args: Extra claude flags (e.g. ``--dangerously-skip-permissions``).

    Returns:
        Tuple of (exit_code, stdout, stderr).

    SECURITY: API key and prompt are written to temp files via single-quoted
    heredocs (no shell expansion) and never appear in the command string.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")

    workspace.exec(
        "printf '%s' > /tmp/.anthropic_key && chmod 600 /tmp/.anthropic_key",
        timeout=5,
    )
    key_result = workspace.exec(f"cat > /tmp/.anthropic_key << 'KEY_EOF'\n{api_key}\nKEY_EOF")
    if key_result.returncode != 0:
        pytest.fail("Failed to write API key")
    prompt_result = workspace.exec(f"cat > /tmp/.forge_prompt << 'FORGE_PROMPT_EOF'\n{prompt}\nFORGE_PROMPT_EOF")
    if prompt_result.returncode != 0:
        pytest.fail("Failed to write prompt")

    flags = ["--print"]
    if resume_id:
        flags += ["--resume", shlex.quote(resume_id)]
    if fork_session:
        flags.append("--fork-session")
    if extra_args:
        flags += [shlex.quote(arg) for arg in extra_args]
    flag_str = " ".join(flags)

    exports = ["export ANTHROPIC_API_KEY=$(cat /tmp/.anthropic_key)"]
    if session_name is not None:
        exports.append(f"export FORGE_SESSION={shlex.quote(session_name)}")
    for key, value in (extra_env or {}).items():
        exports.append(f"export {key}={shlex.quote(value)}")
    export_block = "\n".join(exports)

    try:
        result = workspace.exec(
            f"""
            {export_block}
            cd {shlex.quote(cwd)} && timeout {timeout} claude {flag_str} "$(cat /tmp/.forge_prompt)"
            """,
            timeout=timeout + 10,
        )
        return result.returncode, result.stdout, result.stderr
    finally:
        workspace.exec("rm -f /tmp/.anthropic_key /tmp/.forge_prompt")


_CONTAINER_PY = "/forge/.venv/bin/python"  # editable forge venv inside the container
_HELPER_PATH = "/tmp/_forge_relocate_helper.py"

# Runs INSIDE the container against the forge venv. Subcommand dispatch on argv[1]
# keeps the in-container path math / hashing in one file (written once via a
# single-quoted heredoc, so nothing here is shell-expanded). chr(34) builds the
# double-quote needles to avoid nested-quote escaping.
_HELPER_SRC = """\
import hashlib
import json
import sys

from forge.session.claude.paths import get_project_encoded_dir, get_transcript_path
from forge.session.claude.relocate import relocate_transcript

_Q = chr(34)

cmd = sys.argv[1]
if cmd == "parent-uuid":
    d = get_project_encoded_dir(sys.argv[2])
    js = sorted(
        (p for p in d.glob("*.jsonl") if not p.name.startswith("agent-")),
        key=lambda p: p.stat().st_mtime,
    )
    print(js[-1].stem if js else "")
elif cmd == "parent-meta":
    p = get_transcript_path(sys.argv[2], sys.argv[3])
    signed = False
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        msg = rec.get("message", rec) if isinstance(rec, dict) else {}
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking" and block.get("signature"):
                signed = True
            elif block.get("type") == "redacted_thinking" and block.get("data"):
                signed = True
            if signed:
                break
        if signed:
            break
    print(json.dumps({"path": str(p), "has_sig": signed}))
elif cmd == "relocate":
    res = relocate_transcript(
        session_id=sys.argv[3],
        source_project_root=sys.argv[2],
        dest_project_root=sys.argv[4],
    )
    print(str(res.dest_path))
elif cmd == "snapshot":
    d = get_project_encoded_dir(sys.argv[2])
    stems = sorted(p.name for p in d.glob("*.jsonl"))
    with open(sys.argv[3], "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print(json.dumps({"stems": stems, "sha": digest}))
elif cmd == "inspect":
    d = get_project_encoded_dir(sys.argv[2])
    before = set(json.loads(sys.argv[3]))
    now = sorted(p.name for p in d.glob("*.jsonl"))
    new = [n for n in now if n not in before and not n.startswith("agent-")]
    needle = _Q + "tool_use" + _Q
    counts = [(d / n).read_text(errors="replace").count(needle) for n in new]
    with open(sys.argv[4], "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    print(json.dumps({"new": new, "tool_use": max(counts, default=0), "sha": digest}))
else:
    raise SystemExit("unknown cmd: " + cmd)
"""


def _write_relocate_helper(workspace: ContainerLike) -> None:
    result = workspace.exec(f"cat > {_HELPER_PATH} << 'RELOCATE_PYEOF'\n{_HELPER_SRC}\nRELOCATE_PYEOF")
    if result.returncode != 0:
        pytest.fail(f"Failed to write relocate helper: {result.stderr}")


def _relocate_helper(workspace: ContainerLike, *args: str, timeout: int = 30):
    """Invoke a subcommand of the in-container relocate helper."""
    quoted = " ".join(shlex.quote(str(a)) for a in args)
    return workspace.exec(f"{_CONTAINER_PY} {_HELPER_PATH} {quoted}", timeout=timeout)


def relocate_and_resume(
    workspace: ContainerLike,
    *,
    parent_prompt: str,
    child_prompt: str,
    parent_root: str = "/workspace",
    child_root: str = "/workspace-b",
    parent_session: str = "relocate-parent",
    model: str = "claude-opus-4-6",
    thinking_tokens: int = 2048,
    timeout: int = 180,
) -> dict[str, object]:
    """Drive the native-relocate contract: parent run -> relocate -> child resume.

    Returns raw signals only; the TEST owns all pass/fail decisions. The parent
    uses the proven setup_real_claude path (its hooks are harmless -- the gate is
    judged from Claude's project dir). The child resumes hook-free
    (``FORGE_SESSION`` unset) from a real git worktree, so the result reflects
    Claude's native cross-CWD resume rather than Forge plumbing.

    Keys: parent_uuid, parent_jsonl, parent_has_signature, reloc_dest,
    reloc_sha_before, reloc_sha_after, child_exit, child_stdout, child_stderr,
    new_fork_jsonls, fork_tool_use_count, container_claude_version.
    """
    pin = {**direct_model_env(model), "MAX_THINKING_TOKENS": str(thinking_tokens)}
    _write_relocate_helper(workspace)

    # No --dangerously-skip-permissions: Claude Code rejects it under root (the
    # test container runs as root), and read-only tools (Read) still execute in
    # --print mode without it (verified against forge-claude-test:2.1.158).
    # 1. Parent session + run (signed-thinking + tool-use turn).
    setup_real_claude(workspace, session_name=parent_session, root=parent_root)
    workspace.exec(f"printf 'PARENT_MARKER' > {shlex.quote(parent_root + '/RELOCATE_FIXTURE.txt')}")
    parent_exit, _parent_out, parent_err = run_claude_print(
        workspace,
        parent_prompt,
        session_name=parent_session,
        cwd=parent_root,
        extra_env=pin,
        timeout=timeout,
    )

    # 2. Parent UUID + signed-thinking check, read from Claude's project dir.
    parent_uuid = _relocate_helper(workspace, "parent-uuid", parent_root).stdout.strip()
    if not parent_uuid:
        raise AssertionError(
            f"No parent session transcript under {parent_root}'s encoded dir "
            f"(parent claude exit={parent_exit}); stderr: {parent_err[:600]!r}"
        )
    meta = json.loads(_relocate_helper(workspace, "parent-meta", parent_root, parent_uuid).stdout.strip())

    # 3. Real git worktree for the child CWD (faithful fork --worktree topology),
    #    minimal .claude for Claude trust, no forge hooks / no FORGE_SESSION.
    wt = workspace.exec(f"cd {shlex.quote(parent_root)} && git worktree add --detach {shlex.quote(child_root)}")
    if wt.returncode != 0:
        raise AssertionError(f"git worktree add failed: {wt.stderr}")
    workspace.exec(f"mkdir -p {shlex.quote(child_root + '/.claude')}")
    workspace.exec(f"printf 'CHILD_MARKER' > {shlex.quote(child_root + '/RELOCATE_FIXTURE_CHILD.txt')}")

    # 4. Relocate via the REAL Stage A primitive, inside the container.
    reloc = _relocate_helper(workspace, "relocate", parent_root, parent_uuid, child_root)
    if reloc.returncode != 0:
        raise AssertionError(f"relocate_transcript failed in container: {reloc.stderr}")
    reloc_dest = reloc.stdout.strip()

    # 5. Snapshot child dir + relocated-parent hash before resume.
    before = json.loads(_relocate_helper(workspace, "snapshot", child_root, reloc_dest).stdout.strip())

    # 6. Hook-free child resume across the CWD boundary.
    child_exit, child_out, child_err = run_claude_print(
        workspace,
        child_prompt,
        session_name=None,
        cwd=child_root,
        resume_id=parent_uuid,
        fork_session=True,
        extra_env=pin,
        timeout=timeout,
    )

    # 7. Inspect after: new fork JSONLs, their tool_use count, relocated-parent hash.
    after = json.loads(
        _relocate_helper(workspace, "inspect", child_root, json.dumps(before["stems"]), reloc_dest).stdout.strip()
    )
    version = workspace.exec("claude --version").stdout.strip()

    return {
        "parent_uuid": parent_uuid,
        "parent_jsonl": meta["path"],
        "parent_has_signature": bool(meta["has_sig"]),
        "reloc_dest": reloc_dest,
        "reloc_sha_before": before["sha"],
        "reloc_sha_after": after["sha"],
        "child_exit": child_exit,
        "child_stdout": child_out,
        "child_stderr": child_err,
        "new_fork_jsonls": after["new"],
        "fork_tool_use_count": int(after["tool_use"]),
        "container_claude_version": version,
    }


@pytest.fixture
def forge_workspace(
    clean_workspace: ContainerLike,
) -> Generator[ContainerLike, None, None]:
    """Per-test workspace with forge in PATH, mock claude, and clean state.

    Creates:
    - Symlink /usr/local/bin/forge -> /forge/.venv/bin/forge
    - Mock claude binary that logs and exits 0
    - Clean ~/.forge/ and ~/.claude/ for test isolation

    This allows testing forge CLI commands that invoke Claude without
    actually launching Claude Code.
    """
    result = clean_workspace.exec("""
        # Clean global forge state (session index, active pointer)
        rm -rf ~/.forge ~/.claude

        # Symlink forge to PATH so it's available from any directory
        ln -sf /forge/.venv/bin/forge /usr/local/bin/forge 2>/dev/null || true

        # Create mock claude binary
        cat > /usr/local/bin/claude-mock << 'SCRIPT'
#!/bin/bash
# Mock claude binary for testing
# Returns a parseable version for installer/version checks,
# then logs normal invocations and exits 0.
if [ "${1:-}" = "--version" ]; then
    echo "99.99.99 (Claude Code)"
    exit 0
fi

echo "$(date -Iseconds) claude $*" >> /tmp/claude_invocations.log
exit 0
SCRIPT
        chmod +x /usr/local/bin/claude-mock

        # Backup real claude and replace with mock
        if [ -f /usr/local/bin/claude ]; then
            mv /usr/local/bin/claude /usr/local/bin/claude-real
        fi
        ln -sf /usr/local/bin/claude-mock /usr/local/bin/claude

        # Clear log file
        > /tmp/claude_invocations.log

        # Rule 1: create .forge/ and .claude/ anchors so session start works
        mkdir -p /workspace/.forge /workspace/.claude
        """)
    if result.returncode != 0:
        pytest.fail(f"Failed to set up forge_workspace: {result.stderr}")

    yield clean_workspace

    # Restore real claude after test
    clean_workspace.exec("""
        if [ -f /usr/local/bin/claude-real ]; then
            mv /usr/local/bin/claude-real /usr/local/bin/claude
        fi
        """)


@pytest.fixture
def policy_workspace(
    forge_workspace: ContainerLike,
) -> Generator[ContainerLike, None, None]:
    """Per-test workspace with TDD policy enabled.

    Builds on forge_workspace by:
    1. Creating a session with `forge session start`
    2. Updating manifest with TDD policy config

    The hook tests can then invoke `forge hook policy-check` and verify
    TDD enforcement behavior.
    """
    # Create session (forge_workspace already creates .forge/ + .claude/)
    result = forge_workspace.exec("cd /workspace && forge session start policy-test")
    if result.returncode != 0:
        pytest.fail(f"Session start failed: {result.stderr}")

    # Read manifest and add policy config (per-session directory layout)
    manifest_path = "/workspace/.forge/sessions/policy-test/forge.session.json"
    manifest_result = forge_workspace.exec(f"cat {manifest_path}")
    if manifest_result.returncode != 0:
        pytest.fail(f"Failed to read manifest: {manifest_result.stderr}")

    manifest = json.loads(manifest_result.stdout)
    manifest["intent"]["policy"] = {
        "enabled": True,
        "bundles": ["tdd"],
        "fail_mode": "open",
    }

    # Write updated manifest
    manifest_json = json.dumps(manifest, indent=2)
    write_result = forge_workspace.exec(f"cat > {manifest_path} << 'MANIFEST_EOF'\n{manifest_json}\nMANIFEST_EOF")
    if write_result.returncode != 0:
        pytest.fail(f"Failed to write manifest: {write_result.stderr}")

    yield forge_workspace


@pytest.fixture
def precompact_workspace(
    forge_workspace: ContainerLike,
) -> Generator[ContainerLike, None, None]:
    """Per-test workspace with a session for pre-compact transcript capture testing.

    Builds on forge_workspace by creating a session. No mock server needed —
    pre-compact captures transcripts, it doesn't query the proxy.
    """
    # Create session (forge_workspace already creates .forge/ + .claude/)
    result = forge_workspace.exec("cd /workspace && forge session start precompact-test")
    if result.returncode != 0:
        pytest.fail(f"Session start failed: {result.stderr}")

    yield forge_workspace
