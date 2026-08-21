"""Tests for forge.install.codex_hooks — Codex config.toml managed block."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.core.paths import get_forge_home
from forge.install.codex_hooks import (
    CODEX_BLOCK_BEGIN,
    CODEX_BLOCK_END,
    CODEX_HOOK_EVENTS,
    CodexHookEntry,
    apply_codex_merge,
    apply_codex_merge_transaction,
    apply_codex_runtime_remove,
    backup_codex_config,
    codex_registration_key,
    codex_registration_keys,
    get_builtin_codex_entries,
    get_codex_config_path,
    inspect_codex_hook_registration,
    plan_codex_merge,
    plan_codex_remove,
    plan_codex_runtime_remove,
    read_codex_registration,
    remove_codex_block,
    render_codex_block,
    restore_codex_config_rollback_state,
    validate_codex_events,
)
from forge.install.exceptions import ForgeInstallError
from forge.install.models import InstallScope

USER_CONTENT = (
    'model = "gpt-5.5-codex"\n'
    "# my notes -- do not lose\n"
    "\n"
    '[projects."/home/me/repo"]\n'
    'trust_level = "trusted"\n'
)


def _entries() -> tuple[CodexHookEntry, ...]:
    return get_builtin_codex_entries()


def _normalize_forge_home(text: str) -> str:
    return text.replace(str(get_forge_home()), "$FORGE_HOME")


def _install(config: Path) -> None:
    apply_codex_merge(config, _entries())


class TestBuiltinEntries:
    def test_two_entries_with_trust_durable_commands(self) -> None:
        assert [(e.event, _normalize_forge_home(e.command)) for e in _entries()] == [
            ("SessionStart", "$FORGE_HOME/bin/forge-hook codex-session-start"),
            ("PreToolUse", "$FORGE_HOME/bin/forge-hook codex-policy-check"),
        ]

    def test_pretooluse_has_no_matcher(self) -> None:
        # The adapter filters apply_patch vs Bash itself; a matcher would
        # change the trust-hashed definition for no gain.
        pretool = next(e for e in _entries() if e.event == "PreToolUse")
        assert pretool.matcher is None

    def test_builtin_events_are_known(self) -> None:
        validate_codex_events(_entries())


class TestRegistrationInspection:
    def test_requires_one_byte_exact_policy_row(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(render_codex_block(_entries()), encoding="utf-8")
        expected = next(entry for entry in _entries() if entry.event == "PreToolUse")

        inspection = inspect_codex_hook_registration(config, expected)

        assert inspection.exactly_one is True
        assert inspection.registration_count == 1
        assert inspection.exact_count == 1

    @pytest.mark.parametrize(
        "installed_policy",
        [
            lambda expected: replace(expected, matcher="apply_patch"),
            lambda expected: replace(expected, timeout=5),
            lambda expected: replace(expected, command="forge hook codex-policy-check"),
            lambda expected: replace(expected, event="SessionStart"),
        ],
    )
    def test_rejects_policy_row_drift(self, tmp_path: Path, installed_policy) -> None:
        config = tmp_path / "config.toml"
        expected = next(entry for entry in _entries() if entry.event == "PreToolUse")
        config.write_text(render_codex_block((installed_policy(expected),)), encoding="utf-8")

        inspection = inspect_codex_hook_registration(config, expected)

        assert inspection.exactly_one is False
        assert inspection.registration_count == 1
        assert inspection.exact_count == 0

    def test_rejects_duplicate_policy_rows(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        expected = next(entry for entry in _entries() if entry.event == "PreToolUse")
        config.write_text(render_codex_block((expected, expected)), encoding="utf-8")

        inspection = inspect_codex_hook_registration(config, expected)

        assert inspection.exactly_one is False
        assert inspection.registration_count == 2
        assert inspection.exact_count == 2


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
            'command = "$FORGE_HOME/bin/forge-hook codex-session-start"\n'
            "timeout = 60\n"
            "\n"
            "[[hooks.PreToolUse]]\n"
            "[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\n'
            'command = "$FORGE_HOME/bin/forge-hook codex-policy-check"\n'
            "timeout = 60\n"
            "# <<< forge hooks <<<\n"
        )
        assert _normalize_forge_home(render_codex_block(_entries())) == expected

    def test_block_is_valid_toml(self) -> None:
        parsed = tomllib.loads(render_codex_block(_entries()))
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
        plan = plan_codex_merge(tmp_path / "config.toml", _entries())
        assert plan.action == "install"

    def test_existing_user_config_installs(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        assert plan_codex_merge(config, _entries()).action == "install"

    def test_identical_block_skips(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "skip"
        assert plan.reason == "already installed"

    def test_changed_block_updates(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, _entries()[:1])  # older Forge: one hook only
        assert plan_codex_merge(config, _entries()).action == "update"

    def test_unparseable_config_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("not = valid = toml\n")
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "conflict"
        assert "not valid TOML" in (plan.reason or "")

    def test_hooks_not_a_table_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("hooks = 3\n")
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "conflict"
        assert "'hooks' is not a table" in (plan.reason or "")

    def test_event_not_an_array_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text('[hooks]\nSessionStart = "oops"\n')
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "conflict"
        assert "hooks.SessionStart" in (plan.reason or "")

    def test_full_manual_registration_skips(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            "\n".join(
                f"[[hooks.{e.event}]]\n[[hooks.{e.event}.hooks]]\n"
                f'type = "command"\ncommand = "{e.command}"\ntimeout = 60'
                for e in _entries()
            )
            + "\n"
        )
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "skip"
        assert "outside Forge markers" in (plan.reason or "")

    def test_full_legacy_manual_registration_skips(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
            "[[hooks.PreToolUse]]\n[[hooks.PreToolUse.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-policy-check"\ntimeout = 60\n'
        )
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "skip"
        assert "outside Forge markers" in (plan.reason or "")

    def test_partial_manual_registration_conflicts(self, tmp_path: Path) -> None:
        # Installing the full block would double-register the manual hook
        # (Codex fires duplicates twice per event); skipping would leave the
        # other hook unregistered. Neither auto-resolution is safe.
        config = tmp_path / "config.toml"
        config.write_text(
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            f'type = "command"\ncommand = "{_entries()[0].command}"\ntimeout = 60\n'
        )
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "conflict"
        assert "codex-session-start" in (plan.reason or "")
        assert "codex-policy-check" in (plan.reason or "")

    def test_begin_without_end_marker_conflicts(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(f"{CODEX_BLOCK_BEGIN}\n[[hooks.SessionStart]]\n")
        plan = plan_codex_merge(config, _entries())
        assert plan.action == "conflict"
        assert "without a closing" in (plan.reason or "")


class TestApplyMerge:
    def test_fresh_install_creates_parseable_config(self, tmp_path: Path) -> None:
        config = tmp_path / "codex" / "config.toml"
        backup = apply_codex_merge(config, _entries())
        assert backup is None  # nothing to back up
        parsed = tomllib.loads(config.read_text())
        commands = {h["command"] for entries in parsed["hooks"].values() for e in entries for h in e["hooks"]}
        assert commands == {e.command for e in _entries()}

    def test_install_preserves_user_bytes_and_backs_up(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        backup = apply_codex_merge(config, _entries())
        assert backup is not None and backup.read_text() == USER_CONTENT
        text = config.read_text()
        assert text.startswith(USER_CONTENT + "\n")  # one blank separator line
        assert text.endswith(render_codex_block(_entries()))
        parsed = tomllib.loads(text)
        assert parsed["model"] == "gpt-5.5-codex"

    def test_second_apply_is_noop(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        apply_codex_merge(config, _entries())
        before = config.read_text()
        assert apply_codex_merge(config, _entries()) is None
        assert config.read_text() == before

    def test_transaction_skip_has_no_rollback_state(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, _entries())

        result = apply_codex_merge_transaction(config, _entries())

        assert result.backup_path is None
        assert result.rollback_state is None

    @pytest.mark.parametrize("existed", [False, True], ids=["missing", "existing"])
    def test_transaction_rollback_restores_exact_config(self, tmp_path: Path, existed: bool) -> None:
        config = tmp_path / "config.toml"
        original = USER_CONTENT.encode() if existed else None
        if original is not None:
            config.write_bytes(original)
            config.chmod(0o640)

        result = apply_codex_merge_transaction(config, _entries())
        assert result.rollback_state is not None

        assert restore_codex_config_rollback_state(result.rollback_state) == []
        if original is None:
            assert not config.exists()
        else:
            assert config.read_bytes() == original
            assert config.stat().st_mode & 0o777 == 0o640

    def test_transaction_rollback_preserves_a_later_user_edit(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        result = apply_codex_merge_transaction(config, _entries())
        assert result.rollback_state is not None
        config.write_text(config.read_text() + "\nuser_after_forge = true\n")
        changed = config.read_bytes()

        failures = restore_codex_config_rollback_state(result.rollback_state)

        assert failures == [f"Codex config '{config}' changed after Forge wrote it"]
        assert config.read_bytes() == changed

    def test_transaction_rollback_preserves_config_when_applied_mode_is_unknown(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        result = apply_codex_merge_transaction(config, _entries())
        assert result.rollback_state is not None
        applied = config.read_bytes()

        failures = restore_codex_config_rollback_state(replace(result.rollback_state, applied_mode=None))

        assert failures == [f"Codex config '{config}' changed after Forge wrote it"]
        assert config.read_bytes() == applied

    def test_compatibility_apply_preserves_oserror_boundary(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"

        with (
            patch("forge.install.codex_hooks.atomic_write_text", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            apply_codex_merge(config, _entries())

    def test_update_replaces_block_in_place(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        apply_codex_merge(config, _entries()[:1])
        apply_codex_merge(config, _entries())
        text = config.read_text()
        assert text.count(CODEX_BLOCK_BEGIN) == 1
        assert render_codex_block(_entries()) in text
        assert tomllib.loads(text)["model"] == "gpt-5.5-codex"

    def test_no_trailing_newline_handled(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text('model = "x"')  # no trailing newline
        apply_codex_merge(config, _entries())
        tomllib.loads(config.read_text())

    def test_conflict_raises_and_leaves_file(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text("not = valid = toml\n")
        with pytest.raises(ForgeInstallError, match="conflict"):
            apply_codex_merge(config, _entries())
        assert config.read_text() == "not = valid = toml\n"

    def test_inline_table_hooks_fails_post_validation_without_write(self, tmp_path: Path) -> None:
        # `hooks = { SessionStart = [] }` parses as a dict-with-list, so the
        # structure pre-check passes -- but appending [[hooks.SessionStart]]
        # cannot extend an inline table. Only post-merge validation catches it.
        config = tmp_path / "config.toml"
        original = "hooks = { SessionStart = [] }\n"
        config.write_text(original)
        with pytest.raises(ForgeInstallError, match="invalid TOML"):
            apply_codex_merge(config, _entries())
        assert config.read_text() == original
        assert not list(tmp_path.glob(".config.toml.forge.backup.*"))  # validated before backup


class TestRemoveBlock:
    def test_strict_remove_plan_rejects_manual_sibling(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        config.write_text(
            config.read_text(encoding="utf-8")
            + (
                "\n[[hooks.SessionStart]]\n"
                "[[hooks.SessionStart.hooks]]\n"
                'type = "command"\n'
                f'command = "{_entries()[0].command}"\n'
                "timeout = 60\n"
            ),
            encoding="utf-8",
        )

        plan = plan_codex_remove(config, _entries())

        assert plan.action == "conflict"
        assert plan.leftover_commands == (_entries()[0].command,)

    def test_strict_remove_plan_accepts_balanced_managed_block(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT, encoding="utf-8")
        _install(config)

        plan = plan_codex_remove(config, _entries())

        assert plan.action == "remove"

    def test_strict_remove_plan_rejects_any_forge_command_outside_markers(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        config.write_text(
            config.read_text(encoding="utf-8")
            + (
                "\n[[hooks.Stop]]\n"
                "[[hooks.Stop.hooks]]\n"
                'type = "command"\n'
                'command = "forge-hook custom-handler"\n'
            ),
            encoding="utf-8",
        )

        plan = plan_codex_remove(config, _entries())

        assert plan.action == "conflict"
        assert plan.leftover_commands == ("forge-hook custom-handler",)

    def test_remove_preserves_user_content(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT)
        apply_codex_merge(config, _entries())
        result = remove_codex_block(config, _entries())
        assert result.removed and not result.deleted_file
        assert config.read_text() == USER_CONTENT
        assert result.leftover_commands == ()

    def test_forge_created_file_is_deleted(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, _entries())
        result = remove_codex_block(config, _entries())
        assert result.removed and result.deleted_file
        assert not config.exists()

    def test_missing_file_is_noop(self, tmp_path: Path) -> None:
        result = remove_codex_block(tmp_path / "config.toml", _entries())
        assert not result.removed

    def test_outside_marker_commands_reported_not_touched(self, tmp_path: Path) -> None:
        manual = (
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            f'type = "command"\ncommand = "{_entries()[0].command}"\ntimeout = 60\n'
        )
        config = tmp_path / "config.toml"
        config.write_text(manual)
        result = remove_codex_block(config, _entries())
        assert not result.removed
        assert result.leftover_commands == (_entries()[0].command,)
        assert config.read_text() == manual

    def test_legacy_outside_marker_commands_reported_not_touched(self, tmp_path: Path) -> None:
        manual = (
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        )
        config = tmp_path / "config.toml"
        config.write_text(manual)
        result = remove_codex_block(config, _entries())
        assert not result.removed
        assert result.leftover_commands == ("forge hook codex-session-start",)
        assert config.read_text() == manual


class TestRuntimeRemoveBlock:
    def test_absent_file_and_absent_block_clear_stale_ownership(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        absent = plan_codex_runtime_remove(config, _entries())
        assert absent.action == "clear"
        assert absent.reason == "config absent"

        config.write_text(USER_CONTENT, encoding="utf-8")
        no_block = plan_codex_runtime_remove(config, _entries())
        assert no_block.action == "clear"
        assert no_block.reason == "managed block absent"
        result = apply_codex_runtime_remove(no_block, _entries())
        assert not result.removed
        assert config.read_text(encoding="utf-8") == USER_CONTENT

    @pytest.mark.parametrize(
        "markers",
        [
            f"{CODEX_BLOCK_BEGIN}\n",
            f"{CODEX_BLOCK_END}\n",
            f"{CODEX_BLOCK_BEGIN}\n{CODEX_BLOCK_BEGIN}\n{CODEX_BLOCK_END}\n",
            f"{CODEX_BLOCK_BEGIN}\n{CODEX_BLOCK_END}\n{CODEX_BLOCK_END}\n",
            f"{CODEX_BLOCK_END}\n{CODEX_BLOCK_BEGIN}\n",
        ],
    )
    def test_partial_duplicate_and_unbalanced_markers_conflict(self, tmp_path: Path, markers: str) -> None:
        config = tmp_path / "config.toml"
        config.write_text(markers, encoding="utf-8")

        plan = plan_codex_runtime_remove(config, _entries())

        assert plan.action == "conflict"
        assert "partial, duplicated, or unbalanced" in (plan.reason or "")

    def test_balanced_block_preserves_outside_bytes_and_manual_commands(self, tmp_path: Path) -> None:
        manual = (
            "\n[[hooks.Stop]]\n" "[[hooks.Stop.hooks]]\n" 'type = "command"\n' 'command = "forge-hook custom-handler"\n'
        )
        config = tmp_path / "config.toml"
        config.write_text(USER_CONTENT, encoding="utf-8")
        _install(config)
        config.write_text(config.read_text(encoding="utf-8") + manual, encoding="utf-8")
        expected = USER_CONTENT + manual

        plan = plan_codex_runtime_remove(config, _entries())
        result = apply_codex_runtime_remove(plan, _entries())

        assert plan.action == "remove"
        assert result.removed
        assert result.leftover_commands == ("forge-hook custom-handler",)
        assert config.read_text(encoding="utf-8") == expected

    def test_crlf_block_is_classified_for_removal(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_bytes(render_codex_block(_entries()).replace("\n", "\r\n").encode())

        plan = plan_codex_runtime_remove(config, _entries())

        assert plan.action == "remove"
        assert "could not be classified safely" not in (plan.reason or "")

    def test_whitespace_only_remainder_deletes_file(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        plan = plan_codex_runtime_remove(config, _entries())

        result = apply_codex_runtime_remove(plan, _entries())

        assert result.removed
        assert result.deleted_file
        assert not config.exists()

    def test_leaf_symlink_conflicts_without_touching_target(self, tmp_path: Path) -> None:
        target = tmp_path / "tracked-config.toml"
        target.write_text(USER_CONTENT, encoding="utf-8")
        _install(target)
        expected = target.read_bytes()
        config = tmp_path / "config.toml"
        config.symlink_to(target)

        plan = plan_codex_runtime_remove(config, _entries())

        assert plan.action == "conflict"
        assert plan.reason == "tracked config is a symbolic link"
        assert config.is_symlink()
        assert target.read_bytes() == expected

    def test_apply_refuses_content_changed_after_plan(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        plan = plan_codex_runtime_remove(config, _entries())
        config.write_text('model = "changed"\n' + config.read_text(encoding="utf-8"), encoding="utf-8")

        with pytest.raises(ForgeInstallError, match="changed after removal was planned"):
            apply_codex_runtime_remove(plan, _entries())

        assert CODEX_BLOCK_BEGIN in config.read_text(encoding="utf-8")

    def test_apply_refuses_same_content_leaf_symlink_replacement(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        _install(config)
        plan = plan_codex_runtime_remove(config, _entries())
        expected = config.read_bytes()
        target = tmp_path / "replacement-config.toml"
        target.write_bytes(expected)
        config.unlink()
        config.symlink_to(target)

        with pytest.raises(ForgeInstallError, match="symbolic link"):
            apply_codex_runtime_remove(plan, _entries())

        assert config.is_symlink()
        assert target.read_bytes() == expected


class TestReadRegistration:
    def test_absent_file(self, tmp_path: Path) -> None:
        status = read_codex_registration(tmp_path / "config.toml", _entries())
        assert not status.block_present
        assert status.commands_registered == ()

    def test_installed_block(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        apply_codex_merge(config, _entries())
        status = read_codex_registration(config, _entries())
        assert status.block_present
        assert status.commands_registered == (
            _entries()[1].command,
            _entries()[0].command,
        )

    def test_legacy_manual_registration_reports_registered(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        )
        status = read_codex_registration(config, _entries())
        assert not status.block_present
        assert status.commands_registered == ("forge hook codex-session-start",)

    def test_registration_keys_map_legacy_and_dispatcher_to_same_identity(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            "[[hooks.SessionStart]]\n[[hooks.SessionStart.hooks]]\n"
            'type = "command"\ncommand = "forge hook codex-session-start"\ntimeout = 60\n'
        )
        expected = codex_registration_key("SessionStart", _entries()[0].command)
        assert codex_registration_keys(config) == {expected}


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
