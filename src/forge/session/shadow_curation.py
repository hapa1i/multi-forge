"""Shadow proposal curation: LLM-powered synthesis of shadow docs.

Collects shadow proposals across sessions, reads official + shadow content,
and produces a curated review report via ``run_claude_session()``.

Also owns shadow discovery (``collect_shadow_entries``), used by the
``forge memory shadows`` CLI commands.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from forge.core.ops.context import ExecutionContext

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ShadowEntry:
    """A shadow doc entry with source identity."""

    official: str
    shadow_path: str
    strategy: str
    session: str
    forge_root: str
    content: str = ""


@dataclass
class CurationResult:
    """Outcome of a curation run."""

    success: bool
    report_path: Path | None
    stdout: str


# ---------------------------------------------------------------------------
# Shadow discovery (moved from CLI layer)
# ---------------------------------------------------------------------------


def collect_shadow_entries(
    *,
    ctx: ExecutionContext,
    scope: str,
    session_filter: str | None,
) -> tuple[list[ShadowEntry], set[str]]:
    """Collect shadow entries across sessions in *scope*.

    Returns (entries, scanned_roots). Each entry carries the forge_root
    for repo-scope deduplication and file reads.
    """
    from forge.core.ops.session import ForgeOpError, list_sessions
    from forge.session.effective import compute_effective_intent
    from forge.session.exceptions import ForgeSessionError
    from forge.session.manager import SessionManager

    result = list_sessions(ctx=ctx, include_incognito=False, scope=scope)
    manager = SessionManager()
    entries: list[ShadowEntry] = []
    scanned_roots: set[str] = set()

    for item in result.sessions:
        if session_filter and item.name != session_filter:
            continue
        entry = item.entry
        fr = entry.forge_root or entry.worktree_path
        if not fr:
            continue
        scanned_roots.add(fr)

        try:
            manifest = manager.get_session(item.name, forge_root=fr)
            effective = compute_effective_intent(manifest)
        except (ForgeSessionError, ForgeOpError, OSError):
            logger.debug("Failed to read manifest for session %r in %s", item.name, fr, exc_info=True)
            continue

        if not effective.memory:
            continue

        for doc in effective.memory.designated_docs:
            if doc.shadows is None:
                continue
            entries.append(
                ShadowEntry(
                    official=doc.shadows,
                    shadow_path=doc.path,
                    strategy=doc.strategy,
                    session=item.name,
                    forge_root=fr,
                )
            )

    return entries, scanned_roots


# ---------------------------------------------------------------------------
# Curation prompt
# ---------------------------------------------------------------------------

_CURATION_TEMPLATE = """\
You are a documentation curation agent. Your job is to review shadow proposals \
against an official document and produce a structured synthesis.


## Official Document

**Path**: {official_path}

```
{official_content}
```

## Shadow Proposals

{shadow_sections}

## Instructions

Compare each shadow proposal against the official document. Produce exactly \
four sections:

### Promote

Genuinely new information worth adding to the official document.
Format each item as a checkbox with source citation:
`- [ ] <proposed addition> (source: <shadow_path>, session: <session>)`

### Already Present

Items that duplicate what the official document already says. One bullet each, brief.

### Conflicts

Items that contradict the official document. State both versions with paths.

### Discard

Noise, session-specific details, or speculative items not worth promoting.
One bullet each with brief rationale.

