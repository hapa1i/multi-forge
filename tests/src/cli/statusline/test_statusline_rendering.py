"""Final status-line layout and hardening tests."""

from forge.cli.statusline import formatting
from forge.cli.statusline.palette import DEFAULT_PALETTE
from forge.cli.statusline.rendering import render_output


def test_render_output_preserves_default_bytes_and_margin() -> None:
    margin = formatting.RESET + "\u00a0" * formatting.TRAILING_MARGIN
    output = render_output(
        ["path"],
        ["model"],
        palette=DEFAULT_PALETTE,
        term_width=200,
        truncate=True,
    )

    assert output == f"\x1b[0mpath\u00a0{formatting.SEP}\u00a0model{margin}"


def test_render_output_wraps_at_the_bucket_separator() -> None:
    output = render_output(
        ["abcdefgh"],
        ["ijklmnop"],
        palette=DEFAULT_PALETTE,
        term_width=35,
        truncate=True,
    )

    lines = output.splitlines()
    assert len(lines) == 2
    assert "abcdefgh" in lines[0]
    assert "ijklmnop" in lines[1]
    margin = formatting.RESET + "\u00a0" * formatting.TRAILING_MARGIN
    assert all(line.endswith(margin) for line in lines)
