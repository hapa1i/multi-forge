"""Container lifecycle management for sidecar Claude Code sessions.

Bundles proxy + Claude Code in a Docker container. The key function
`run_sidecar_session()` is the container equivalent of `invoke_claude()`
— it runs interactively with inherited stdin/stdout/stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from forge.core.paths import get_forge_home
from forge.core.reactive.env import (
    CLAUDE_CODE_ATTRIBUTION_HEADER_VAR,
    apply_attribution_header_policy,
    new_root_run_identity,
)
from forge.sidecar.docker import _docker_name_filter

# In-container Forge home, pinned via FORGE_HOME so audit/cost/config resolution is
# deterministic. The sidecar keeps everything under /root (root's home: the
# entrypoint writes /root/.claude*, the standard mounts target /root/.claude, and the
# audit/cost/config mounts target /root/.forge).
#
# Under the Linux `--user uid:gid` mapping the process is a non-root uid with no
# passwd entry, so two things are needed (both also no-ops for the macOS root run):
# HOME=/root is set explicitly (Docker otherwise leaves HOME=/ for such a uid), and
# Dockerfile.sidecar runs `chmod 0777 /root` so the mapped uid can traverse/write
# /root and its mounted children. Safe for an ephemeral single-session --rm sandbox.
_SIDECAR_FORGE_HOME = "/root/.forge"
_SIDECAR_HOME = "/root"
_SIDECAR_PROXY_BASE_URL = "http://localhost:8085"


class ContainerExistsError(RuntimeError):
    """Raised when a container with the given name already exists."""

    def __init__(self, container_name: str) -> None:
        self.container_name = container_name
        super().__init__(f"Container '{container_name}' already exists. " f"Remove with: docker rm -f {container_name}")


def get_container_id(container_name: str) -> str | None:
    """Get container ID by name (for running containers only)."""
    result = subprocess.run(
        ["docker", "ps", "-q", "-f", _docker_name_filter(container_name)],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None


def container_exists(container_name: str) -> bool:
    """Check if a container exists by name (running OR stopped).

    Uses `docker ps -a` to detect ALL containers, including stopped/exited ones.
    """
    result = subprocess.run(
        ["docker", "ps", "-aq", "-f", _docker_name_filter(container_name)],
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def run_sidecar_session(
    *,
    image: str,
    template: str,
    session_name: str,
    project_dir: Path,
    proxy_id: str | None = None,
    extra_mounts: list[tuple[str, str, str]] | None = None,
    context_limit: int = 200000,
    env_vars: dict[str, str] | None = None,
    claude_args: list[str] | None = None,
) -> int:
    """Run Claude + proxy in a Docker container. Returns exit code.

    Container lifecycle = Session lifecycle:
    - Container starts when this function is called
    - Container exits when Claude exits
    - Container auto-cleaned via --rm flag

    When ``proxy_id`` is set the sidecar becomes a real always-on audit path: the
    in-container proxy starts under that proxy id (loading the per-proxy
    intercept/audit overlay), and audit logs persist on the host. Template-only
    sidecars (``proxy_id=None``) keep the plain ``--template`` behavior.
    """
    container_name = f"forge-{session_name}"

    # Collision guard: detect both running AND stopped containers
    if container_exists(container_name):
        raise ContainerExistsError(container_name)

    # Fail fast on the host: a proxy id with no proxy.yaml would start the container
    # only to abort at proxy health-check (the in-container init_config can't load it).
    if proxy_id is not None:
        proxy_config = get_forge_home() / "proxies" / proxy_id / "proxy.yaml"
        if not proxy_config.is_file():
            raise FileNotFoundError(
                f"Proxy '{proxy_id}' has no config at {proxy_config}. "
                f"Create it with 'forge proxy create' or launch template-only (without --proxy)."
            )

    # The sidecar is a run-tree root (an interactive session in a container), so it
    # mints a fresh identity with no parent — host env inheritance does not cross the
    # container boundary, and a sidecar session begins its own run tree.
    run_identity = new_root_run_identity()
    attribution_env = _sidecar_attribution_header_env()

    cmd = [
        "docker",
        "run",
        "-it",
        "--rm",
        "--name",
        container_name,
        "-v",
        f"{project_dir}:/workspace",
        "-e",
        f"FORGE_TEMPLATE={template}",
        "-e",
        f"CLAUDE_CODE_AUTO_COMPACT_WINDOW={context_limit}",
        "-e",
        f"{CLAUDE_CODE_ATTRIBUTION_HEADER_VAR}={attribution_env[CLAUDE_CODE_ATTRIBUTION_HEADER_VAR]}",
        "-e",
        f"FORGE_SESSION={session_name}",
        "-e",
        "FORGE_SIDECAR=1",
        "-e",
        "FORGE_LAUNCH_MODE=sidecar",
        "-e",
        f"FORGE_RUN_ID={run_identity.run_id}",
        "-e",
        f"FORGE_ROOT_RUN_ID={run_identity.root_run_id}",
        # Deterministic home: a `--user` uid with no passwd entry would get HOME=/,
        # breaking claude (~/.claude.json) and forge (~/.forge) resolution.
        "-e",
        f"HOME={_SIDECAR_HOME}",
        "-w",
        "/workspace",
    ]

    # Audit plumbing: proxy id + FORGE_HOME so the in-container server starts under
    # the proxy id (entrypoint.sh passes --proxy-id when FORGE_PROXY_ID is set) and
    # resolves ~/.forge to the mounted location.
    if proxy_id is not None:
        cmd.extend(["-e", f"FORGE_PROXY_ID={proxy_id}", "-e", f"FORGE_HOME={_SIDECAR_FORGE_HOME}"])

    if sys.platform == "linux":
        uid, gid = os.getuid(), os.getgid()
        cmd.extend(["--user", f"{uid}:{gid}"])

    if proxy_id is not None:
        for host_path, container_path, mode in _ensure_audit_plumbing_mounts(proxy_id):
            cmd.extend(["-v", f"{host_path}:{container_path}:{mode}"])

    if extra_mounts:
        for host_path, container_path, mode in extra_mounts:
            cmd.extend(["-v", f"{host_path}:{container_path}:{mode}"])

    # Write env vars to temp file instead of CLI args to avoid
    # leaking secrets via `ps aux` (CR-022). Cleanup in finally.
    env_file_path: str | None = None
    try:
        if env_vars:
            fd, env_file_path = tempfile.mkstemp(prefix=".forge-env-", suffix=".env")
            with os.fdopen(fd, "w") as f:
                for k, v in env_vars.items():
                    f.write(f"{k}={v}\n")
            os.chmod(env_file_path, 0o600)
            cmd.extend(["--env-file", env_file_path])

        cmd.append(image)
        if claude_args:
            cmd.extend(claude_args)

        result = subprocess.run(cmd)
        return result.returncode
    finally:
        if env_file_path:
            try:
                os.unlink(env_file_path)
            except OSError:
                pass


def _ensure_audit_plumbing_mounts(proxy_id: str) -> list[tuple[str, str, str]]:
    """Build the sidecar audit-plumbing mounts, creating host state dirs as needed.

    Side effect: creates the host audit/, costs/, and usage/ dirs (Docker bind sources
    must exist before `docker run`). Narrow mounts (NOT all of ~/.forge, preserving the
    design.md §7 isolation rationale):
    - per-proxy config dir read-only, so the in-container server reads the proxy.yaml
      intercept/audit overlay.
    - host audit/, costs/, and usage/ read-write, so the proxy's audit records and cost
      history, spend-cap accounting, and the attribution ledger persist where the host
      reads them (`forge proxy audit|costs`, `forge activity`, the session-end summary)
      instead of dying with the --rm container. Each would otherwise be lost silently:
      caps bootstrap from cost history, so an unmounted costs/ resets daily/monthly caps
      every launch; and in sidecar mode the in-container supervisor + workflow verbs are
      the *only* writers of their usage events, so an unmounted usage/ makes the whole
      session invisible to `forge activity`.
    """
    forge_home = get_forge_home()
    mounts: list[tuple[str, str, str]] = [
        (str(forge_home / "proxies" / proxy_id), f"{_SIDECAR_FORGE_HOME}/proxies/{proxy_id}", "ro"),
    ]

    for subdir in ("audit", "costs", "usage"):
        host_dir = forge_home / subdir
        host_dir.mkdir(parents=True, exist_ok=True)
        mounts.append((str(host_dir), f"{_SIDECAR_FORGE_HOME}/{subdir}", "rw"))

    return mounts


def _sidecar_attribution_header_env() -> dict[str, str]:
    """Derive Claude attribution-header policy for the in-container proxy route.

    The sidecar entrypoint sets ``ANTHROPIC_BASE_URL`` after its local proxy is
    healthy; the host launcher owns the classifier/cache policy decision and
    passes the resulting env var into the container so shell and Python cannot
    drift.
    """
    env = {"ANTHROPIC_BASE_URL": _SIDECAR_PROXY_BASE_URL}
    apply_attribution_header_policy(env)
    return env


def exec_in_container(container_name: str, command: list[str]) -> int:
    """Execute interactive command in running container."""
    cmd = ["docker", "exec", "-it", container_name, *command]
    result = subprocess.run(cmd)
    return result.returncode


def parse_mounts(mount_specs: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """Parse --mount flag specifications into (host, container, mode) tuples.

    Format: "host_path:container_path[:ro|rw]"
    Default mode is "rw" if not specified.
    """
    mounts = []
    for spec in mount_specs:
        parts = spec.split(":")

        if len(parts) < 2:
            raise ValueError(f"Invalid mount specification: {spec}. Expected 'host:container[:ro|rw]'")

        host_path = parts[0]
        container_path = parts[1]
        mode = parts[2] if len(parts) > 2 else "rw"

        if mode not in ("ro", "rw"):
            raise ValueError(f"Invalid mount mode: {mode}. Must be 'ro' or 'rw'")

        host_path = os.path.expanduser(host_path)
        mounts.append((host_path, container_path, mode))

    return mounts
