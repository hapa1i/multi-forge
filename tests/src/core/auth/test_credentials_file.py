"""Tests for file-based credential store (~/.forge/credentials.yaml)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import yaml

from forge.core.auth.credentials_file import (
    SCHEMA_VERSION,
    CredentialVersionError,
    _validate_profile_name,
    delete_profile,
    get_credentials_path,
    list_profiles,
    load_credentials,
    load_profile,
    resolve_profile,
    save_profile,
)

# --- Path resolution ---


def test_get_credentials_path_uses_forge_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FORGE_HOME", str(tmp_path))
    assert get_credentials_path() == tmp_path / "credentials.yaml"


# --- Profile resolution ---


def test_resolve_profile_explicit() -> None:
    assert resolve_profile("work") == "work"


def test_resolve_profile_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_PROFILE", "corporate")
    assert resolve_profile() == "corporate"


def test_resolve_profile_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORGE_PROFILE", raising=False)
    assert resolve_profile() == "default"


def test_resolve_profile_explicit_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_PROFILE", "corporate")
    assert resolve_profile("personal") == "personal"


# --- Profile name validation ---


@pytest.mark.parametrize("name", ["default", "work", "my-profile", "test_123", "A"])
def test_validate_profile_name_valid(name: str) -> None:
    _validate_profile_name(name)  # Should not raise


@pytest.mark.parametrize(
    "name",
    [
        "",
        "has space",
        "path/sep",
        "back\\slash",
        "../traversal",
        "special!char",
        "tab\there",
        "新",
    ],
)
def test_validate_profile_name_invalid(name: str) -> None:
    with pytest.raises(ValueError, match="Invalid profile name"):
        _validate_profile_name(name)


# --- load_credentials ---


def test_load_credentials_missing_file(tmp_path: Path) -> None:
    result = load_credentials(tmp_path / "nonexistent.yaml")
    assert result == {}


def test_load_credentials_empty_file(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text("")
    assert load_credentials(creds) == {}


def test_load_credentials_valid(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(
        yaml.dump(
            {
                "version": 1,
                "profiles": {
                    "default": {"ANTHROPIC_API_KEY": "sk-ant-test"},
                    "work": {"LITELLM_API_KEY": "sk-lm-test", "GEMINI_AUTH_URL": "https://auth.example.com"},
                },
            }
        )
    )
    result = load_credentials(creds)
    assert result == {
        "default": {"ANTHROPIC_API_KEY": "sk-ant-test"},
        "work": {"LITELLM_API_KEY": "sk-lm-test", "GEMINI_AUTH_URL": "https://auth.example.com"},
    }


def test_load_credentials_no_profiles_key(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 1}))
    assert load_credentials(creds) == {}


def test_load_credentials_corrupt_yaml(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text("{{invalid yaml: [")
    with pytest.raises(ValueError, match="Corrupt credentials file"):
        load_credentials(creds)


def test_load_credentials_corrupt_recovery_message(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text("{{invalid")
    with pytest.raises(ValueError, match="forge auth login"):
        load_credentials(creds)


def test_load_credentials_not_a_mapping(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text("- a list\n- not a mapping\n")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_credentials(creds)


def test_load_credentials_profiles_not_a_mapping(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 1, "profiles": "not-a-dict"}))
    with pytest.raises(ValueError, match="'profiles' must be a mapping"):
        load_credentials(creds)


def test_load_credentials_profile_value_not_a_mapping(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 1, "profiles": {"bad": "string-not-dict"}}))
    with pytest.raises(ValueError, match="Profile 'bad' must be a mapping"):
        load_credentials(creds)


def test_load_credentials_non_string_value(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 1, "profiles": {"default": {"KEY": 12345}}}))
    with pytest.raises(ValueError, match="must be a string"):
        load_credentials(creds)


def test_load_credentials_unknown_version(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 99, "profiles": {"default": {"KEY": "val"}}}))
    with pytest.raises(CredentialVersionError, match="version 99"):
        load_credentials(creds)


def test_load_credentials_missing_version_ok(tmp_path: Path) -> None:
    """Files without version field are tolerated (pre-versioned files)."""
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"profiles": {"default": {"KEY": "val"}}}))
    result = load_credentials(creds)
    assert result == {"default": {"KEY": "val"}}


def test_load_credentials_current_version_ok(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": SCHEMA_VERSION, "profiles": {"default": {"KEY": "val"}}}))
    result = load_credentials(creds)
    assert result == {"default": {"KEY": "val"}}


# --- load_profile ---


def test_load_profile_existing(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 1, "profiles": {"default": {"API_KEY": "test"}}}))
    assert load_profile("default", path=creds) == {"API_KEY": "test"}


def test_load_profile_missing_profile(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 1, "profiles": {"default": {"API_KEY": "test"}}}))
    assert load_profile("nonexistent", path=creds) == {}


def test_load_profile_missing_file(tmp_path: Path) -> None:
    assert load_profile("default", path=tmp_path / "nope.yaml") == {}


# --- save_profile ---


def test_save_profile_creates_file(tmp_path: Path) -> None:
    creds = tmp_path / "forge" / "credentials.yaml"
    result = save_profile("default", {"API_KEY": "test"}, path=creds)
    assert result == creds
    assert creds.exists()

    loaded = load_credentials(creds)
    assert loaded == {"default": {"API_KEY": "test"}}


def test_save_profile_permissions(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "val"}, path=creds)
    mode = os.stat(creds).st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_save_profile_merge_true(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY_A": "a"}, path=creds)
    save_profile("default", {"KEY_B": "b"}, path=creds, merge=True)

    loaded = load_profile("default", path=creds)
    assert loaded == {"KEY_A": "a", "KEY_B": "b"}


def test_save_profile_merge_overwrites_existing_key(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "old"}, path=creds)
    save_profile("default", {"KEY": "new"}, path=creds, merge=True)

    assert load_profile("default", path=creds) == {"KEY": "new"}


def test_save_profile_merge_false_replaces(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY_A": "a", "KEY_B": "b"}, path=creds)
    save_profile("default", {"KEY_C": "c"}, path=creds, merge=False)

    loaded = load_profile("default", path=creds)
    assert loaded == {"KEY_C": "c"}


def test_save_profile_preserves_other_profiles(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "default-val"}, path=creds)
    save_profile("work", {"KEY": "work-val"}, path=creds)

    loaded = load_credentials(creds)
    assert loaded["default"] == {"KEY": "default-val"}
    assert loaded["work"] == {"KEY": "work-val"}


def test_save_profile_writes_version(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "val"}, path=creds)

    with open(creds) as f:
        data = yaml.safe_load(f)
    assert data["version"] == SCHEMA_VERSION


def test_save_profile_writes_header_comment(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "val"}, path=creds)

    raw = creds.read_text()
    assert "Forge Credential Store" in raw


def test_save_profile_invalid_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid profile name"):
        save_profile("bad/name", {"KEY": "val"}, path=tmp_path / "creds.yaml")


def test_save_profile_recovers_from_corrupt_file(tmp_path: Path) -> None:
    """If the file is corrupt, save_profile starts fresh under lock."""
    creds = tmp_path / "credentials.yaml"
    creds.write_text("{{corrupt yaml")

    save_profile("default", {"KEY": "val"}, path=creds)
    assert load_profile("default", path=creds) == {"KEY": "val"}


def test_save_profile_refuses_to_overwrite_future_version(tmp_path: Path) -> None:
    """save_profile must NOT silently wipe a future-version credential file."""
    creds = tmp_path / "credentials.yaml"
    creds.write_text(yaml.dump({"version": 99, "profiles": {"default": {"KEY": "precious"}}}))

    with pytest.raises(CredentialVersionError, match="version 99"):
        save_profile("default", {"KEY": "new"}, path=creds)

    # Original file content must be preserved
    raw = yaml.safe_load(creds.read_text())
    assert raw["version"] == 99
    assert raw["profiles"]["default"]["KEY"] == "precious"


# --- delete_profile ---


def test_delete_profile_existing(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "val"}, path=creds)
    save_profile("work", {"KEY": "val2"}, path=creds)

    result = delete_profile("default", path=creds)
    assert result is True
    assert list_profiles(creds) == ["work"]


def test_delete_profile_nonexistent(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("default", {"KEY": "val"}, path=creds)

    result = delete_profile("nonexistent", path=creds)
    assert result is False


def test_delete_profile_missing_file(tmp_path: Path) -> None:
    result = delete_profile("default", path=tmp_path / "nope.yaml")
    assert result is False


def test_delete_profile_invalid_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid profile name"):
        delete_profile("../bad", path=tmp_path / "creds.yaml")


# --- list_profiles ---


def test_list_profiles_empty(tmp_path: Path) -> None:
    assert list_profiles(tmp_path / "nope.yaml") == []


def test_list_profiles_sorted(tmp_path: Path) -> None:
    creds = tmp_path / "credentials.yaml"
    save_profile("zebra", {"K": "v"}, path=creds)
    save_profile("alpha", {"K": "v"}, path=creds)
    save_profile("middle", {"K": "v"}, path=creds)

    assert list_profiles(creds) == ["alpha", "middle", "zebra"]
