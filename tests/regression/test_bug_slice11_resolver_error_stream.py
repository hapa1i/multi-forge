"""Regression: session proxy-resolution failures must print to stderr, not stdout.

forge_cli_cleanup Slice 11 routed hand-rolled errors through forge.cli.output. In
``session._resolve_routing_from_cli`` the conversion replaced ``click.ClickException``
(which Click renders to stderr) with ``print_error*(console=console)``, and the
module ``console`` is the shared stdout console -- so proxy-resolution errors and
their recovery tips regressed from stderr onto stdout, polluting the results stream
(cli_style_guidelines.md "Output Streams"). The five resolver unit tests all mock
``_resolve_routing_from_cli`` wholesale, so none exercised the real error path.

Root cause: stdout console passed where stderr was required.
Fix: route the resolver's error/tip sites through ``output.err_console``.
Affected: ``src/forge/cli/session.py`` (``_resolve_routing_from_cli``),
``src/forge/cli/output.py`` (``err_console``).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from forge.cli.main import main

pytestmark = pytest.mark.regression


def test_unknown_proxy_error_and_tip_go_to_stderr() -> None:
    """An unresolvable --proxy fails on stderr with a clean stdout stream."""
    result = CliRunner().invoke(
        main, ["session", "start", "smoke", "--proxy", "definitely-not-a-proxy-template"]
    )

    assert result.exit_code == 1
    # Error + recovery tip belong on the diagnostics stream.
    assert "Error:" in result.stderr
    assert "Tip:" in result.stderr
    assert "forge proxy template list" in result.stderr
    # The results stream must stay clean -- this is what regressed.
    assert "Error:" not in result.stdout
    assert "Tip:" not in result.stdout
