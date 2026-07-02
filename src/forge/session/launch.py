"""CLI-free helpers for interactive Claude session launches."""

from __future__ import annotations

import logging
from pathlib import Path

from forge.core.reactive.env import (
    FORGE_PROXY_WIRE_SHAPE_VAR,
    FORGE_SUBPROCESS_BASE_URL_VAR,
    FORGE_SUBPROCESS_PROXY_ID_VAR,
    FORGE_SUBPROCESS_PROXY_VAR,
    FORGE_SUBPROCESS_TEMPLATE_VAR,
    resolve_proxy_wire_shape,
)
from forge.session import (
    LAUNCH_MODE_HOST,
    LAUNCH_MODE_SIDECAR,
    SIDECAR_RUNTIME_BASE_URL,
    SessionState,
)

logger = logging.getLogger(__name__)


def _build_session_env(
    *,
    session_name: str,
    context_limit: int,
    template: str | None,
    base_url: str | None,
    proxy_id: str | None = None,
    fork_name: str | None = None,
    parent_session: str | None = None,
    forge_root: str | None = None,
    subprocess_proxy: str | None = None,
    sidecar: bool = False,
) -> tuple[dict[str, str], list[str]]:
    """Build Claude env vars plus explicit unsets for a session launch."""
    env_vars: dict[str, str] = {
        "FORGE_SESSION": session_name,
    }
    if forge_root:
        env_vars["FORGE_FORGE_ROOT"] = forge_root
    unset_env_vars: list[str] = []

    if base_url is None:
        # Direct mode: don't touch CLAUDE_CODE_AUTO_COMPACT_WINDOW -- it's a
        # native CC env var the user may have set. Only scrub Forge-managed vars.
        unset_env_vars.append("ANTHROPIC_BASE_URL")
        unset_env_vars.append("ACTIVE_TEMPLATE")
        unset_env_vars.append(FORGE_PROXY_WIRE_SHAPE_VAR)
    else:
        # Proxy mode: set compaction window to match the routed model's context.
        env_vars["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(context_limit)
        env_vars["ANTHROPIC_BASE_URL"] = base_url
        if wire_shape := resolve_proxy_wire_shape(proxy_id=proxy_id, template=template):
            env_vars[FORGE_PROXY_WIRE_SHAPE_VAR] = wire_shape
        if template is None:
            unset_env_vars.append("ACTIVE_TEMPLATE")
        else:
            env_vars["ACTIVE_TEMPLATE"] = template

    if subprocess_proxy:
        env_vars[FORGE_SUBPROCESS_PROXY_VAR] = subprocess_proxy
        env_vars.update(_resolve_subprocess_proxy_launch_metadata(subprocess_proxy, sidecar=sidecar))

    if fork_name is not None:
        env_vars["FORGE_FORK_NAME"] = fork_name
    if parent_session is not None:
        env_vars["FORGE_PARENT_SESSION"] = parent_session

    return env_vars, unset_env_vars


def _resolve_subprocess_proxy_launch_metadata(proxy_id: str, *, sidecar: bool = False) -> dict[str, str]:
    """Resolve subprocess proxy metadata to inject into launched sessions."""
    try:
        from forge.proxy.proxies import ProxyRegistryStore, resolve_proxy_optional

        registry = ProxyRegistryStore().read()
        entry = resolve_proxy_optional(registry, proxy_id)
        if entry is None:
            return {}

        base_url = _container_reachable_url(entry.base_url) if sidecar else entry.base_url
        metadata = {
            FORGE_SUBPROCESS_BASE_URL_VAR: base_url,
            FORGE_SUBPROCESS_PROXY_ID_VAR: entry.proxy_id,
            FORGE_SUBPROCESS_TEMPLATE_VAR: entry.template,
        }
        if wire_shape := resolve_proxy_wire_shape(proxy_id=entry.proxy_id, template=entry.template):
            metadata[FORGE_PROXY_WIRE_SHAPE_VAR] = wire_shape
        return metadata
    except Exception as e:
        logger.debug("Could not resolve subprocess proxy metadata for %s: %s", proxy_id, e)
        return {}


def _container_reachable_url(base_url: str) -> str:
    """Map host loopback proxy URLs to Docker's host gateway name."""
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return base_url

    host = "host.docker.internal"
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _prepare_sidecar_prompt_file(
    *,
    worktree_path: Path,
    system_prompt_file: str | None,
) -> tuple[str | None, list[tuple[str, str, str]]]:
    """Map a host-side prompt file to a path visible inside the sidecar."""
    if system_prompt_file is None:
        return None, []

    prompt_path = Path(system_prompt_file).resolve()
    worktree_root = worktree_path.resolve()

    try:
        relative_prompt = prompt_path.relative_to(worktree_root)
    except ValueError:
        container_prompt = f"/tmp/{prompt_path.name}"
        return container_prompt, [(str(prompt_path), container_prompt, "ro")]

    return str(Path("/workspace") / relative_prompt), []


def _resolve_extension_detection_root(cwd: Path) -> Path:
    """Return the Forge project root to use for extension inheritance lookup."""
    from forge.core.ops.context import find_forge_root
    from forge.session.claude.paths import find_project_root

    forge_root = find_forge_root(cwd)
    if forge_root is not None:
        return forge_root
    try:
        return find_project_root(str(cwd))
    except FileNotFoundError:
        return cwd.resolve()


def _resolve_worktree_extension_root(manifest: SessionState) -> Path | None:
    """Return where extensions should be installed inside a target worktree."""
    if not manifest.worktree or not manifest.worktree.is_worktree:
        return None

    worktree_root = Path(manifest.worktree.path)
    if manifest.forge_root:
        forge_root = Path(manifest.forge_root)
        try:
            forge_root.relative_to(worktree_root)
            return forge_root
        except ValueError:
            pass
    return worktree_root


def _resolve_launch_mode(*, sidecar: bool, host_proxy: bool) -> str:
    """Resolve host vs sidecar launch mode from CLI flags and runtime config."""
    if sidecar:
        return LAUNCH_MODE_SIDECAR
    if host_proxy:
        return LAUNCH_MODE_HOST

    from forge.runtime_config import get_runtime_config

    return LAUNCH_MODE_SIDECAR if get_runtime_config().proxy_mode == LAUNCH_MODE_SIDECAR else LAUNCH_MODE_HOST


def _get_runtime_base_url(*, use_sidecar: bool, effective_url: str | None) -> str | None:
    """Return the base URL Claude should see for this launch."""
    return SIDECAR_RUNTIME_BASE_URL if use_sidecar else effective_url


def _combine_prompt_files(*, worktree_path: Path, session_name: str, prompt_files: list[Path]) -> str | None:
    """Combine multiple prompt/context files into one appendable prompt file."""
    existing = [path.resolve() for path in prompt_files if path.is_file()]
    if not existing:
        return None
    if len(existing) == 1:
        return str(existing[0])

    launch_context_dir = worktree_path / ".forge" / "launch-context"
    launch_context_dir.mkdir(parents=True, exist_ok=True)
    combined_path = launch_context_dir / f"{session_name}.md"

    sections: list[str] = []
    for path in existing:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        if not content:
            continue
        sections.append(f"<!-- Source: {path.name} -->\n{content}")

    combined_path.write_text("\n\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return str(combined_path.resolve())
