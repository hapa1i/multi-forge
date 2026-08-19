"""Final status-line layout, palette application, and output hardening."""

from __future__ import annotations

from forge.cli.statusline import formatting
from forge.cli.statusline.palette import Palette, apply_palette

__all__ = ["render_output"]


def render_output(
    where: list[str],
    stream: list[str],
    *,
    palette: Palette,
    term_width: int,
    truncate: bool,
) -> str:
    """Render and harden the two status-line buckets for terminal output."""
    output = formatting.render_categories(where, stream)
    output = apply_palette(output, palette)

    # Override Claude Code's dim default styling, then use non-breaking spaces
    # so VS Code's terminal does not trim the rendered line.
    output = "\x1b[0m" + output
    output = output.replace(" ", "\u00a0")

    # Prefer a separator-boundary wrap over truncation when the custom line plus
    # Claude Code's native token display would exceed the terminal width.
    if truncate:
        available = term_width - formatting.TRAILING_MARGIN - formatting.NATIVE_DISPLAY_RESERVE
        if available > 3:
            display_width = formatting.visible_width(output)
            if display_width + formatting.TRAILING_MARGIN + formatting.NATIVE_DISPLAY_RESERVE > term_width:
                output = formatting.wrap_output(output, available)

    # RESET prevents color bleed; NBSP padding keeps Claude's adjacent native
    # display visually separate on every wrapped line.
    margin = formatting.RESET + "\u00a0" * formatting.TRAILING_MARGIN
    return "\n".join(line + margin for line in output.split("\n"))
