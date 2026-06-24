"""Tests for forge clean CLI command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from forge.cli.gc import clean_cmd
from forge.core.ops.gc import CleanReport, OrphanCategory


def _make_report(scope: str = "workspace", total: int = 0) -> CleanReport:
    """Build a CleanReport with optional orphans."""
    cats = [
        OrphanCategory("session_dirs", "Orphan session dirs", total, ["/fake/path"] * total),
        OrphanCategory("transfer_files", "Orphan transfer files", 0, []),
        OrphanCategory("active_entries", "Stale active entries", 0, []),
        OrphanCategory("work_queue", "Stale work queue", 0, []),
        OrphanCategory("proxies", "Stale proxy entries", 0, []),
        OrphanCategory("search_docs", "Orphan search docs", 0, []),
    ]
    return CleanReport(categories=cats, scope=scope)


class TestCleanCmdDryRun:
    def test_dry_run_shows_report(self) -> None:
        report = _make_report(total=2)
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd") as mock_ctx,
            patch("forge.cli.gc.collect_clean_report", return_value=report),
        ):
            mock_ctx.return_value = None  # not used in mocked path
            runner = CliRunner()
            result = runner.invoke(clean_cmd, [])
            assert result.exit_code == 0
            assert "2" in result.output
            assert "Orphan session dirs" in result.output
            assert "Tip:" in result.output

    def test_clean_repo_shows_nothing(self) -> None:
        report = _make_report(total=0)
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
        ):
            runner = CliRunner()
            result = runner.invoke(clean_cmd, [])
            assert result.exit_code == 0
            assert "Nothing to clean" in result.output

    def test_verbose_shows_items(self) -> None:
        report = _make_report(total=1)
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
        ):
            runner = CliRunner()
            result = runner.invoke(clean_cmd, ["--verbose"])
            assert result.exit_code == 0
            assert "/fake/path" in result.output

    def test_json_output(self) -> None:
        report = _make_report(total=1)
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
        ):
            runner = CliRunner()
            result = runner.invoke(clean_cmd, ["--json"])
            assert result.exit_code == 0
            import json

            data = json.loads(result.output)
            assert data["dry_run"] is True
            assert data["total"] == 1


class TestCleanCmdYes:
    def test_yes_runs_clean(self) -> None:
        report = _make_report(total=1)
        from forge.core.ops.gc import CleanResult

        clean_result = CleanResult(categories_cleaned={"session_dirs": 1}, failed=[])
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean", return_value=clean_result),
        ):
            runner = CliRunner()
            result = runner.invoke(clean_cmd, ["--yes"])
            assert result.exit_code == 0
            assert "Cleaned" in result.output
            assert "1" in result.output


class TestCleanCmdErrors:
    def test_scope_project_no_forge_root(self) -> None:
        from forge.core.ops.gc import CleanError

        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", side_effect=CleanError("Not inside a Forge project")),
        ):
            runner = CliRunner()
            result = runner.invoke(clean_cmd, ["--scope", "project"])
            assert result.exit_code != 0
            assert "Not inside a Forge project" in result.output


class TestVerbRenames:
    """Verify the renamed commands exist."""

    def test_proxy_clean_removed(self) -> None:
        # Removed in Slice 09 (F14a, fully redundant); stale proxies are auto-pruned
        # by list/create/start and by `forge clean`.
        from forge.cli.proxy import proxy

        cmd = proxy.get_command(None, "clean")  # type: ignore[arg-type]
        assert cmd is None

    def test_proxy_prune_removed(self) -> None:
        from forge.cli.proxy import proxy

        cmd = proxy.get_command(None, "prune")  # type: ignore[arg-type]
        assert cmd is None

    def test_search_clean_exists(self) -> None:
        from forge.cli.search import search_cmd

        cmd = search_cmd.get_command(None, "clean")  # type: ignore[arg-type]
        assert cmd is not None
        assert "orphaned" in (cmd.help or "").lower()

    def test_search_prune_removed(self) -> None:
        from forge.cli.search import search_cmd

        cmd = search_cmd.get_command(None, "prune")  # type: ignore[arg-type]
        assert cmd is None

    def test_top_level_clean_exists(self) -> None:
        from forge.cli.main import main

        cmd = main.get_command(None, "clean")  # type: ignore[arg-type]
        assert cmd is not None
