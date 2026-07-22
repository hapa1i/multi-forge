"""Regression for stale pre-marker Codex packages hidden by lost tracking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from forge.cli.extensions import extensions
from forge.core.ops.context import ExecutionContext
from forge.core.ops.gc import collect_clean_report

pytestmark = pytest.mark.regression


def test_untracked_pre_marker_user_package_is_visible_but_never_cleanable(tmp_path: Path) -> None:
    package = Path.home() / ".agents" / "skills" / "understand"
    package.mkdir(parents=True)
    (package / "SKILL.md").write_text("stale pre-marker Forge output\n", encoding="utf-8")

    status = CliRunner().invoke(extensions, ["status", "--scope", "user", "--json"])

    assert status.exit_code == 0, status.output
    payload = json.loads(status.stdout)
    assert payload["schema_version"] == 2
    assert payload["installations"] == []
    assert len(payload["unmanaged_skill_packages"]) == 1
    unmanaged = payload["unmanaged_skill_packages"][0]
    assert unmanaged["runtime"] == "codex"
    assert unmanaged["skill"] == "understand"
    assert unmanaged["target_dir"] == str(package)
    assert unmanaged["provenance"] == "unmarked"
    assert unmanaged["cleanup_eligible"] is False
    assert unmanaged["cleanup_scope"] is None
    assert f"Remove or rename {package}" in unmanaged["recovery"]
    assert "forge clean" not in unmanaged["recovery"]

    (tmp_path / ".forge").mkdir()
    ctx = ExecutionContext(
        cwd=tmp_path,
        worktree_root=tmp_path,
        project_root=tmp_path,
        forge_root=tmp_path,
    )
    for scope in ("project", "workspace", "all"):
        report = collect_clean_report(ctx=ctx, scope=scope)
        clean_category = next(
            category for category in report.categories if category.category == "unmanaged_skill_packages"
        )
        assert str(package) not in clean_category.items
    assert package.is_dir()
