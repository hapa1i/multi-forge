"""Tests for per-skill profile gating in the installer.

Verifies that SKILL_PROFILE_REQUIREMENTS gates skills at install time:
- QA skill excluded from standard profile (fresh install)
- QA skill included in full profile
- QA skill kept during update if already installed (skill-level, not file-level)
- New files in an already-installed gated skill are included (coherence)
- Unlisted skills always included when SKILLS module is enabled
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.install.installer import Installer
from forge.install.models import (
    TRACKING_VERSION,
    Installation,
    InstalledFile,
    InstalledManifest,
    InstallProfile,
    InstallScope,
)
from forge.install.tracking import TrackingStore


@pytest.fixture
def skill_installer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Installer, Path, Path, Path]:
    """Set up installer with skills in the source tree.

    Creates:
      src/skills/walkthrough/SKILL.md
      src/skills/qa/SKILL.md
      src/skills/qa/scripts/start-container.sh
      src/commands/test.md
    """
    forge_home = tmp_path / ".forge"
    forge_home.mkdir()

    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))

    src = tmp_path / "src"
    (src / "forge").mkdir(parents=True)  # _is_repo_checkout requires src/forge

    # Commands (needed for profile resolution)
    commands = src / "commands"
    commands.mkdir(parents=True)
    (commands / "test.md").write_text("# Test\n")

    # Skills: walkthrough (no profile requirement)
    wt = src / "skills" / "walkthrough"
    wt.mkdir(parents=True)
    (wt / "SKILL.md").write_text(
        "---\nname: forge:walkthrough\ndescription: Test walkthrough skill\n---\n# Walkthrough\n"
    )

    # Skills: qa (requires full profile)
    qa = src / "skills" / "qa"
    qa.mkdir(parents=True)
    (qa / "SKILL.md").write_text("---\nname: forge:qa\ndescription: Test QA skill\n---\n# QA\n")
    qa_scripts = qa / "scripts"
    qa_scripts.mkdir()
    (qa_scripts / "start-container.sh").write_text("#!/bin/bash\n")

    tracking = TrackingStore(tracking_path=forge_home / "installed.json")
    installer = Installer(scope=InstallScope.USER, tracking_store=tracking)

    return installer, forge_home, claude_home, src


class TestSkillProfileFiltering:
    """Verify per-skill profile gating in _plan()."""

    def test_qa_skill_excluded_from_standard_profile(self, skill_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Standard profile should not include qa/ skill files."""
        installer, _, claude_home, src = skill_installer

        with (
            patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
            patch("forge.install.installer.get_target_root", return_value=claude_home),
        ):
            plan = installer.plan(profile=InstallProfile.STANDARD)

        qa_files = [f for f in plan.files if "/skills/qa/" in f.target_path]
        assert qa_files == [], f"qa files should be excluded: {[f.target_path for f in qa_files]}"

    def test_qa_skill_included_in_full_profile(self, skill_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Full profile should include qa/ skill files."""
        installer, _, claude_home, src = skill_installer

        with (
            patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
            patch("forge.install.installer.get_target_root", return_value=claude_home),
        ):
            plan = installer.plan(profile=InstallProfile.FULL)

        qa_files = [f for f in plan.files if "/skills/qa/" in f.target_path]
        assert len(qa_files) >= 2, f"Expected qa files in plan, got: {[f.target_path for f in qa_files]}"

    def test_qa_skill_updated_if_already_installed(self, skill_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Standard profile should keep ALL qa files when the skill is in the manifest."""
        installer, forge_home, claude_home, src = skill_installer

        # Pre-populate manifest with one qa file (simulating previous full install)
        qa_target = str(claude_home / "skills" / "qa" / "SKILL.md")
        existing = Installation(
            scope="user",
            mode="copy",
            profile="full",
            modules_enabled=["commands", "skills"],
            files=[
                InstalledFile(
                    target_path=qa_target,
                    source_path=str(src / "skills" / "qa" / "SKILL.md"),
                    checksum="abc123",
                    mode="copy",
                    installed_at="2024-01-01T00:00:00+00:00",
                ),
            ],
            installed_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        manifest = InstalledManifest(version=TRACKING_VERSION, installations={"user": existing})
        tracking_path = forge_home / "installed.json"
        tracking_path.write_text(
            json.dumps(
                {
                    "version": manifest.version,
                    "installations": {
                        "user": {
                            "scope": existing.scope,
                            "mode": existing.mode,
                            "profile": existing.profile,
                            "project_path": existing.project_path,
                            "modules_enabled": existing.modules_enabled,
                            "files": [
                                {
                                    "target_path": f.target_path,
                                    "source_path": f.source_path,
                                    "checksum": f.checksum,
                                    "mode": f.mode,
                                    "installed_at": f.installed_at,
                                }
                                for f in existing.files
                            ],
                            "settings_entries": [],
                            "settings_backup_path": None,
                            "installed_at": existing.installed_at,
                            "updated_at": existing.updated_at,
                        },
                    },
                }
            )
        )

        with (
            patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
            patch("forge.install.installer.get_target_root", return_value=claude_home),
        ):
            # Plan with standard profile — ALL qa files should appear
            # because the skill is already installed (skill-level check)
            plan = installer.plan(profile=InstallProfile.STANDARD)

        qa_files = [f for f in plan.files if "/skills/qa/" in f.target_path]
        # Skill-level gating: all qa files included (SKILL.md + scripts/start-container.sh)
        assert len(qa_files) >= 2, (
            f"All qa files should be included when skill is installed: " f"{[f.target_path for f in qa_files]}"
        )

    def test_new_file_in_installed_skill_included(self, skill_installer: tuple[Installer, Path, Path, Path]) -> None:
        """A new file added to an already-installed gated skill should be planned."""
        installer, forge_home, claude_home, src = skill_installer

        # Add a new file to qa/ source (simulating a new release adding a resource)
        new_resource = src / "skills" / "qa" / "resources"
        new_resource.mkdir(parents=True)
        (new_resource / "checklist.md").write_text("# Checklist\n")

        # Manifest only has the original SKILL.md — the new file is NOT tracked
        qa_target = str(claude_home / "skills" / "qa" / "SKILL.md")
        existing = Installation(
            scope="user",
            mode="copy",
            profile="full",
            modules_enabled=["commands", "skills"],
            files=[
                InstalledFile(
                    target_path=qa_target,
                    source_path=str(src / "skills" / "qa" / "SKILL.md"),
                    checksum="abc123",
                    mode="copy",
                    installed_at="2024-01-01T00:00:00+00:00",
                ),
            ],
            installed_at="2024-01-01T00:00:00+00:00",
            updated_at="2024-01-01T00:00:00+00:00",
        )
        tracking_path = forge_home / "installed.json"
        tracking_path.write_text(
            json.dumps(
                {
                    "version": TRACKING_VERSION,
                    "installations": {
                        "user": {
                            "scope": existing.scope,
                            "mode": existing.mode,
                            "profile": existing.profile,
                            "project_path": existing.project_path,
                            "modules_enabled": existing.modules_enabled,
                            "files": [
                                {
                                    "target_path": f.target_path,
                                    "source_path": f.source_path,
                                    "checksum": f.checksum,
                                    "mode": f.mode,
                                    "installed_at": f.installed_at,
                                }
                                for f in existing.files
                            ],
                            "settings_entries": [],
                            "settings_backup_path": None,
                            "installed_at": existing.installed_at,
                            "updated_at": existing.updated_at,
                        },
                    },
                }
            )
        )

        with (
            patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
            patch("forge.install.installer.get_target_root", return_value=claude_home),
        ):
            plan = installer.plan(profile=InstallProfile.STANDARD)

        qa_files = [f for f in plan.files if "/skills/qa/" in f.target_path]
        qa_paths = [f.target_path for f in qa_files]
        # The new resource should be included even though it wasn't in the manifest
        assert any(
            "checklist.md" in p for p in qa_paths
        ), f"New file in already-installed skill should be included: {qa_paths}"

    def test_unlisted_skills_always_included(self, skill_installer: tuple[Installer, Path, Path, Path]) -> None:
        """Skills not in SKILL_PROFILE_REQUIREMENTS install with any profile that has SKILLS."""
        installer, _, claude_home, src = skill_installer

        with (
            patch("forge.install.installer.get_forge_source_root", return_value=src.parent),
            patch("forge.install.installer.get_target_root", return_value=claude_home),
        ):
            plan = installer.plan(profile=InstallProfile.STANDARD)

        wt_files = [f for f in plan.files if "/skills/walkthrough/" in f.target_path]
        assert len(wt_files) >= 1, f"walkthrough skill should be included: {[f.target_path for f in plan.files]}"
