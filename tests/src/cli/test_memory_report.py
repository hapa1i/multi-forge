"""Tests for ``forge session memory report`` (memory writer report surface, Slice 02 flattened leaf)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from forge.cli.main import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _seed_session_with_reports(
    tmp_path: Path, session_name: str = "my-session", report_count: int = 0
) -> tuple[Path, list[Path]]:
    """Create a session in the index and seed N memory writer review files."""
    from forge.session import IndexStore

    forge_root = tmp_path / "project"
    (forge_root / ".forge" / "sessions" / session_name).mkdir(parents=True)
    (forge_root / ".forge" / "sessions" / session_name / "forge.session.json").write_text("{}")

    index = IndexStore()
    index.add_session(
        name=session_name,
        worktree_path=str(forge_root),
        project_root=str(tmp_path),
        forge_root=str(forge_root),
        checkout_root=str(forge_root),
        relative_path=".",
        is_incognito=False,
        is_fork=False,
        parent_session=None,
    )

    # Artifact path retains the ".../handoff/" segment (kept by design; see plan Phase 3).
    review = forge_root / ".forge" / "artifacts" / session_name / "handoff"
    review.mkdir(parents=True, exist_ok=True)
    reports: list[Path] = []
    for i in range(report_count):
        # Different timestamps so sorting is well-defined
        f = review / f"review-2026010{i}-120000.md"
        f.write_text(f"# Memory Writer Report\n\nrun {i}\n", encoding="utf-8")
        reports.append(f)
    return forge_root, reports


class TestShowCommand:
    def test_no_reports_emits_friendly_message(self, runner: CliRunner, tmp_path: Path) -> None:
        forge_root, _ = _seed_session_with_reports(tmp_path, "s1", report_count=0)
        from forge.session import SessionManager

        real_manager = SessionManager()
        with patch("forge.cli.memory_report.SessionManager", return_value=real_manager):
            with patch("forge.cli.memory_report._cwd_forge_root", return_value=forge_root):
                result = runner.invoke(main, ["session", "memory", "report", "s1"])
        assert result.exit_code == 0, result.output
        assert "No memory reports found" in result.output

    def test_shows_latest_by_default(self, runner: CliRunner, tmp_path: Path) -> None:
        forge_root, reports = _seed_session_with_reports(tmp_path, "s1", report_count=3)

        from forge.session import SessionManager

        real_manager = SessionManager()
        with patch("forge.cli.memory_report.SessionManager", return_value=real_manager):
            with patch("forge.cli.memory_report._cwd_forge_root", return_value=forge_root):
                result = runner.invoke(main, ["session", "memory", "report", "s1"])

        assert result.exit_code == 0, result.output
        # Latest is the highest-numbered (run 2)
        assert "run 2" in result.output
        # Path may be wrapped by Rich's word-wrap; normalize whitespace before checking
        normalized = "".join(result.output.split())
        assert reports[-1].name.replace("-", "") in normalized.replace("-", "")

    def test_all_flag_lists_each_report(self, runner: CliRunner, tmp_path: Path) -> None:
        forge_root, reports = _seed_session_with_reports(tmp_path, "s1", report_count=3)

        from forge.session import SessionManager

        real_manager = SessionManager()
        with patch("forge.cli.memory_report.SessionManager", return_value=real_manager):
            with patch("forge.cli.memory_report._cwd_forge_root", return_value=forge_root):
                result = runner.invoke(main, ["session", "memory", "report", "s1", "--all"])

        assert result.exit_code == 0, result.output
        for report in reports:
            assert report.name in result.output

    def test_latest_and_all_mutually_exclusive(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["session", "memory", "report", "s1", "--latest", "--all"])
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_no_session_name_outside_forge_project(self, runner: CliRunner, tmp_path: Path) -> None:
        from forge.session import SessionManager

        real_manager = SessionManager()
        with patch("forge.cli.memory_report.SessionManager", return_value=real_manager):
            with patch("forge.cli.memory_report._cwd_forge_root", return_value=None):
                result = runner.invoke(main, ["session", "memory", "report"])
        assert result.exit_code != 0
        assert "Not inside a Forge project" in result.output

    def test_no_session_name_prefers_forge_session_env(
        self, runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        forge_root, _ = _seed_session_with_reports(tmp_path, "current", report_count=1)
        _seed_session_with_reports(tmp_path, "other", report_count=1)
        monkeypatch.setenv("FORGE_SESSION", "current")
        monkeypatch.setenv("FORGE_FORGE_ROOT", str(forge_root))

        from forge.session import SessionManager

        real_manager = SessionManager()
        with patch("forge.cli.memory_report.SessionManager", return_value=real_manager):
            with patch("forge.cli.memory_report._cwd_forge_root", return_value=forge_root):
                result = runner.invoke(main, ["session", "memory", "report"])

        assert result.exit_code == 0, result.output
        assert "current" in result.output
        assert "run 0" in result.output


class TestReportJson:
    """``--json`` makes this read surface scriptable (Slice 02 read-debt resolved here, not deferred)."""

    def _run(self, runner: CliRunner, forge_root: Path, argv: list[str]) -> str:
        from forge.session import SessionManager

        real_manager = SessionManager()
        with patch("forge.cli.memory_report.SessionManager", return_value=real_manager):
            with patch("forge.cli.memory_report._cwd_forge_root", return_value=forge_root):
                result = runner.invoke(main, argv)
        assert result.exit_code == 0, result.output
        return result.output

    def test_latest_json_carries_path_and_content(self, runner: CliRunner, tmp_path: Path) -> None:
        forge_root, reports = _seed_session_with_reports(tmp_path, "s1", report_count=3)
        out = self._run(runner, forge_root, ["session", "memory", "report", "s1", "--json"])
        data = json.loads(out)
        assert data["session"] == "s1"
        assert data["report"]["name"] == reports[-1].name  # latest
        assert data["report"]["path"] == str(reports[-1])
        assert "run 2" in data["report"]["content"]

    def test_all_json_lists_every_report(self, runner: CliRunner, tmp_path: Path) -> None:
        forge_root, reports = _seed_session_with_reports(tmp_path, "s1", report_count=3)
        out = self._run(runner, forge_root, ["session", "memory", "report", "s1", "--all", "--json"])
        data = json.loads(out)
        assert data["session"] == "s1"
        names = [r["name"] for r in data["reports"]]
        assert names == [r.name for r in reports]  # oldest -> newest, all present
        assert all("path" in r for r in data["reports"])

    def test_no_reports_json_is_null_report(self, runner: CliRunner, tmp_path: Path) -> None:
        forge_root, _ = _seed_session_with_reports(tmp_path, "s1", report_count=0)
        out = self._run(runner, forge_root, ["session", "memory", "report", "s1", "--json"])
        data = json.loads(out)
        assert data["session"] == "s1"
        assert data["report"] is None  # structured empty, no human tip leaking into JSON
