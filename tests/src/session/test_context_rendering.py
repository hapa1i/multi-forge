"""Tests for shared session-context Markdown primitives."""

from __future__ import annotations

import pytest

from forge.session.context_rendering import (
    coerce_render_text,
    render_cited_text_bullets,
    render_markdown_section,
    render_text_bullets,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  kept  ", "kept"),
        ("   ", ""),
        (None, ""),
        (3, ""),
    ],
)
def test_coerce_render_text(value: object, expected: str) -> None:
    assert coerce_render_text(value) == expected


def test_render_text_bullets_uses_caller_empty_label() -> None:
    assert render_text_bullets(["  first  ", "", 3, "second"], empty_label="EMPTY") == ["- first", "- second"]
    assert render_text_bullets(["", None], empty_label="EMPTY") == ["EMPTY"]
    assert render_text_bullets("first", empty_label="EMPTY") == ["EMPTY"]


def test_render_cited_text_bullets_uses_caller_labels() -> None:
    items = [
        {"text": "  decision  ", "citation": "  turn 2  "},
        "  plain  ",
        {"text": "", "citation": "turn 3"},
        3,
    ]

    assert render_cited_text_bullets(items, empty_label="EMPTY", citation_label="source") == [
        "- decision _(source: turn 2)_",
        "- plain",
    ]
    assert render_cited_text_bullets([], empty_label="EMPTY", citation_label="source") == ["EMPTY"]


def test_render_markdown_section_uses_caller_title() -> None:
    assert render_markdown_section("Decisions", ["- keep this"]) == ["## Decisions", "", "- keep this", ""]
