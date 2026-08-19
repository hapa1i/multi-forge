"""Color palettes and glyph sets for the status line.

Two mechanisms, chosen by how the styled bytes are produced:

- **Palette (colors)** is applied as an *output-level ANSI remap*. Every role
  (path, branch, each tier, each context band, ...) emits a unique role-specific
  ANSI code, so recoloring is a single-pass regex that maps each default code to
  its replacement. This recolors the whole rendered line without threading a
  ``palette`` argument through the ~8 ``format_*`` helpers, and the ``default``
  palette is a literal no-op (the golden guard stays byte-identical).
- **Glyphs (chars)** can't be remapped at the output level (``-``/``#`` are not
  unique tokens), so they're threaded into the one place they're emitted: the
  progress bar in ``get_context_display``.

``DEFAULT_PALETTE`` / ``ASCII_GLYPHS`` are built from ``formatting`` constants,
so they cannot drift from the real defaults. Import direction stays acyclic:
palette depends on formatting, final rendering depends on both, and the command
depends only downward on the status-line package.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

from forge.cli.statusline import formatting as fmt


@dataclass(frozen=True)
class Palette:
    """Role -> ANSI color code. Field values are full SGR escape sequences."""

    path: str
    branch: str
    breadcrumb: str
    template: str
    metrics: str
    think: str
    line_add: str
    line_remove: str
    tier_haiku: str
    tier_sonnet: str
    tier_sonnet_deep: str
    tier_opus: str
    tier_opus_deep: str
    ctx_low: str
    ctx_med: str
    ctx_high: str
    ctx_warn: str
    ctx_crit: str


# Default == today's exact module constants (so the remap is a no-op and a
# drift-guard test can assert equality).
DEFAULT_PALETTE = Palette(
    path=fmt.GREEN_BOLD,
    branch=fmt.YELLOW_BOLD,
    breadcrumb=fmt.BREADCRUMB_COLOR,
    template=fmt.TEMPLATE_COLOR,
    metrics=fmt.METRICS_COLOR,
    think=fmt.BLUE,
    line_add=fmt.LINE_ADD_COLOR,
    line_remove=fmt.LINE_REMOVE_COLOR,
    tier_haiku=fmt.TIER_HAIKU,
    tier_sonnet=fmt.TIER_SONNET,
    tier_sonnet_deep=fmt.TIER_SONNET_DEEP,
    tier_opus=fmt.TIER_OPUS,
    tier_opus_deep=fmt.TIER_OPUS_DEEP,
    ctx_low=fmt.CTX_LOW,
    ctx_med=fmt.CTX_MED,
    ctx_high=fmt.CTX_HIGH,
    ctx_warn=fmt.CTX_WARN,
    ctx_crit=fmt.CTX_CRIT,
)

# "Sage & clay" earth tones: moss/sage/clay/stone/ochre, tiers in a green-family
# shaded by context size. Context gradient nudged warmer at the low end.
EARTHY_PALETTE = Palette(
    path="\033[1;38;5;65m",  # bold moss
    branch="\033[38;5;108m",  # sage
    breadcrumb="\033[38;5;138m",  # clay
    template="\033[38;5;102m",  # stone
    metrics="\033[38;5;145m",  # warm grey (== default)
    think="\033[38;5;179m",  # ochre
    line_add="\033[38;5;71m",  # fern
    line_remove="\033[38;5;167m",  # clay-red
    tier_haiku="\033[38;5;108m",  # sage
    tier_sonnet="\033[38;5;72m",  # teal-sage
    tier_sonnet_deep="\033[38;5;66m",  # deep teal-sage
    tier_opus="\033[38;5;65m",  # moss
    tier_opus_deep="\033[38;5;23m",  # deep moss
    ctx_low="\033[38;5;151m",  # pale sage
    ctx_med="\033[38;5;108m",  # sage
    ctx_high="\033[38;5;179m",  # ochre (== default)
    ctx_warn="\033[38;5;173m",  # burnt orange (== default)
    ctx_crit="\033[38;5;167m",  # clay-red (== default)
)

_PALETTES: dict[str, Palette] = {"default": DEFAULT_PALETTE, "earthy": EARTHY_PALETTE}


def resolve_palette(name: str) -> Palette:
    """Map a config palette name to a ``Palette`` (unknown -> default)."""
    return _PALETTES.get(name, DEFAULT_PALETTE)


def _remap(palette: Palette) -> dict[str, str]:
    return {
        getattr(DEFAULT_PALETTE, f.name): getattr(palette, f.name)
        for f in fields(Palette)
        if getattr(DEFAULT_PALETTE, f.name) != getattr(palette, f.name)
    }


def apply_palette(text: str, palette: Palette) -> str:
    """Recolor ``text`` by replacing each default role code with the palette's.

    Single-pass (substituted bytes are not re-scanned) so a value that happens to
    equal another role's default code never chains. Longest-key-first guards
    against any prefix overlap. ``default`` palette -> empty remap -> no-op.
    """
    remap = _remap(palette)
    if not remap:
        return text
    keys = sorted(remap, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(k) for k in keys))
    return pattern.sub(lambda m: remap[m.group(0)], text)


@dataclass(frozen=True)
class Glyphs:
    """Progress-bar fill/empty characters."""

    filled: str
    empty: str


ASCII_GLYPHS = Glyphs(filled=fmt.PROGRESS_FILLED, empty=fmt.PROGRESS_EMPTY)
# U+2588 FULL BLOCK / U+2591 LIGHT SHADE (Block Elements, not emoji). Escaped so
# the normalize-text hook can't strip them on commit.
UNICODE_GLYPHS = Glyphs(filled="\u2588", empty="\u2591")

_GLYPHS: dict[str, Glyphs] = {"ascii": ASCII_GLYPHS, "unicode": UNICODE_GLYPHS}


def resolve_glyphs(name: str) -> Glyphs:
    """Map a config glyphs name to a ``Glyphs`` (unknown -> ascii)."""
    return _GLYPHS.get(name, ASCII_GLYPHS)
