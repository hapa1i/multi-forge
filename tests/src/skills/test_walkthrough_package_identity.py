"""Tests for walkthrough package provenance reporting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "src/skills/walkthrough/scripts/package-identity.py"


def _module():
    spec = importlib.util.spec_from_file_location("walkthrough_package_identity_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package(parent: Path) -> Path:
    root = parent / "walkthrough-package"
    root.mkdir()
    skill = b"---\nname: walkthrough\n---\n"
    (root / "SKILL.md").write_bytes(skill)
    (root / ".forge-package.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "producer": "multi-forge",
                "runtime": "claude_code",
                "skill": "walkthrough",
                "files": [
                    {
                        "path": "SKILL.md",
                        "sha256": hashlib.sha256(skill).hexdigest(),
                        "mode": 0o644,
                    }
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return root


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--skill-root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_reports_distribution_and_exact_package_tree(tmp_path: Path) -> None:
    root = _package(tmp_path)

    marker_digest, payload_digest, matches, mismatches = _module().verify_skill_root(root)

    assert marker_digest.startswith("sha256:")
    assert payload_digest.startswith("sha256:")
    assert matches is True
    assert mismatches == []


def test_fails_when_installed_payload_differs_from_marker(tmp_path: Path) -> None:
    root = _package(tmp_path)
    (root / "SKILL.md").write_text("changed\n")

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert mismatches == ["SKILL.md"]


def test_fails_when_installed_tree_contains_unexpected_directory_symlink(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (root / "unexpected-link").symlink_to(target, target_is_directory=True)

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert mismatches == ["unexpected-link"]


def test_cli_rejects_a_symlinked_exact_tree_skill_root(tmp_path: Path) -> None:
    root = _package(tmp_path)
    alias = tmp_path / "walkthrough-alias"
    alias.symlink_to(root, target_is_directory=True)

    result = _run(alias)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["skill_root"] == str(alias)
    assert payload["package_tree_matches_marker"] is False
    assert payload["mismatches"] == ["."]


def test_fails_when_marker_contains_noncanonical_fields(tmp_path: Path) -> None:
    root = _package(tmp_path)
    marker = root / ".forge-package.json"
    payload = json.loads(marker.read_text())
    payload["unexpected"] = True
    marker.write_text(json.dumps(payload) + "\n")

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert "marker_schema" in mismatches


def test_fails_when_marker_schema_version_is_a_numeric_float(tmp_path: Path) -> None:
    root = _package(tmp_path)
    marker = root / ".forge-package.json"
    payload = json.loads(marker.read_text())
    payload["schema_version"] = 1.0
    marker.write_text(json.dumps(payload) + "\n")

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert "marker_identity" in mismatches


def test_fails_when_package_contains_an_unexpected_empty_directory(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path)
    (root / "unexpected-dir").mkdir()

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert mismatches == ["unexpected-dir/"]


def test_fails_when_package_contains_a_special_filesystem_entry(tmp_path: Path) -> None:
    root = _package(tmp_path)
    os.mkfifo(root / "unexpected-fifo")

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert mismatches == ["unexpected-fifo"]


def test_fails_without_following_a_symlinked_package_marker(tmp_path: Path) -> None:
    root = _package(tmp_path)
    marker = root / ".forge-package.json"
    external = tmp_path / "external-marker.json"
    marker.replace(external)
    marker.symlink_to(external)

    _, _, matches, mismatches = _module().verify_skill_root(root)

    assert matches is False
    assert mismatches == [".forge-package.json"]


def test_marker_replacement_race_fails_without_following_the_new_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _package(tmp_path)
    marker = root / ".forge-package.json"
    external = tmp_path / "replacement-marker.json"
    real_open = os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if not replaced and path == ".forge-package.json" and kwargs.get("dir_fd") is not None:
            marker.replace(external)
            marker.symlink_to(external)
            replaced = True
        return real_open(path, flags, *args, **kwargs)

    module = _module()
    monkeypatch.setattr(module.os, "open", replace_before_open)

    _, _, matches, mismatches = module.verify_skill_root(root)

    assert replaced is True
    assert matches is False
    assert mismatches == [".forge-package.json"]


def test_payload_replacement_race_fails_without_following_the_new_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _package(tmp_path)
    payload = root / "SKILL.md"
    original = tmp_path / "original-SKILL.md"
    external = tmp_path / "replacement-SKILL.md"
    external.write_bytes(payload.read_bytes())
    real_open = os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if not replaced and path == "SKILL.md" and kwargs.get("dir_fd") is not None:
            payload.replace(original)
            payload.symlink_to(external)
            replaced = True
        return real_open(path, flags, *args, **kwargs)

    module = _module()
    monkeypatch.setattr(module.os, "open", replace_before_open)

    _, _, matches, mismatches = module.verify_skill_root(root)

    assert replaced is True
    assert matches is False
    assert "SKILL.md" in mismatches


def test_directory_replacement_race_fails_without_following_the_new_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _package(tmp_path)
    nested = root / "resources"
    nested.mkdir()
    payload = b"same packaged bytes\n"
    (nested / "guide.md").write_bytes(payload)

    marker = root / ".forge-package.json"
    marker_data = json.loads(marker.read_text())
    marker_data["files"].append(
        {
            "path": "resources/guide.md",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "mode": 0o644,
        }
    )
    marker.write_text(json.dumps(marker_data, sort_keys=True, separators=(",", ":")) + "\n")

    original = tmp_path / "original-resources"
    external = tmp_path / "external-resources"
    external.mkdir()
    (external / "guide.md").write_bytes(payload)
    real_open = os.open
    replaced = False

    def replace_before_directory_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if (
            not replaced
            and path == "resources"
            and kwargs.get("dir_fd") is not None
            and flags & getattr(os, "O_DIRECTORY", 0)
        ):
            nested.replace(original)
            nested.symlink_to(external, target_is_directory=True)
            replaced = True
        return real_open(path, flags, *args, **kwargs)

    module = _module()
    monkeypatch.setattr(module.os, "open", replace_before_directory_open)

    _, _, matches, mismatches = module.verify_skill_root(root)

    assert replaced is True
    assert matches is False
    assert "resources/" in mismatches
    assert nested.is_symlink()


def test_package_root_replacement_race_fails_after_traversing_the_opened_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _package(tmp_path)
    external_parent = tmp_path / "external-parent"
    external_parent.mkdir()
    external = _package(external_parent)
    original = tmp_path / "original-package"
    real_scandir = os.scandir
    replaced = False

    def replace_before_root_scan(path):
        nonlocal replaced
        if not replaced and isinstance(path, int):
            root.replace(original)
            root.symlink_to(external, target_is_directory=True)
            replaced = True
        return real_scandir(path)

    module = _module()
    monkeypatch.setattr(module.os, "scandir", replace_before_root_scan)

    _, _, matches, mismatches = module.verify_skill_root(root)

    assert replaced is True
    assert matches is False
    assert "." in mismatches
    assert root.is_symlink()


def test_cli_reports_malformed_marker_json_without_a_traceback(tmp_path: Path) -> None:
    root = _package(tmp_path)
    (root / ".forge-package.json").write_text("{not json\n", encoding="utf-8")

    result = _run(root)

    assert result.returncode == 2
    assert result.stdout == ""
    assert json.loads(result.stderr) == {"status": "error", "reason": "JSONDecodeError"}


def test_cli_refuses_a_valid_marker_from_another_answering_distribution(
    tmp_path: Path,
) -> None:
    root = _package(tmp_path)

    result = _run(root)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["package_tree_matches_marker"] is True
    assert payload["package_matches_answering_distribution"] is False


def test_answering_distribution_uses_the_forge_launcher_interpreter(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    launcher = tmp_path / "forge"
    launcher.write_text("#!/opt/answering-forge/bin/python\n")
    observed: list[str] = []

    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command: str(launcher) if command == "forge" else None,
    )

    def fake_run(argv, **kwargs):
        observed.extend(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "distribution": "multi-forge",
                    "version": "1.0.0",
                    "distribution_root": "/opt/answering-forge/lib/python/site-packages",
                    "forge_module": "/opt/answering-forge/lib/python/site-packages/forge/__init__.py",
                    "walkthrough_source_root": "/opt/answering-forge/lib/python/site-packages/forge/_extensions/skills/walkthrough",
                    "walkthrough_payload_sha256": "sha256:answering",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module.answering_distribution()

    assert observed[0] == "/opt/answering-forge/bin/python"
    assert result["version"] == "1.0.0"
    assert result["forge_launcher"] == str(launcher.resolve())


def test_editable_answering_distribution_is_explicitly_ineligible(tmp_path: Path, monkeypatch) -> None:
    module = _module()
    launcher = tmp_path / "forge"
    launcher.write_text(f"#!{sys.executable}\n")
    monkeypatch.setattr(
        module.shutil,
        "which",
        lambda command: str(launcher) if command == "forge" else None,
    )

    result = module.answering_distribution()

    assert result["answering_distribution_kind"] == "editable"
    assert result["answering_distribution_issue"] == "editable-install"
    assert result["walkthrough_payload_present"] is False
    assert result["walkthrough_payload_sha256"] is None
