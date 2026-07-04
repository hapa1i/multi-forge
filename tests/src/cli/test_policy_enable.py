"""Tests for `forge policy enable` CLI behavior (A3: fail loud on no bundle)."""

from __future__ import annotations

from click.testing import CliRunner
from pytest import fixture

from forge.cli.main import main


@fixture
def runner():
    return CliRunner()


class TestEnableRequiresBundle:
    def test_bare_enable_fails_loud(self, runner: CliRunner) -> None:
        """Bare `policy enable` is a loud stderr error, not a silent stdout no-op.

        A3: the old behavior printed a warning on stdout and exited 0. The CLI is the
        explicit surface, so it now requires --bundle; restore-from-intent is the
        interactive `%policy enable` shortcut's job (design_workflows.md).
        """
        result = runner.invoke(main, ["policy", "enable"])
        err = " ".join(result.stderr.split())

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "No policy bundles specified." in err
        # The recovery tip must name BOTH bundles, not degrade to one.
        assert "Tip:" in err
        assert "--bundle tdd" in err
        assert "coding_standards" in err

    def test_help_lists_bundle_choices(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["policy", "enable", "--help"])

        assert result.exit_code == 0
        assert "--bundle" in result.output
        assert "tdd" in result.output
        assert "coding_standards" in result.output
