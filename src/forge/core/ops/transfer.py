"""Shared transfer-context operations (command-core).

UI-agnostic operations behind ``forge session transfer`` (and a future ``%transfer``
direct command). They return structured data and raise ``ForgeOpError`` on
failure -- no Click, no printing.

The on-disk layout (``prev_sessions.py``):

- ``generated.md`` -- parent-scoped AI cache (``regenerate`` rewrites this only).
- ``children/<child>.md`` -- per-child pure AI snapshot (frozen; never edited).
- ``children/<child>.notes.md`` -- per-child user-notes overlay (the only
  editable surface; merged into the launch context).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forge.core.state.exceptions import StateCorruptedError, StateUnreadableError
from forge.session import ForgeSessionError, SessionManager, SessionState
from forge.session.prev_sessions import (
    child_notes_path,
    child_path,
    compose_child_context,
    ensure_notes_template,
    generated_path,
    iter_children,
    notes_has_user_content,
)
from forge.session.transfer import (
    TRANSFER_TARGET_RUNTIMES,
    ResumeStrategy,
    assemble_transfer_context,
    parse_transfer_frontmatter,
)

from .context import ExecutionContext
from .session import ForgeOpError


@dataclass(frozen=True)
class TransferView:
    """A rendered transfer artifact for display."""

    parent: str
    child: str | None  # None = parent cache (generated.md)
    path: Path  # the source file (generated.md or the child snapshot)
    content: str  # raw cache, or the composed child view (snapshot + notes)
    frontmatter: dict | None  # parsed forge_transfer block, or None if absent/malformed
    has_notes: bool  # whether the child has a non-empty user-notes overlay
    warning: str | None  # frontmatter parse warning (best-effort), if any
    sections: list[dict[str, Any]]  # ordered ATX-heading map: [{"level", "title"}]


@dataclass(frozen=True)
class RegenerateResult:
    """Outcome of regenerating a parent cache."""

    parent: str
    strategy: str
    depth: int
    path: Path  # the rewritten generated.md
    token_estimate: int | None
    warnings: list[str]
    target_runtime: str


def _require_forge_root(ctx: ExecutionContext) -> Path:
    if ctx.forge_root is None:
        raise ForgeOpError("Not inside a Forge project (no .forge/ directory found).")
    return ctx.forge_root


def _child_names(forge_root: Path, parent: str) -> list[str]:
    """Return sorted child snapshot names (notes overlays excluded by iter_children)."""
    return sorted(path.stem for path in iter_children(forge_root, parent))


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _parse_sections(text: str) -> list[dict[str, Any]]:
    """Parse markdown ATX headings into an ordered section map.

    Returns ``[{"level": int, "title": str}]`` in document order so a JSON
    consumer can see which schema sections (## Decisions, ## Relevant Files, …)
    a transfer doc actually contains without re-parsing the markdown body.
    """
    return [
        {"level": len(m.group(1)), "title": m.group(2)} for line in text.splitlines() if (m := _HEADING_RE.match(line))
    ]


def resolve_single_child(*, ctx: ExecutionContext, parent: str, child: str | None = None) -> str:
    """Resolve a child name: the named child, the sole child, or an error.

    Used by ``diff`` and ``edit`` (which operate on a specific child). Raises
    ``ForgeOpError`` naming the candidates when ``child`` is omitted and the
    parent has zero or multiple children.
    """
    forge_root = _require_forge_root(ctx)
    children = _child_names(forge_root, parent)

    if child is not None:
        if child not in children:
            available = ", ".join(children) if children else "none"
            raise ForgeOpError(f"No child transfer '{child}' under parent '{parent}' (children: {available}).")
        return child

    if not children:
        raise ForgeOpError(f"Parent '{parent}' has no child transfers yet.")
    if len(children) > 1:
        raise ForgeOpError(f"Parent '{parent}' has multiple children ({', '.join(children)}); pass --child.")
    return children[0]


def show_transfer(*, ctx: ExecutionContext, parent: str, child: str | None = None) -> TransferView:
    """Return the parent cache (``child=None``) or the composed child view.

    The child view composes the AI snapshot plus the user-notes overlay (when it
    has content). This approximates the launch context but is not byte-exact: the
    launcher (``_combine_prompt_files``) additionally wraps each file with a
    ``<!-- Source: … -->`` marker and may prepend a configured prompt file.
    """
    forge_root = _require_forge_root(ctx)

    if child is None:
        cache = generated_path(forge_root, parent)
        if not cache.is_file():
            raise ForgeOpError(f"No transfer context for parent '{parent}'.")
        raw = cache.read_text(encoding="utf-8")
        frontmatter, body, warning = parse_transfer_frontmatter(raw)
        return TransferView(
            parent=parent,
            child=None,
            path=cache,
            content=raw,
            frontmatter=frontmatter,
            has_notes=False,
            warning=warning,
            sections=_parse_sections(body),
        )

    snapshot = child_path(forge_root, parent, child)
    if not snapshot.is_file():
        raise ForgeOpError(f"No child transfer '{child}' under parent '{parent}'.")
    composed = compose_child_context(forge_root, parent, child)
    frontmatter, _, warning = parse_transfer_frontmatter(snapshot.read_text(encoding="utf-8"))
    _, composed_body, _ = parse_transfer_frontmatter(composed)
    return TransferView(
        parent=parent,
        child=child,
        path=snapshot,
        content=composed,
        frontmatter=frontmatter,
        has_notes=notes_has_user_content(child_notes_path(forge_root, parent, child)),
        warning=warning,
        sections=_parse_sections(composed_body),
    )


def resolve_notes_target(*, ctx: ExecutionContext, parent: str, child: str) -> Path:
    """Return the per-child notes overlay path, creating the template if absent.

    Raises ``ForgeOpError`` if the child snapshot does not exist (you cannot
    author notes for a child that was never created).
    """
    forge_root = _require_forge_root(ctx)
    if not child_path(forge_root, parent, child).is_file():
        raise ForgeOpError(f"No child transfer '{child}' under parent '{parent}'.")
    return ensure_notes_template(forge_root, parent, child)


def diff_transfer(*, ctx: ExecutionContext, parent: str, child: str) -> str:
    """Return a unified diff of the child snapshot body vs the parent cache body.

    Shows how the regeneratable cache has drifted from the child's frozen
    snapshot. Diffs the **markdown bodies only** (frontmatter stripped): every
    regenerate restamps ``generated_at`` (and may shift ``token_estimate``), so a
    full-file diff would report metadata churn as drift even when the curated
    content is identical. Empty string means no body drift.
    """
    forge_root = _require_forge_root(ctx)
    cache = generated_path(forge_root, parent)
    snapshot = child_path(forge_root, parent, child)
    if not cache.is_file():
        raise ForgeOpError(f"No parent cache for '{parent}'.")
    if not snapshot.is_file():
        raise ForgeOpError(f"No child snapshot '{child}' under '{parent}'.")

    _, snapshot_body, _ = parse_transfer_frontmatter(snapshot.read_text(encoding="utf-8"))
    _, cache_body, _ = parse_transfer_frontmatter(cache.read_text(encoding="utf-8"))
    diff = difflib.unified_diff(
        snapshot_body.splitlines(keepends=True),
        cache_body.splitlines(keepends=True),
        fromfile=f"children/{child}.md (snapshot body)",
        tofile="generated.md (cache body)",
    )
    return "".join(diff)


def regenerate_transfer(
    *,
    ctx: ExecutionContext,
    parent: str,
    strategy: str | None = None,
    depth: int | None = None,
    target_runtime: str | None = None,
) -> RegenerateResult:
    """Rewrite only the parent cache (``generated.md``); never touch children.

    Defaults ``strategy``/``depth``/``target_runtime`` to the existing cache's
    frontmatter so a regenerate does not silently downgrade an ai-curated or full
    cache to structured, nor flip a codex cache back to claude. Falls back to
    ``structured``/``1``/``claude`` only when no metadata exists.
    """
    forge_root = _require_forge_root(ctx)
    cache = generated_path(forge_root, parent)

    eff_strategy = strategy
    eff_depth = depth
    eff_target_runtime = target_runtime
    if (eff_strategy is None or eff_depth is None or eff_target_runtime is None) and cache.is_file():
        frontmatter, _, _ = parse_transfer_frontmatter(cache.read_text(encoding="utf-8"))
        if frontmatter:
            if eff_strategy is None and isinstance(frontmatter.get("strategy"), str):
                eff_strategy = frontmatter["strategy"]
            if eff_depth is None and isinstance(frontmatter.get("depth"), int):
                eff_depth = frontmatter["depth"]
            if eff_target_runtime is None and isinstance(frontmatter.get("target_runtime"), str):
                eff_target_runtime = frontmatter["target_runtime"]
    eff_strategy = eff_strategy or "structured"
    eff_depth = 1 if eff_depth is None else eff_depth
    eff_target_runtime = eff_target_runtime or "claude"

    try:
        resume_strategy = ResumeStrategy(eff_strategy)
    except ValueError as e:
        valid = ", ".join(s.value for s in ResumeStrategy)
        raise ForgeOpError(f"Unknown strategy '{eff_strategy}' (valid: {valid}).") from e

    if eff_target_runtime not in TRANSFER_TARGET_RUNTIMES:
        valid = ", ".join(TRANSFER_TARGET_RUNTIMES)
        raise ForgeOpError(f"Unknown target runtime '{eff_target_runtime}' (valid: {valid}).")

    manager = SessionManager()
    try:
        parent_state = manager.get_session(parent, forge_root=str(forge_root))
    except (StateCorruptedError, StateUnreadableError):
        raise  # corrupt parent manifest -> top-level reset handler
    except ForgeSessionError as e:
        raise ForgeOpError(f"Parent session '{parent}' not found: {e}") from e

    def _get(name: str) -> SessionState | None:
        try:
            return manager.get_session(name, forge_root=str(forge_root))
        except ForgeSessionError:
            return None

    result = assemble_transfer_context(
        parent_name=parent,
        parent_state=parent_state,
        forge_root=forge_root,
        strategy=resume_strategy,
        depth=eff_depth,
        get_session=_get,
        child_name=None,  # parent cache only -- children/* stay frozen
        target_runtime=eff_target_runtime,
    )
    return RegenerateResult(
        parent=parent,
        strategy=resume_strategy.value,
        depth=eff_depth,
        path=cache,
        token_estimate=result.token_estimate,
        warnings=result.warnings,
        target_runtime=eff_target_runtime,
    )
