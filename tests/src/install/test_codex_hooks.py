"""Tests for forge.install.codex_hooks — Codex config.toml managed block."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from forge.install.codex_hooks import (
    CODEX_BLOCK_BEGIN,
    CODEX_BLOCK_END,
    CODEX_HOOK_EVENTS,
    CodexHookEntry,
    apply_codex_merge,
    backup_codex_config,
    get_builtin_codex_entries,
    get_codex_config_path,
    plan_codex_merge,
    read_codex_registration,
    remove_codex_block,
    render_codex_block,
    validate_codex_events,
)
from forge.install.exceptions import ForgeInstallError
from forge.install.models import InstallScope

ENTRIES = get_builtin_codex_entries()

USER_CONTENT = (
    'model = "gpt-5.5-codex"\n'
    "# my notes -- do not lose\n"
    "\n"
    '[projects."/home/me/repo"]\n'
    'trust_level = "trusted"\n'
)


def _install(config: Path) -> None:
    apply_codex_merge(config, ENTRIES)


class TestBuiltinEntries:
    def test_two_entries_with_trust_durable_commands(self) -> None:
        assert [(e.event, e.command) for e in ENTRIES] == [
            ("SessionStart", "forge hook codex-session-start"),
            ("PreToolUse", "forge hook codex-policy-check"),
        ]

    def test_pretooluse_has_no_matcher(self) -> None:
        # The adapter filters apply_patch vs Bash itself; a matcher would
        # change the trust-hashed definition for no gain.
        pretool = next(e for e in ENTRIES if e.event == "PreToolUse")
        assert pretool.matcher is None

    def test_builtin_events_are_known(self) -> None:
        validate_codex_events(ENTRIES)


class TestEventValidation:
    def test_unknown_event_raises(self) -> None:
        bogus = (CodexHookEntry(event="SessionStarted", command="x"),)
        with pytest.raises(ForgeInstallError, match="SessionStarted"):
            validate_codex_events(bogus)

    def test_known_event_set_is_the_probe_pinned_ten(self) -> None:
        assert len(CODEX_HOOK_EVENTS) == 10


class TestRenderBlock:
    def test_golden_block_bytes(self) -> None:
        """Trust-byte stability: Codex's trusted_hash covers these definitions.

        If this golden changes, every existing enrollment silently breaks.
        Do not update it casually -- see design.md §3.9.
        """
        expected = (
            "# >>> forge hooks >>>\n"
            "# Managed by 'forge extension enable'. Do not edit: Codex trust enrollment\n"
            "# hashes these definitions; any change silently disables the hooks.\n"
            "[[hooks.SessionStart]]\n"
            "[[hooks.SessionStart.hooks]]\n"
            'type = "command"\n'
            'command = "forge hook codex-session-start"\n'
            "timeout = 60\n"
            "\n"
            "[[hooks.PreToolUse]]\n"
            "[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\n'
            'command = "forge hook codex-policy-check"\n'
            "timeout = 60\n"
            "# <<< forge hooks <<<\n"
        )
        assert render_codex_block(ENTRIES) == expected

    def test_block_is_valid_toml(self) -> None:
        parsed = tomllib.loads(render_codex_block(ENTRIES))
        assert len(parsed["hooks"]["SessionStart"]) == 1
        assert parsed["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] == 60

    def test_matcher_rendered_when_present(self) -> None:
        block = render_codex_block((CodexHookEntry(event="Stop", command="x", matcher="shell"),))
        parsed = tomllib.loads(block)
        assert parsed["hooks"]["Stop"][0]["matcher"] == "shell"


class TestConfigPath:
    def test_user_scope_honors_codex_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
        assert get_codex_config_path(InstallScope.USER) == tmp_path / "codex-home" / "config.toml"

    def test_user_scope_defaults_to_home_codex(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CODEX_HOME", raising=False)
        assert get_codex_config_path(InstallScope.USER) == Path.home() / ".codex" / "config.toml"

    @pytest.mark.parametrize("scope", [InstallScope.PROJECT, InstallScope.LOCAL])
    def test_project_and_local_map_to_project_codex(self, scope: InstallScope, tmp_path: Path) -> None:
        # Codex has no settings.local analog: both project scopes target the
        # one per-project config.
        assert get_codex_config_path(scope, tmp_path) == tmp_path / ".codex" / "config.toml"

    @pytest.mark.parametrize("scope", [InstallScope.PROJECT, InstallScope.LOCAL])
    def test_project_scopes_require_project_root(self, scope: InstallScope) -> None:
        with pytest.raises(ValueError, match="project_root required"):
            get_codex_config_path(scope)


class TestPlanMerge:
    def test_missing_file_installs(self, tmp_path: Path) -> None:
        plan = plan_codex_merge(tmp_path / "config.toml", ENTRIES)
        assert plan.action == "install"

    def test_existing_user_config_installs(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        assert plan_codex_merge(config, ENTRIES).action == "install"

    def test_identical_block_skips(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "skip"
        assert plan.reason == "already installed"

    def test_changed_block_updates(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, ENTRIES[:1])  # older Forge: one hook only
        assert plan_codex_merge(config, ENTRIES).action == "update"

    def test_unparseable_config_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("not = valid = toml\n")
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "conflict"
        assert "not valid TOML" in (plan.reason or "")

    def test_hooks_not_a_table_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("hooks = 3\n")
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "conflict"
        assert "'hooks' is not a table" in (plan.reason or "")

    def test_event_not_an_array_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text('[hooks]\nSessionStart = "oops"\n')
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "conflict"
        assert "hooks.SessionStart" in (plan.reason or "")

    def test_full_manual_registration_skips(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            "\n".join(
                f"[[hooks.{e.event}]]\n[[hooks.{e.event}.hooks]]\n"
                f'type = "command"\ncommand = "{e.command}"\ntimeout = 60'
                for e in ENTRIES
            )
            + "\n"
        )
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "skip"
        assert "outside Forge markers" in (plan.reason or "")

    def test_partial_manual_registration_conflicts(self, tmp_path: Path) -> None:
        # Installing the full block would double-register the manual hook
        # (Codex fires duplicates twice per event); skipping would leave the
        # other hook unregistered. Neither auto-resolution is safe.
        config = tmp_path / "config.toml"
        config.write_text(
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        )
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "conflict"
        assert "codex-session-start" in (plan.reason or "")
        assert "codex-policy-check" in (plan.reason or "")

    def test_begin_without_end_marker_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(f"{CODEX_BLOCK_BEGIN}\n[[hooks.SessionStart]]\n")
        plan = plan_codex_merge(config, ENTRIES)
        assert plan.action == "conflict"
        assert "without a closing" in (plan.reason or "")


class TestApplyMerge:
    def test_fresh_install_creates_parseable_config(self, tmp_path: Path) -> None:
        config = tmp_path / "codex" / "config.toml"
        backup = apply_codex_merge(config, ENTRIES)
        assert backup is None  # nothing to back up
        parsed = tomllib.loads(config.read_text())
        commands = {h["command"] for entries in parsed["hooks"].values() for e in entries for h in e["hooks"]}
        assert commands == {e.command for e in ENTRIES}

    def test_install_preserves_user_bytes_and_backs_up(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        backup = apply_codex_merge(config, ENTRIES)
        assert backup is not None and backup.read_text() == USER_CONTENT
        text = config.read_text()
        assert text.startswith(USER_CONTENT + "\n")  # one blank separator line
        assert text.endswith(render_codex_block(ENTRIES))
        parsed = tomllib.loads(text)
        assert parsed["model"] == "gpt-5.5-codex"

    def test_second_apply_is_noop(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        apply_codex_merge(config, ENTRIES)
        before = config.read_text()
        assert apply_codex_merge(config, ENTRIES) is None
        assert config.read_text() == before

    def test_update_replaces_block_in_place(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        apply_codex_merge(config, ENTRIES[:1])
        apply_codex_merge(config, ENTRIES)
        text = config.read_text()
        assert text.count(CODEX_BLOCK_BEGIN) == 1
        assert render_codex_block(ENTRIES) in text
        assert tomllib.loads(text)["model"] == "gpt-5.5-codex"

    def test_no_trailing_newline_handled(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text('model = "x"')  # no trailing newline
        apply_codex_merge(config, ENTRIES)
        tomllib.loads(config.read_text())

    def test_conflict_raises_and_leaves_file(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("not = valid = toml\n")
        with pytest.raises(ForgeInstallError, match="conflict"):
            apply_codex_merge(config, ENTRIES)
        assert config.read_text() == "not = valid = toml\n"

    def test_inline_table_hooks_fails_post_validation_without_write(self, tmp_path: Path) -> None:
        # `hooks = { SessionStart = [] }` parses as a dict-with-list, so the
        # structure pre-check passes -- but appending [[hooks.SessionStart]]
        # cannot extend an inline table. Only post-merge validation catches it.
        config = tmp_path / "config.toml"
        original = "hooks = { SessionStart = [] }\n"
        config.write_text(original)
        with pytest.raises(ForgeInstallError, match="invalid TOML"):
            apply_codex_merge(config, ENTRIES)
        assert config.read_text() == original
        assert not list(tmp_path.glob(".config.toml.forge.backup.*"))  # validated before backup


class TestRemoveBlock:
    def test_remove_preserves_user_content(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        apply_codex_merge(config, ENTRIES)
        result = remove_codex_block(config, ENTRIES)
        assert result.removed and not result.deleted_file
        assert config.read_text() == USER_CONTENT
        assert result.leftover_commands == ()

    def test_forge_created_file_is_deleted(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, ENTRIES)
        result = remove_codex_block(config, ENTRIES)
        assert result.removed and result.deleted_file
        assert not config.exists()

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        result = remove_codex_block(tmp_path / "config.toml", ENTRIES)
        assert not result.removed

    def test_outside_marker_commands_reported_not_touched(self, tmp_path: Path) -> None:
        manual = (
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        )
        config = tmp_path / "config.toml"
        config.write_text(manual)
        result = remove_codex_block(config, ENTRIES)
        assert not result.removed
        assert result.leftover_commands == ("forge hook codex-session-start",)
        assert config.read_text() == manual


class TestReadRegistration:
    def test_absent_file(self, tmp_path: Path) -> None:
        status = read_codex_registration(tmp_path / "config.toml", ENTRIES)
        assert not status.block_present
        assert status.commands_registered == ()

    def test_installed_block(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, ENTRIES)
        status = read_codex_registration(config, ENTRIES)
        assert status.block_present
        assert status.commands_registered == (
            "forge hook codex-policy-check",
            "forge hook codex-session-start",
        )


class TestBackup:
    def test_backup_absent_file_returns_none(self, tmp_path: Path) -> None:
        assert backup_codex_config(tmp_path / "config.toml") is None

    def test_backup_naming_mirrors_settings_pattern(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("x = 1\n")
        backup = backup_codex_config(config)
        assert backup is not None
        assert backup.name.startswith(".config.toml.forge.backup.")


class TestMarkers:
    def test_end_marker_is_distinct(self) -> None:
        assert CODEX_BLOCK_BEGIN != CODEX_BLOCK_END
