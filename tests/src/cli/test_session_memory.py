"""Tests for ``forge session memory`` tombstone (replaced by ``forge memory``)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from forge.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTombstone:
    def test_bare_group_tombstone(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "memory"])
        assert "forge memory" in result.output

    def test_help_tombstone(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "memory", "--help"])
        assert "forge memory" in result.output

    def test_list_docs_tombstone(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "memory", "list-docs"])
        assert result.exit_code != 0
        assert "forge memory list" in result.output

    def test_add_doc_tombstone(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "memory", "add-doc", "x.md"])
        assert result.exit_code != 0
        assert "forge memory track" in result.output

    def test_remove_doc_tombstone(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "memory", "remove-doc", "x.md"])
        assert result.exit_code != 0
        assert "forge memory passport remove" in result.output