Do NOT modify any files. This is a read-only review."""


def build_curation_prompt(
    *,
    official_path: str,
    official_content: str,
    shadow_entries: list[ShadowEntry],
) -> str:
    """Build a self-contained curation prompt with inlined doc contents."""
    sections: list[str] = []
    for entry in shadow_entries:
        header = f"### {entry.shadow_path} (session: {entry.session}, root: {entry.forge_root})"
        body = entry.content.strip() if entry.content else "_(empty)_"
        sections.append(f"{header}\n\n```\n{body}\n```")

    shadow_text = "\n\n".join(sections) if sections else "_(no shadow proposals)_"

    return _CURATION_TEMPLATE.format(
        official_path=official_path,
        official_content=official_content,
        shadow_sections=shadow_text,
    )


# ---------------------------------------------------------------------------
# Report persistence
# ---------------------------------------------------------------------------


def _doc_slug(official_path: str) -> str:
    """Derive a filename slug from an official doc path.

    Strips extension, replaces ``/`` with ``_``, strips leading dots/underscores,
    truncates to 60 chars. Appends a 6-char hash of the original path to prevent
    collisions (``a/b.md`` vs ``a_b.md`` vs truncation).
    """
    stem = re.sub(r"\.[^.]+$", "", official_path)
    slug = stem.replace("/", "_").replace("\\", "_")
    slug = slug.lstrip("._")
    slug = slug[:60]
    path_hash = hashlib.sha256(official_path.encode()).hexdigest()[:6]
    return f"{slug}-{path_hash}"


def curation_report_dir(forge_root: Path, session_name: str) -> Path:
    """Return ``.forge/artifacts/{session}/memory/``."""
    return forge_root / ".forge" / "artifacts" / session_name / "memory"


def persist_curation_report(
    *,
    forge_root: Path,
    session_name: str,
    official_path: str,
    scope: str,
    shadow_count: int,
    content: str,
) -> Path:
    """Write a timestamped curation report. Returns the path."""
    from datetime import datetime, timezone

    output_dir = curation_report_dir(forge_root, session_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S-%f")
    slug = _doc_slug(official_path)
    target = output_dir / f"curation-{slug}-{stamp}.md"

    header = (
        f"# Shadow Curation Report -- {session_name}\n\n"
        f"**Official doc**: {official_path}\n"
        f"**Timestamp**: {now.isoformat()}\n"
        f"**Shadow sources**: {shadow_count}\n"
        f"**Scope**: {scope}\n\n"
        "---\n\n"
    )
    target.write_text(header + (content or "_(no output)_\n"), encoding="utf-8")
    return target


def report_glob_pattern(official_path: str) -> str:
    """Return the glob pattern for ``--show-latest`` filtering by doc."""
    slug = _doc_slug(official_path)
    return f"curation-{slug}-*.md"


# ---------------------------------------------------------------------------
# Curation orchestrator
# ---------------------------------------------------------------------------


def run_shadow_curation(
    *,
    session_name: str,
    forge_root: Path,
    official_path: str,
    official_content: str,
    shadow_entries: list[ShadowEntry],
    base_url: str | None = None,
    direct: bool = False,
    timeout_seconds: int = 120,
    scope: str = "project",
) -> CurationResult:
    """Build prompt, call LLM, persist report.

    The caller (CLI) resolves routing via ``resolve_handoff_base_url()``
    and passes ``base_url`` + ``direct``.
    """
    from forge.core.reactive.cost_tracking import track_verb_cost
    from forge.core.reactive.session_runner import run_claude_session

    prompt = build_curation_prompt(
        official_path=official_path,
        official_content=official_content,
        shadow_entries=shadow_entries,
    )

    tracking_urls = [base_url] if base_url else []

    with track_verb_cost("curation", tracking_urls):
        result = run_claude_session(
            prompt,
            base_url=base_url,
            direct=direct,
            timeout_seconds=timeout_seconds,
            cwd=str(forge_root),
        )

    if not result.success:
        logger.warning(
            "Curation failed for %s (session %s): rc=%s, error=%s",
            official_path,
            session_name,
            result.returncode,
            result.error or result.stderr[:200],
        )
        return CurationResult(success=False, report_path=None, stdout=result.stdout or "")

    report_path = persist_curation_report(
        forge_root=forge_root,
        session_name=session_name,
        official_path=official_path,
        scope=scope,
        shadow_count=len(shadow_entries),
        content=result.stdout,
    )

    logger.info("Curation report written to %s", report_path)
    return CurationResult(success=True, report_path=report_path, stdout=result.stdout)
