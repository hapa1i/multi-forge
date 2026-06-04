"""Palette (ANSI remap) and glyph (progress-bar char) tests for the status line.

The default palette is a no-op remap and ascii glyphs are the module defaults, so
the golden guard (test_statusline_registry.py) covers the default path. These
tests cover the earthy/unicode opt-ins and the remap's correctness invariants.
"""

from __future__ import annotations

import contextlib
import json
from unittest.mock import patch

from click.testing import CliRunner

from forge.cli import status_line as sl
from forge.cli.status_line import TranscriptStats, get_context_display, status_line
from forge.cli.statusline.palette import (
    ASCII_GLYPHS,
    DEFAULT_PALETTE,
    EARTHY_PALETTE,
    UNICODE_GLYPHS,
    apply_palette,
    resolve_glyphs,
    resolve_palette,
)
from forge.runtime_config import RuntimeConfig, StatusLineConfig

FIXTURE = {
    "workspace": {"current_dir": "/tmp/demo"},
    "model": {"display_name": "Opus 4.6"},
    "context_window": {
        "context_window_size": 200000,
        "used_percentage": 12,
        "current_usage": {"input_tokens": 12000, "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 5000},
    },
}


def _render_with_statusline(**statusline_kwargs):
    """Render status_line() with a patched RuntimeConfig.statusline."""
    cfg = RuntimeConfig(statusline=StatusLineConfig(**statusline_kwargs))
    runner = CliRunner()
    with contextlib.ExitStack() as es:
        es.enter_context(patch.object(sl, "_get_terminal_width", return_value=200))
        es.enter_context(patch.object(sl, "detect_proxy", return_value=(False, None, False)))
        es.enter_context(patch.object(sl, "discover_session", return_value=(None, False)))
        es.enter_context(patch.object(sl, "get_git_branch", return_value=None))
        es.enter_context(patch.object(sl, "_cached_scan_transcript", return_value=TranscriptStats()))
        es.enter_context(patch("forge.runtime_config.get_runtime_config", return_value=cfg))
        res = runner.invoke(status_line, input=json.dumps(FIXTURE), env={"FORGE_STATUS_TRUNCATE": "0"})
    assert res.exit_code == 0, res.output
    return res.output


class TestPaletteResolution:
    def test_default_name(self):
        assert resolve_palette("default") is DEFAULT_PALETTE

    def test_earthy_name(self):
        assert resolve_palette("earthy") is EARTHY_PALETTE

    def test_unknown_falls_back_to_default(self):
        assert resolve_palette("nope") is DEFAULT_PALETTE


class TestDefaultPaletteNoDrift:
    """DEFAULT_PALETTE is built from the live constants; assert no drift."""

    def test_representative_fields_match_constants(self):
        assert DEFAULT_PALETTE.path == sl.GREEN_BOLD
        assert DEFAULT_PALETTE.branch == sl.YELLOW_BOLD
        assert DEFAULT_PALETTE.breadcrumb == sl.BREADCRUMB_COLOR
        assert DEFAULT_PALETTE.template == sl.TEMPLATE_COLOR
        assert DEFAULT_PALETTE.think == sl.BLUE
        assert DEFAULT_PALETTE.tier_opus == sl.TIER_OPUS
        assert DEFAULT_PALETTE.ctx_low == sl.CTX_LOW
        assert DEFAULT_PALETTE.ctx_crit == sl.CTX_CRIT


class TestApplyPalette:
    def test_default_is_noop(self):
        text = f"{sl.GREEN_BOLD}/x{sl.RESET} {sl.TIER_OPUS}[Opus]{sl.RESET}"
        assert apply_palette(text, DEFAULT_PALETTE) == text

    def test_earthy_remaps_path_and_tier(self):
        text = f"{sl.GREEN_BOLD}/x{sl.RESET}{sl.TIER_OPUS}[Opus]{sl.RESET}"
        out = apply_palette(text, EARTHY_PALETTE)
        assert sl.GREEN_BOLD not in out
        assert EARTHY_PALETTE.path in out
        assert sl.TIER_OPUS not in out
        assert EARTHY_PALETTE.tier_opus in out
        assert sl.RESET in out  # structural reset untouched

    def test_no_chained_substitution(self):
        # think default (BLUE) -> earthy ochre (38;5;179); ctx_high default is
        # also 179 (identity). A sequential replace could double-map a freshly
        # written 179; single-pass must produce exactly the earthy think code.
        text = f"{sl.BLUE}T{sl.RESET}"
        assert apply_palette(text, EARTHY_PALETTE) == f"{EARTHY_PALETTE.think}T{sl.RESET}"

    def test_separators_untouched(self):
        # DARK_GRAY (SEP) is structural; earthy does not remap it.
        text = f"{sl.DARK_GRAY}|{sl.RESET}"
        assert apply_palette(text, EARTHY_PALETTE) == text


class TestGlyphs:
    def test_ascii_default(self):
        assert resolve_glyphs("ascii") is ASCII_GLYPHS
        assert (ASCII_GLYPHS.filled, ASCII_GLYPHS.empty) == ("#", "-")

    def test_unicode(self):
        assert resolve_glyphs("unicode") is UNICODE_GLYPHS
        assert (UNICODE_GLYPHS.filled, UNICODE_GLYPHS.empty) == ("\u2588", "\u2591")

    def test_unknown_falls_back_ascii(self):
        assert resolve_glyphs("nope") is ASCII_GLYPHS

    def test_context_display_ascii_default(self):
        out = get_context_display({"percent": 50, "context_window": 200000})
        assert "#" in out and "-" in out

    def test_context_display_unicode(self):
        out = get_context_display({"percent": 50, "context_window": 200000}, ("\u2588", "\u2591"))
        assert "\u2588" in out and "\u2591" in out
        assert "#" not in out


class TestEndToEnd:
    def test_default_keeps_constants(self):
        out = _render_with_statusline()
        assert sl.GREEN_BOLD in out  # path bold-green by default
        assert sl.TIER_OPUS in out  # opus tier blue by default

    def test_earthy_recolors(self):
        out = _render_with_statusline(palette="earthy")
        assert sl.GREEN_BOLD not in out
        assert EARTHY_PALETTE.path in out
        assert sl.TIER_OPUS not in out
        assert EARTHY_PALETTE.tier_opus in out

    def test_unicode_glyphs_render_blocks(self):
        # 12% of an 8-cell bar -> 0 filled, 8 empty -> all light-shade blocks.
        out = _render_with_statusline(glyphs="unicode")
        assert "\u2591" in out
        assert "--------" not in out

    def test_palette_and_glyphs_are_orthogonal(self):
        out = _render_with_statusline(palette="earthy", glyphs="unicode")
        assert EARTHY_PALETTE.path in out  # recolored
        assert "\u2591" in out  # block glyphs
