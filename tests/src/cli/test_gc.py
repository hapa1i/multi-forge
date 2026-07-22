"""Tests for forge clean CLI command."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from forge.cli.gc import clean_cmd
from forge.core.ops.gc import CleanReport, CleanResult, OrphanCategory
from forge.install.project_compat import ProjectCompatibilitySkip


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


def _compatibility_skip() -> ProjectCompatibilitySkip:
    return ProjectCompatibilitySkip(
        target="/project/.forge/sessions/ghost",
        forge_root="/project",
        state="incompatible",
        reason="project requires Forge >=9999, but running Forge is 0.1.0",
        recovery="Run a Forge version satisfying required_forge, or edit/reset project state.",
    )


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

    def test_unmanaged_package_category_renders_paths_and_json_count(self) -> None:
        import json

        package = "/project/.agents/skills/understand"
        report = CleanReport(
            categories=[
                OrphanCategory(
                    "unmanaged_skill_packages",
                    "Untracked Forge runtime skill packages with verified provenance",
                    1,
                    [package],
                )
            ],
            scope="project",
        )
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
        ):
            human = CliRunner().invoke(clean_cmd, ["--scope", "project", "--verbose"])
            machine = CliRunner().invoke(clean_cmd, ["--scope", "project", "--json"])

        assert human.exit_code == 0
        assert "Unmanaged skill packages:" in human.output
        assert package in human.output
        payload = json.loads(machine.output)
        assert payload["total"] == 1
        assert payload["categories"] == [
            {
                "category": "unmanaged_skill_packages",
                "description": "Untracked Forge runtime skill packages with verified provenance",
                "count": 1,
                "items": [package],
            }
        ]

    def test_direct_clean_inherits_unmanaged_read_only_report(self, capsys) -> None:
        import json

        from forge.cli.hooks.direct_commands import _handle_cmd_clean

        report = CleanReport(
            categories=[
                OrphanCategory(
                    "unmanaged_skill_packages",
                    "Untracked Forge runtime skill packages with verified provenance",
                    2,
                    ["/project/.agents/skills/review", "/project/.agents/skills/understand"],
                )
            ],
            scope="project",
        )
        with (
            patch("forge.core.ops.context.ExecutionContext.from_cwd"),
            patch("forge.core.ops.gc.collect_clean_report", return_value=report),
            patch("forge.core.ops.gc.run_clean") as run_clean,
        ):
            _handle_cmd_clean(["--scope", "project"])

        payload = json.loads(capsys.readouterr().out)
        assert payload["decision"] == "block"
        assert "Untracked Forge runtime skill packages with verified provenance: 2" in payload["reason"]
        assert "forge clean --yes" in payload["reason"]
        run_clean.assert_not_called()

    def test_preview_labels_apply_refusal_without_running_clean(self) -> None:
        report = _make_report(total=1)
        report.skipped_project_compatibility.append(_compatibility_skip())
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean") as mock_run,
        ):
            result = CliRunner().invoke(clean_cmd, [])

        assert result.exit_code == 0
        mock_run.assert_not_called()
        assert "Would skip 1 project-owned item" in result.output
        assert "target: /project/.forge/sessions/ghost" in result.output
        assert "root: /project" in result.output
        assert "state: incompatible" in result.output
        assert "reason:" in result.output
        assert "recovery:" in result.output

    def test_json_preview_includes_structured_compatibility_skip(self) -> None:
        import json

        report = _make_report(total=1)
        report.skipped_project_compatibility.append(_compatibility_skip())
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
        ):
            result = CliRunner().invoke(clean_cmd, ["--json"])

        assert result.exit_code == 0
        skip = json.loads(result.output)["skipped_project_compatibility"][0]
        assert skip == {
            "target": "/project/.forge/sessions/ghost",
            "root": "/project",
            "state": "incompatible",
            "reason": "project requires Forge >=9999, but running Forge is 0.1.0",
            "recovery": "Run a Forge version satisfying required_forge, or edit/reset project state.",
        }


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

    def test_apply_reports_skip_and_exits_nonzero_after_eligible_cleanup(self) -> None:
        report = _make_report(total=2)
        clean_result = CleanResult(
            categories_cleaned={"proxies": 1},
            skipped_project_compatibility=[_compatibility_skip()],
        )
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean", return_value=clean_result),
        ):
            result = CliRunner().invoke(clean_cmd, ["--yes"])

        assert result.exit_code == 1
        assert "Cleaned 1 objects" in result.output
        assert "Skipped 1 project-owned item" in result.output
        assert "state: incompatible" in result.output

    def test_json_apply_reports_structured_skip_and_exits_nonzero(self) -> None:
        import json

        report = _make_report(total=2)
        clean_result = CleanResult(
            categories_cleaned={"proxies": 1},
            skipped_project_compatibility=[_compatibility_skip()],
        )
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean", return_value=clean_result),
        ):
            result = CliRunner().invoke(clean_cmd, ["--yes", "--json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["deleted"] == 1
        assert data["categories_cleaned"] == {"proxies": 1}
        assert data["skipped_project_compatibility"][0]["root"] == "/project"
        assert data["skipped_project_compatibility"][0]["state"] == "incompatible"

    def test_json_apply_reports_failure_and_exits_nonzero_with_clean_stderr(self) -> None:
        import json

        report = _make_report(total=1)
        clean_result = CleanResult(failed=[("/project/stale", "permission denied")])
        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch("forge.cli.gc.collect_clean_report", return_value=report),
            patch("forge.cli.gc.run_clean", return_value=clean_result),
        ):
            result = CliRunner().invoke(clean_cmd, ["--yes", "--json"])

        assert result.exit_code == 1
        assert result.stderr == ""
        data = json.loads(result.stdout)
        assert data["deleted"] == 0
        assert data["failed"] == [{"item": "/project/stale", "error": "permission denied"}]
        assert data["skipped_project_compatibility"] == []


class TestCleanCmdErrors:
    def test_scope_project_no_forge_root(self) -> None:
        from forge.core.ops.gc import CleanError

        with (
            patch("forge.cli.gc.ExecutionContext.from_cwd"),
            patch(
                "forge.cli.gc.collect_clean_report",
                side_effect=CleanError("Not inside a Forge project"),
            ),
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
