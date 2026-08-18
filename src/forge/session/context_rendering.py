"""Neutral Markdown primitives for session context documents."""

from __future__ import annotations


def coerce_render_text(value: object) -> str:
    """Return a trimmed string, or an empty string for other values."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


def render_text_bullets(items: object, *, empty_label: str) -> list[str]:
    """Render non-empty strings as bullets, using ``empty_label`` when none survive."""
    lines: list[str] = []
    if isinstance(items, list):
        for item in items:
            text = coerce_render_text(item)
            if text:
                lines.append(f"- {text}")
    return lines or [empty_label]


def render_cited_text_bullets(
    items: object,
    *,
    empty_label: str,
    citation_label: str,
) -> list[str]:
    """Render text/citation items as bullets with caller-owned labels."""
    lines: list[str] = []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                text = coerce_render_text(item.get("text"))
                citation = coerce_render_text(item.get("citation"))
            else:
                text, citation = coerce_render_text(item), ""
            if not text:
                continue
            lines.append(f"- {text} _({citation_label}: {citation})_" if citation else f"- {text}")
    return lines or [empty_label]


def render_markdown_section(section_title: str, body_lines: list[str]) -> list[str]:
    """Render a level-two section with stable blank-line framing."""
    return [f"## {section_title}", "", *body_lines, ""]
