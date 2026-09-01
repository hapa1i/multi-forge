"""Tests for walkthrough package provenance reporting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "src/skills/walkthrough/scripts/package-identity.py"


def _module():
    spec = importlib.util.spec_from_file_location("walkthrough_package_identity_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _package(root: Path) -> None:
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


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT), "--skill-root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_reports_distribution_and_exact_package_tree(tmp_path: Path) -> None:
    _package(tmp_path)

    marker_digest, payload_digest, matches, mismatches = _module().verify_skill_root(tmp_path)

    assert marker_digest.startswith("sha256:")
    assert payload_digest.startswith("sha256:")
    assert matches is True
    assert mismatches == []


def test_fails_when_installed_payload_differs_from_marker(tmp_path: Path) -> None:
    _package(tmp_path)
    (tmp_path / "SKILL.md").write_text("changed\n")

    _, _, matches, mismatches = _module().verify_skill_root(tmp_path)

    assert matches is False
    assert mismatches == ["SKILL.md"]


def test_fails_when_installed_tree_contains_unexpected_directory_symlink(
    tmp_path: Path,
) -> None:
    _package(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "unexpected-link").symlink_to(target, target_is_directory=True)

    _, _, matches, mismatches = _module().verify_skill_root(tmp_path)

    assert matches is False
    assert mismatches == ["unexpected-link"]


def test_cli_refuses_a_valid_marker_from_another_answering_distribution(
    tmp_path: Path,
) -> None:
    _package(tmp_path)

    result = _run(tmp_path)

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
