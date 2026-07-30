"""Schema-v3 ownership migration and invariant acceptance tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge.install.exceptions import TrackingCorruptedError
from forge.install.models import (
    Installation,
    InstalledSkillPackage,
    UnattributedSurface,
)
from forge.install.ownership import attributed, attribution_pair
from forge.install.tracking import TrackingStore

FIXTURES = Path(__file__).parents[2] / "fixtures" / "install"
CLAUDE = "claude_code"
CODEX = "codex"


def _expanded_fixture(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], Path, Path, Path]:
    claude_home = tmp_path / "claude"
    codex_home = tmp_path / "codex"
    codex_skills = tmp_path / "home" / ".agents" / "skills"
    monkeypatch.setenv("CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for token, value in {
        "__CLAUDE_HOME__": claude_home,
        "__CODEX_HOME__": codex_home,
        "__CODEX_SKILLS__": codex_skills,
    }.items():
        text = text.replace(token, str(value))
    return json.loads(text), claude_home, codex_home, codex_skills


def _write_payload(store: TrackingStore, payload: dict[str, Any]) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _file_summary(installation: Installation) -> list[tuple[str, str, str, str, str, object]]:
    return [
        (
            record.target_path,
            record.source_path,
            record.checksum,
            record.mode,
            record.installed_at,
            record.attribution,
        )
        for record in installation.files
    ]


def _settings_summary(installation: Installation) -> list[tuple[str, object, str, str, object]]:
    return [
        (
            record.key_path,
            record.value,
            record.merge_type,
            record.stable_id,
            record.attribution,
        )
        for record in installation.settings_entries
    ]


def test_v1_fixture_migrates_field_by_field_without_rewriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, claude_home, codex_home, _ = _expanded_fixture("installed_v1.json", tmp_path, monkeypatch)
    store = TrackingStore(tmp_path / "tracking" / "installed.json")
    _write_payload(store, payload)
    original = store.path.read_bytes()

    manifest = store.read()

    assert manifest.version == 3
    installation = manifest.installations["user"]
    assert (
        installation.scope,
        installation.project_path,
        installation.mode,
        installation.profile,
        installation.settings_backup_path,
        installation.codex_config_path,
        installation.codex_commands,
        installation.installed_at,
        installation.updated_at,
    ) == (
        "user",
        None,
        "copy",
        "standard",
        str(claude_home / "settings.json.forge-backup"),
        str(codex_home / "config.toml"),
        ["forge-hook codex-session-start"],
        "2026-07-01T00:00:00Z",
        "2026-07-01T00:00:03Z",
    )
    assert installation.module_owners == sorted(
        [
            attributed("commands", CLAUDE),
            attributed("hooks", CLAUDE),
            attributed("hooks", CODEX),
            attributed("permissions", CLAUDE),
            attributed("skills", CLAUDE),
        ]
    )
    assert _file_summary(installation) == [
        (
            str(claude_home / "commands" / "review.md"),
            "/fixture/src/commands/review.md",
            "command-checksum",
            "copy",
            "2026-07-01T00:00:00Z",
            attributed("commands", CLAUDE),
        ),
        (
            str(claude_home / "skills" / "portable" / "SKILL.md"),
            "/fixture/src/skills/portable/SKILL.md",
            "skill-checksum",
            "copy",
            "2026-07-01T00:00:01Z",
            attributed("skills", CLAUDE),
        ),
        (
            "/opaque/legacy.bin",
            "/fixture/src/opaque.bin",
            "opaque-checksum",
            "copy",
            "2026-07-01T00:00:02Z",
            UnattributedSurface("legacy_path_unmapped"),
        ),
    ]
    assert installation.skill_packages == [
        InstalledSkillPackage(
            runtime=CLAUDE,
            skill="portable",
            target_dir=str(claude_home / "skills" / "portable"),
            file_paths=[str(claude_home / "skills" / "portable" / "SKILL.md")],
        )
    ]
    assert _settings_summary(installation) == [
        (
            "hooks.SessionStart",
            {"hooks": [{"type": "command", "command": "forge-hook session-start"}]},
            "append",
            "legacy-hook",
            attributed("hooks", CLAUDE),
        ),
        ("permissions.allow", "Read", "union", "Read", attributed("permissions", CLAUDE)),
        (
            "future.setting",
            "private-value",
            "scalar",
            "future.setting",
            UnattributedSurface("legacy_key_unmapped"),
        ),
    ]
    assert store.path.read_bytes() == original


def test_v2_fixture_migrates_field_by_field_without_live_v3_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, claude_home, codex_home, codex_skills = _expanded_fixture(
        "installed_v2.json",
        tmp_path,
        monkeypatch,
    )
    store = TrackingStore(tmp_path / "tracking" / "installed.json")
    _write_payload(store, payload)
    original = store.path.read_bytes()

    manifest = store.read()

    assert manifest.version == 3
    installation = manifest.installations["user"]
    assert (
        installation.scope,
        installation.project_path,
        installation.mode,
        installation.profile,
        installation.settings_backup_path,
        installation.codex_config_path,
        installation.codex_commands,
        installation.installed_at,
        installation.updated_at,
    ) == (
        "user",
        None,
        "copy",
        "full",
        str(claude_home / "settings.json.forge-backup"),
        str(codex_home / "config.toml"),
        ["forge-hook codex-policy-check", "forge-hook codex-session-start"],
        "2026-07-02T00:00:00Z",
        "2026-07-02T00:00:05Z",
    )
    assert installation.module_owners == sorted(
        [
            attributed("agents", CLAUDE),
            attributed("commands", CLAUDE),
            attributed("hooks", CLAUDE),
            attributed("hooks", CODEX),
            attributed("permissions", CLAUDE),
            attributed("skills", CLAUDE),
            attributed("skills", CODEX),
            attributed("status-line", CLAUDE),
        ]
    )
    expected_paths_and_attribution = [
        (str(claude_home / "commands" / "review.md"), attributed("commands", CLAUDE)),
        (str(claude_home / "agents" / "reviewer.md"), attributed("agents", CLAUDE)),
        (str(claude_home / "skills" / "portable" / "SKILL.md"), attributed("skills", CLAUDE)),
        (str(codex_skills / "portable" / "SKILL.md"), attributed("skills", CODEX)),
        ("/opaque/v2.bin", UnattributedSurface("legacy_path_unmapped")),
    ]
    assert [(record.target_path, record.attribution) for record in installation.files] == (
        expected_paths_and_attribution
    )
    assert installation.skill_packages == [
        InstalledSkillPackage(
            runtime=CLAUDE,
            skill="portable",
            target_dir=str(claude_home / "skills" / "portable"),
            file_paths=[str(claude_home / "skills" / "portable" / "SKILL.md")],
        ),
        InstalledSkillPackage(
            runtime=CODEX,
            skill="portable",
            target_dir=str(codex_skills / "portable"),
            file_paths=[str(codex_skills / "portable" / "SKILL.md")],
        ),
    ]
    assert [record.attribution for record in installation.settings_entries] == [
        attributed("hooks", CLAUDE),
        attributed("status-line", CLAUDE),
        attributed("permissions", CLAUDE),
        attributed("permissions", CLAUDE),
        UnattributedSurface("legacy_key_unmapped"),
    ]
    assert [record.key_path for record in installation.settings_entries] == [
        "hooks.SessionStart",
        "statusLine",
        "permissions.allow",
        "env.FORGE_ENABLED",
        "future.setting",
    ]
    assert store.path.read_bytes() == original


def test_unknown_legacy_module_remains_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, *_ = _expanded_fixture("installed_v2.json", tmp_path, monkeypatch)
    payload["installations"]["user"]["modules_enabled"].append("future-module")
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match=r"unknown module value\(s\).*'future-module'"):
        store.read()


def _current_payload() -> dict[str, Any]:
    return {
        "version": 3,
        "installations": {
            "user": {
                "scope": "user",
                "mode": "copy",
                "profile": "minimal",
                "module_owners": [{"module": "commands", "runtime": CLAUDE}],
                "files": [
                    {
                        "target_path": "/managed/commands/review.md",
                        "source_path": "/source/commands/review.md",
                        "checksum": "abc",
                        "mode": "copy",
                        "installed_at": "2026-07-03T00:00:00Z",
                        "attribution": {"module": "commands", "runtime": CLAUDE},
                    }
                ],
            }
        },
    }


@pytest.mark.parametrize(
    ("owner", "message"),
    [
        ({"module": "future-module", "runtime": CLAUDE}, "unknown module value"),
        ({"module": "commands", "runtime": CODEX}, "cannot be owned by runtime"),
    ],
)
def test_v3_rejects_invalid_owner_pairs(
    tmp_path: Path,
    owner: dict[str, str],
    message: str,
) -> None:
    payload = _current_payload()
    payload["installations"]["user"]["module_owners"] = [owner]
    payload["installations"]["user"]["files"] = []
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match=message):
        store.read()


@pytest.mark.parametrize(
    "owners",
    [
        [
            {"module": "commands", "runtime": CLAUDE},
            {"module": "commands", "runtime": CLAUDE},
        ],
        [
            {"module": "skills", "runtime": CODEX},
            {"module": "skills", "runtime": CLAUDE},
        ],
    ],
    ids=["duplicate", "unsorted"],
)
def test_v3_rejects_noncanonical_owner_relation(
    tmp_path: Path,
    owners: list[dict[str, str]],
) -> None:
    payload = _current_payload()
    payload["installations"]["user"]["module_owners"] = owners
    payload["installations"]["user"]["files"] = []
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match="module_owners must be unique and sorted"):
        store.read()


@pytest.mark.parametrize(
    "attribution",
    [
        {},
        {"module": "commands", "runtime": CLAUDE, "unattributed_reason": "legacy_path_unmapped"},
    ],
    ids=["empty", "both-tag-forms"],
)
def test_v3_requires_exactly_one_tagged_attribution_form(
    tmp_path: Path,
    attribution: dict[str, str],
) -> None:
    payload = _current_payload()
    payload["installations"]["user"]["files"][0]["attribution"] = attribution
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match="deserialization error"):
        store.read()


def test_v3_rejects_duplicate_file_identity_claimed_by_two_pairs(tmp_path: Path) -> None:
    payload = _current_payload()
    installation = payload["installations"]["user"]
    installation["module_owners"] = [
        {"module": "agents", "runtime": CLAUDE},
        {"module": "commands", "runtime": CLAUDE},
    ]
    second = dict(installation["files"][0])
    second["attribution"] = {"module": "agents", "runtime": CLAUDE}
    installation["files"].append(second)
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match="duplicates file row identity"):
        store.read()


def test_v3_rejects_skill_package_without_matching_owner_pair(tmp_path: Path) -> None:
    payload = _current_payload()
    installation = payload["installations"]["user"]
    target_dir = "/managed/skills/portable"
    skill_path = f"{target_dir}/SKILL.md"
    installation["files"][0]["target_path"] = skill_path
    installation["skill_packages"] = [
        {
            "runtime": CODEX,
            "skill": "portable",
            "target_dir": target_dir,
            "file_paths": [skill_path],
        }
    ]
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match="has no matching skills owner pair"):
        store.read()


@pytest.mark.parametrize(
    ("codex_owner", "codex_path"),
    [(True, None), (False, "/managed/codex/config.toml")],
    ids=["owner-without-path", "path-without-owner"],
)
def test_v3_requires_codex_hook_owner_iff_config_path(
    tmp_path: Path,
    codex_owner: bool,
    codex_path: str | None,
) -> None:
    payload = _current_payload()
    installation = payload["installations"]["user"]
    installation["files"] = []
    installation["module_owners"] = [{"module": "hooks", "runtime": CODEX}] if codex_owner else []
    installation["codex_config_path"] = codex_path
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match="must own hooks/codex iff codex_config_path is set"):
        store.read()


def test_legacy_unattributed_row_stays_readable_but_has_no_removal_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload, *_ = _expanded_fixture("installed_v1.json", tmp_path, monkeypatch)
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)
    migrated = store.read()
    opaque = next(
        record for record in migrated.installations["user"].files if record.target_path == "/opaque/legacy.bin"
    )

    assert isinstance(opaque.attribution, UnattributedSurface)
    assert attribution_pair(opaque.attribution) is None

    store.write(migrated)
    reread = store.read()
    persisted = next(
        record for record in reread.installations["user"].files if record.target_path == "/opaque/legacy.bin"
    )
    assert persisted.attribution == opaque.attribution
    assert json.loads(store.path.read_text(encoding="utf-8"))["version"] == 3


def test_v3_rejects_unknown_unattributed_reason(tmp_path: Path) -> None:
    payload = _current_payload()
    payload["installations"]["user"]["module_owners"] = []
    payload["installations"]["user"]["files"][0]["attribution"] = {"unattributed_reason": "future_reason"}
    store = TrackingStore(tmp_path / "installed.json")
    _write_payload(store, payload)

    with pytest.raises(TrackingCorruptedError, match="unknown unattributed reason"):
        store.read()
