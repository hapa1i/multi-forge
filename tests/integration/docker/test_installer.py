"""End-to-end tests for installer against real ~/.claude/ paths.

These tests run in Docker containers to validate installer operations
against real filesystem paths without risk to host machine.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.fixtures.docker import ContainerLike

# Mark all tests as integration + docker_in
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


_CODEX_PORTABLE_SKILLS = (
    "challenge",
    "review",
    "review-docs",
    "smoke-test",
    "understand",
)
_PATH_WITHOUT_CODEX = "/usr/bin:/bin"


def _get_tracking_path(container: ContainerLike) -> str:
    """Return the tracking manifest path resolved by Forge inside the test environment."""
    result = container.exec("""
        cd /forge && uv run python -c "
from forge.install.tracking import get_tracking_path
print(get_tracking_path())
"
    """)
    assert result.returncode == 0, f"Tracking path probe failed: {result.stderr}"
    return result.stdout.strip()


def _exec_with_extension_source(
    container: ContainerLike,
    command: str,
    *,
    bundled: bool,
) -> subprocess.CompletedProcess[str]:
    """Run Forge from the checkout or temporarily force its bundled extension assets."""
    if not bundled:
        return container.exec(command)

    return container.exec(f"""
set -eu
bundled_root=$(/forge/.venv/bin/python -c "from forge.install.installer import _get_bundled_extensions_path; print(_get_bundled_extensions_path())")
if [ -e "$bundled_root" ]; then
    mv "$bundled_root" "${{bundled_root}}.integration-original"
fi
restore_checkout_extensions() {{
    for module in skills agents commands; do
        if [ -d "/forge/src/${{module}}.integration-hidden" ]; then
            mv "/forge/src/${{module}}.integration-hidden" "/forge/src/${{module}}"
        fi
    done
    rm -rf "$bundled_root"
    if [ -e "${{bundled_root}}.integration-original" ]; then
        mv "${{bundled_root}}.integration-original" "$bundled_root"
    fi
}}
trap restore_checkout_extensions EXIT
mkdir -p "$bundled_root"
for module in skills agents commands; do
    cp -a "/forge/src/${{module}}" "$bundled_root/${{module}}"
done
for module in skills agents commands; do
    mv "/forge/src/${{module}}" "/forge/src/${{module}}.integration-hidden"
done
{command}
""")


def _read_codex_skill_root(container: ContainerLike, project_root: str | None) -> dict[str, object]:
    """Return the resolved Codex skill root and its immediate package directories."""
    root_expression = (
        f"Path({project_root!r}) / '.agents' / 'skills'"
        if project_root is not None
        else "Path.home() / '.agents' / 'skills'"
    )
    result = container.exec(f"""
/forge/.venv/bin/python - <<'PY'
import json
from pathlib import Path

root = {root_expression}
print(json.dumps({{
    "root": str(root),
    "packages": sorted(path.name for path in root.iterdir() if path.is_dir()),
}}))
PY
""")
    assert result.returncode == 0, f"Codex skill-root probe failed: {result.stderr}"
    return json.loads(result.stdout)


class TestForgeExtensionEnable:
    """Tests for forge extension enable command."""

    def test_init_user_scope_creates_claude_dir(self, synced_container: ContainerLike) -> None:
        """Verify forge extension enable --scope user creates ~/.claude/."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile minimal")
        assert result.returncode == 0, f"Init failed: {result.stderr}"

        check = synced_container.exec("test -d ~/.claude && echo 'exists'")
        assert "exists" in check.stdout, "~/.claude/ directory not created"

    def test_init_user_scope_creates_tracking_file(self, synced_container: ContainerLike) -> None:
        """Verify forge extension enable creates the tracking manifest."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile minimal")
        assert result.returncode == 0

        tracking_path = _get_tracking_path(synced_container)
        check = synced_container.exec(f"test -f {tracking_path} && echo 'found'")
        assert "found" in check.stdout

    def test_init_standard_profile_adds_hooks(self, synced_container: ContainerLike) -> None:
        """Verify forge extension enable --profile standard adds hooks to settings.json."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile standard")
        assert result.returncode == 0

        # Parse settings.json and verify hooks key exists
        check = synced_container.exec("""
            cd /forge && uv run python -c "
import json
from pathlib import Path
settings = json.loads(Path.home().joinpath('.claude/settings.json').read_text())
assert 'hooks' in settings, 'hooks key missing'
print('hooks present')
"
        """)
        assert check.returncode == 0, f"Settings check failed: {check.stderr}"
        assert "hooks present" in check.stdout

    def test_full_profile_memory_passport_assets(self, synced_container: ContainerLike) -> None:
        """Full installs ship the envelope and explicit-upgrade QA guidance."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile full")
        assert result.returncode == 0, f"Enable failed: {result.stderr}"

        qa = synced_container.read_file("$HOME/.claude/skills/qa/resources/checklist/16-memory.md")
        walkthrough = synced_container.read_file("$HOME/.claude/skills/walkthrough/resources/checklist.md")

        for content in (qa, walkthrough):
            assert "Memory Document" in content
            assert "forge_memory" in content
            assert "forge memory passport upgrade" in content

        assert 'assert all(key not in frontmatter for key in ("resource", "tags", "timestamp"))' in qa
        assert 'forbidden = {"resource", "tags", "timestamp"}' in walkthrough
        assert "forbidden.isdisjoint" in walkthrough
        assert "import yaml" not in walkthrough
        assert "cmp -s .forge/memory/legacy-passport.md /tmp/legacy-passport.upgraded" in qa
        assert "cmp -s .forge/memory/walkthrough-legacy.md /tmp/walkthrough-legacy.upgraded" in walkthrough

    def test_init_is_idempotent(self, synced_container: ContainerLike) -> None:
        """Verify running extension enable twice doesn't error."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        # First init
        result1 = synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile minimal")
        assert result1.returncode == 0

        # Second init (should succeed)
        result2 = synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile minimal")
        assert result2.returncode == 0

    def test_init_auto_detect_creates_project_anchor_under_home(self, synced_container: ContainerLike) -> None:
        """Auto-detect should create repo-local .claude/ instead of falling back to user scope."""
        synced_container.exec("rm -rf ~/.claude ~/.forge ~/repo-auto-detect")

        result = synced_container.exec("""
            mkdir -p ~/repo-auto-detect && cd ~/repo-auto-detect
            git init -b main
            git config user.email "test@forge.local"
            git config user.name "Forge Test"
            echo "# Auto Detect" > README.md
            git add . && git commit -m "init"
            /forge/.venv/bin/forge extension enable --profile minimal
        """)
        assert result.returncode == 0, f"Auto-detect enable failed: {result.stderr}"

        repo_check = synced_container.exec("test -d ~/repo-auto-detect/.claude && echo repo-scope")
        assert "repo-scope" in repo_check.stdout, f"Repo-local .claude/ missing: {repo_check.stderr}"

        home_check = synced_container.exec("test ! -d ~/.claude/settings.json && echo no-user-fallback")
        assert "no-user-fallback" in home_check.stdout, f"Unexpected user-scope install: {home_check.stderr}"

    def test_enable_creates_forge_anchor(self, synced_container: ContainerLike) -> None:
        """forge extension enable --scope local creates both .claude/ and .forge/ (Rule 1)."""
        synced_container.exec("rm -rf ~/.claude ~/.forge ~/repo-forge-anchor")

        result = synced_container.exec("""
            mkdir -p ~/repo-forge-anchor && cd ~/repo-forge-anchor
            git init -b main
            git config user.email "test@forge.local"
            git config user.name "Forge Test"
            echo "# Forge Anchor" > README.md
            git add . && git commit -m "init"
            /forge/.venv/bin/forge extension enable --scope local --profile minimal
        """)
        assert result.returncode == 0, f"Enable failed: {result.stderr}"

        claude_check = synced_container.exec("test -d ~/repo-forge-anchor/.claude && echo claude-ok")
        assert "claude-ok" in claude_check.stdout, ".claude/ should exist after enable"

        forge_check = synced_container.exec("test -d ~/repo-forge-anchor/.forge && echo forge-ok")
        assert "forge-ok" in forge_check.stdout, ".forge/ should exist after enable (Rule 1 anchor)"

        registry_check = synced_container.exec("""
            cd /forge && uv run python -c "
import json
from pathlib import Path
registry = json.loads((Path.home() / '.forge' / 'projects.json').read_text())
paths = {entry['canonical_path'] for entry in registry['projects']}
expected = str((Path.home() / 'repo-forge-anchor').resolve())
assert expected in paths, f'{expected} not enrolled: {paths}'
print('registry-ok')
"
        """)
        assert "registry-ok" in registry_check.stdout, f"Project registry check failed: {registry_check.stderr}"

    def test_init_project_dry_run_does_not_create_claude_anchor(self, synced_container: ContainerLike) -> None:
        """--dry-run should not create .claude/ as a side effect."""
        synced_container.exec("rm -rf ~/.claude ~/.forge ~/repo-dry-run")

        result = synced_container.exec("""
            mkdir -p ~/repo-dry-run && cd ~/repo-dry-run
            git init -b main
            git config user.email "test@forge.local"
            git config user.name "Forge Test"
            echo "# Dry Run" > README.md
            git add . && git commit -m "init"
            /forge/.venv/bin/forge extension enable --scope project --profile minimal --dry-run
        """)
        assert result.returncode == 0, f"Dry-run enable failed: {result.stderr}"

        anchor_check = synced_container.exec("test ! -e ~/repo-dry-run/.claude && echo no-anchor")
        assert (
            "no-anchor" in anchor_check.stdout
        ), f".claude/ should not be created during dry-run: {anchor_check.stderr}"


class TestForgeExtensionSync:
    """Tests for forge extension sync command."""

    def test_update_requires_existing_installation(self, synced_container: ContainerLike) -> None:
        """Verify forge extension sync fails without prior install."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec("cd /forge && uv run forge extension sync --scope user 2>&1")
        assert result.returncode != 0
        # Error message says "no Forge installation found" or similar
        assert "no forge installation" in result.stdout.lower() or "forge extension enable" in result.stdout.lower()

    def test_update_preserves_user_settings(self, synced_container: ContainerLike) -> None:
        """Verify update doesn't clobber user customizations."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        # Init first
        synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile minimal")

        # Add user customization to settings (preserve existing structure)
        synced_container.exec("""
            cd /forge && uv run python -c "
import json
from pathlib import Path
settings_path = Path.home() / '.claude' / 'settings.json'
settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
settings['userCustomKey'] = 'preserved'
settings_path.write_text(json.dumps(settings, indent=2))
"
        """)

        # Update
        result = synced_container.exec("cd /forge && uv run forge extension sync --scope user")
        assert result.returncode == 0

        # User key should still be there
        check = synced_container.exec("""
            cd /forge && uv run python -c "
import json
from pathlib import Path
settings = json.loads(Path.home().joinpath('.claude/settings.json').read_text())
assert settings.get('userCustomKey') == 'preserved', 'User key was lost'
print('preserved')
"
        """)
        assert "preserved" in check.stdout


class TestCrossRuntimeSkillLifecycle:
    """Packaged Codex skills stay isolated and tracked through their CLI lifecycle."""

    @pytest.mark.parametrize(
        ("scope", "project_root", "bundled_assets"),
        [
            pytest.param("user", None, False, id="user-checkout-assets"),
            pytest.param(
                "project",
                "/tmp/forge-codex-skills-project",
                True,
                id="project-bundled-assets",
            ),
        ],
    )
    def test_codex_only_packages_survive_runtime_absence_and_disable_tracked_only(
        self,
        synced_container: ContainerLike,
        scope: str,
        project_root: str | None,
        bundled_assets: bool,
    ) -> None:
        """Enable, status, sync, and disable the five portable Codex packages."""
        setup = synced_container.exec("""
rm -rf ~/.agents ~/.claude ~/.forge /tmp/forge-codex-skills-project /tmp/forge-codex-skills-bin
mkdir -p /tmp/forge-codex-skills-bin /tmp/forge-codex-skills-project
printf '#!/bin/sh\nprintf "codex-cli 0.144.0\\n"\n' > /tmp/forge-codex-skills-bin/codex
chmod +x /tmp/forge-codex-skills-bin/codex
""")
        assert setup.returncode == 0, f"Fixture setup failed: {setup.stderr}"

        if scope == "user":
            enable_target = "--scope user"
            status_target = "--scope user"
            lifecycle_cwd = "/forge"
            tracking_key = "user"
            claude_anchor = "$HOME/.claude"
            opposite_codex_anchor = "/tmp/forge-codex-skills-project/.agents"
        else:
            assert project_root is not None
            enable_target = f"--scope project --root {project_root}"
            status_target = f"--scope project --root {project_root}"
            lifecycle_cwd = project_root
            tracking_key = f"project:{project_root}"
            claude_anchor = f"{project_root}/.claude"
            opposite_codex_anchor = "$HOME/.agents"

        enable = _exec_with_extension_source(
            synced_container,
            (
                f"cd {lifecycle_cwd}\n"
                "PATH=/tmp/forge-codex-skills-bin:$PATH "
                f"/forge/.venv/bin/forge extension enable {enable_target} "
                "--profile minimal --with skills --without commands --runtime codex"
            ),
            bundled=bundled_assets,
        )
        assert enable.returncode == 0, f"Codex enable failed: stdout={enable.stdout!r} stderr={enable.stderr!r}"
        assert synced_container.exec(f"test ! -e {claude_anchor}").returncode == 0
        assert synced_container.exec(f"test ! -e {opposite_codex_anchor}").returncode == 0

        target = _read_codex_skill_root(synced_container, project_root)
        target_root = str(target["root"])
        assert target["packages"] == list(_CODEX_PORTABLE_SKILLS)

        manifest = synced_container.read_json(_get_tracking_path(synced_container))
        assert manifest["version"] == 2
        installation = manifest["installations"][tracking_key]
        assert installation["modules_enabled"] == ["skills"]
        packages = installation["skill_packages"]
        assert [(package["runtime"], package["skill"]) for package in packages] == [
            ("codex", skill) for skill in _CODEX_PORTABLE_SKILLS
        ]
        for package in packages:
            expected_dir = f"{target_root}/{package['skill']}"
            assert package["target_dir"] == expected_dir
            assert package["file_paths"] == sorted(package["file_paths"])
            assert package["file_paths"]
            assert all(path.startswith(f"{expected_dir}/") for path in package["file_paths"])

        codex_absent = synced_container.exec(f"PATH={_PATH_WITHOUT_CODEX} command -v codex")
        assert codex_absent.returncode != 0, "The sync probe PATH unexpectedly contains Codex"
        sync = _exec_with_extension_source(
            synced_container,
            (
                f"cd {lifecycle_cwd}\n"
                f"PATH={_PATH_WITHOUT_CODEX} /forge/.venv/bin/forge extension sync --scope {scope}"
            ),
            bundled=bundled_assets,
        )
        assert sync.returncode == 0, f"Codex sync failed: stdout={sync.stdout!r} stderr={sync.stderr!r}"
        assert _read_codex_skill_root(synced_container, project_root)["packages"] == list(_CODEX_PORTABLE_SKILLS)

        status = synced_container.exec(
            f"cd {lifecycle_cwd}\n"
            f"PATH={_PATH_WITHOUT_CODEX} /forge/.venv/bin/forge extension status {status_target} --json"
        )
        assert status.returncode == 0, f"Codex status failed: {status.stderr}"
        payload = json.loads(status.stdout)
        assert len(payload) == 1
        assert payload[0]["scope"] == scope
        observed_packages = payload[0]["skill_packages"]
        assert [(package["runtime"], package["skill"]) for package in observed_packages] == [
            ("codex", skill) for skill in _CODEX_PORTABLE_SKILLS
        ]
        for package in observed_packages:
            assert package["state"] == "present"
            assert package["target_present"] is True
            assert package["missing_file_paths"] == []
            assert package["duplicate_dirs"] == []
            assert package["recovery"] is None

        operator_package = f"{target_root}/operator-owned"
        add_operator_package = synced_container.exec(
            f'mkdir -p "{operator_package}"\n' f'printf "operator-owned\\n" > "{operator_package}/SKILL.md"'
        )
        assert add_operator_package.returncode == 0, add_operator_package.stderr

        disable = synced_container.exec(
            f"cd {lifecycle_cwd}\n"
            f"PATH={_PATH_WITHOUT_CODEX} /forge/.venv/bin/forge extension disable --scope {scope} --yes"
        )
        assert disable.returncode == 0, f"Codex disable failed: stdout={disable.stdout!r} stderr={disable.stderr!r}"
        remaining = _read_codex_skill_root(synced_container, project_root)
        assert remaining["packages"] == ["operator-owned"]
        assert synced_container.read_file(f"{operator_package}/SKILL.md") == "operator-owned\n"

        after_disable = synced_container.read_json(_get_tracking_path(synced_container))
        assert tracking_key not in after_disable["installations"]


class TestHookDispatcherRuntime:
    """Rendered dispatcher behavior in the installed container environment."""

    def test_dev_override_executes_checkout_and_invalid_value_never_falls_back(
        self,
        synced_container: ContainerLike,
    ) -> None:
        synced_container.exec(
            "rm -rf ~/.claude ~/.forge /tmp/forge-global /tmp/forge-dev "
            "/tmp/forge-dev-args /tmp/forge-dev-stdin /tmp/forge-global-invoked"
        )
        synced_container.mkdir("/tmp/forge-global", parents=True)
        synced_container.write_file(
            "/tmp/forge-global/forge",
            '#!/bin/sh\nprintf "%s\\n" "$@" > /tmp/forge-global-invoked\n',
        )
        synced_container.mkdir("/tmp/forge-dev/.venv/bin", parents=True)
        synced_container.write_file(
            "/tmp/forge-dev/.venv/bin/forge",
            '#!/bin/sh\nprintf "%s\\n" "$@" > /tmp/forge-dev-args\ncat > /tmp/forge-dev-stdin\n',
        )
        permissions = synced_container.exec("chmod +x /tmp/forge-global/forge /tmp/forge-dev/.venv/bin/forge")
        assert permissions.returncode == 0, permissions.stderr

        enabled = synced_container.exec(
            "cd /forge && PATH=/tmp/forge-global:$PATH "
            "/forge/.venv/bin/forge extension enable --scope user --profile minimal"
        )
        assert enabled.returncode == 0, f"Enable failed: {enabled.stderr}"

        valid = synced_container.exec(
            'printf \'{"tool":"Read"}\' | FORGE_SESSION=integration '
            "FORGE_DEV=/tmp/forge-dev ~/.forge/bin/forge-hook policy-check"
        )
        assert valid.returncode == 0, f"Override dispatch failed: {valid.stderr}"
        assert synced_container.read_file("/tmp/forge-dev-args").splitlines() == [
            "hook",
            "policy-check",
        ]
        assert synced_container.read_file("/tmp/forge-dev-stdin") == '{"tool":"Read"}'
        assert not synced_container.file_exists("/tmp/forge-global-invoked")

        invalid = synced_container.exec(
            "FORGE_SESSION=integration FORGE_DEV=/tmp/missing-checkout " "~/.forge/bin/forge-hook policy-check"
        )
        assert invalid.returncode == 127
        assert "FORGE_DEV target is missing or not executable" in invalid.stderr
        assert not synced_container.file_exists("/tmp/forge-global-invoked")


class TestHookMigration:
    """Pre-T5 project state transitions to one user-scoped runtime source."""

    def test_cleanup_project_migrates_tracked_claude_and_codex_hooks(
        self,
        synced_container: ContainerLike,
    ) -> None:
        synced_container.exec("rm -rf ~/.claude ~/.forge ~/repo-hook-migration /tmp/codex-home")
        setup = synced_container.exec("""
            cd /forge && uv run python - <<'PY'
import json
from pathlib import Path

from forge.install.codex_hooks import apply_codex_merge, get_builtin_codex_entries
from forge.install.models import (
    Installation,
    InstalledSettingsEntry,
    InstallMode,
    InstallModule,
    InstallProfile,
    InstallScope,
)
from forge.install.settings_merge import entries_to_added_structure, save_added_settings, write_settings
from forge.install.tracking import TrackingStore

root = Path.home() / "repo-hook-migration"
(root / ".forge").mkdir(parents=True)
(root / ".claude").mkdir()
(root / ".codex").mkdir()
(Path.home() / ".claude").mkdir()
legacy = {"hooks": [{"type": "command", "command": "forge hook session-start"}]}
status_line = {"type": "command", "command": "forge status-line"}
settings_path = root / ".claude" / "settings.json"
write_settings(
    settings_path,
    {
        "hooks": {"SessionStart": [legacy]},
        "statusLine": status_line,
        "permissions": {"allow": ["Read"]},
    },
)
write_settings(
    Path.home() / ".claude" / "settings.local.json",
    {"hooks": {"SessionStart": [legacy]}, "legacyUserKey": True},
)
hook_tracking = InstalledSettingsEntry(
    key_path="hooks.SessionStart",
    value=legacy,
    merge_type="append",
    stable_id=json.dumps(legacy, sort_keys=True, separators=(",", ":")),
)
status_tracking = InstalledSettingsEntry(
    key_path="statusLine",
    value=status_line,
    merge_type="scalar",
    stable_id="statusLine",
)
codex_path = root / ".codex" / "config.toml"
codex_path.write_text('model = "gpt-5"\\n', encoding="utf-8")
apply_codex_merge(codex_path, get_builtin_codex_entries())
installation = Installation(
    scope=InstallScope.PROJECT.value,
    project_path=str(root),
    mode=InstallMode.COPY.value,
    profile=InstallProfile.STANDARD.value,
    modules_enabled=[
        InstallModule.HOOKS.value,
        InstallModule.STATUSLINE.value,
        InstallModule.CODEX_HOOKS.value,
    ],
    settings_entries=[hook_tracking, status_tracking],
    codex_config_path=str(codex_path),
    codex_commands=[entry.command for entry in get_builtin_codex_entries()],
    installed_at="2026-01-01T00:00:00Z",
    updated_at="2026-01-01T00:00:00Z",
)
TrackingStore().set_installation(InstallScope.PROJECT.value, installation, str(root))
save_added_settings(settings_path, entries_to_added_structure(installation.settings_entries))
PY
            """)
        assert setup.returncode == 0, f"Migration fixture setup failed: {setup.stderr}"

        result = synced_container.exec(
            "cd ~/repo-hook-migration && CODEX_HOME=/tmp/codex-home "
            "/forge/.venv/bin/forge extension cleanup-project --root ~/repo-hook-migration --yes"
        )
        assert result.returncode == 0, f"Migration failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        assert "Project hook migration complete" in result.stdout
        assert "grant trust" in result.stdout

        check = synced_container.exec("""
            cd /forge && CODEX_HOME=/tmp/codex-home uv run python - <<'PY'
from pathlib import Path

from forge.install.hooks import (
    find_forge_hook_cleanup_registrations,
    find_forge_hook_registrations,
    has_forge_hook_double_fire,
)
from forge.install.models import InstallModule, InstallScope
from forge.install.project_registry import ProjectRegistryStore
from forge.install.settings_merge import load_added_settings, read_settings
from forge.install.tracking import TrackingStore

root = Path.home() / "repo-hook-migration"
project_settings = read_settings(root / ".claude" / "settings.json")
assert "hooks" not in project_settings
assert project_settings["permissions"] == {"allow": ["Read"]}
assert project_settings["statusLine"]["command"] == "forge status-line"
legacy_user = read_settings(Path.home() / ".claude" / "settings.local.json")
assert legacy_user == {"legacyUserKey": True}
registrations = find_forge_hook_registrations(root)
assert registrations
assert {registration.scope for registration in registrations} == {"user"}
assert not find_forge_hook_cleanup_registrations(root)
assert not has_forge_hook_double_fire(root)
registry = ProjectRegistryStore().read_strict()
entry = next(item for item in registry.projects if item.canonical_path == str(root.resolve()))
assert entry.enrollment_source == "backfill"
tracking = TrackingStore()
project = tracking.get_installation(InstallScope.PROJECT.value, str(root))
assert project is not None
assert InstallModule.HOOKS.value not in project.modules_enabled
assert InstallModule.CODEX_HOOKS.value not in project.modules_enabled
assert InstallModule.STATUSLINE.value in project.modules_enabled
assert not any(item.key_path.startswith("hooks.") for item in project.settings_entries)
added = load_added_settings(root / ".claude" / "settings.json")
assert "hooks" not in added
assert "statusLine" in added
user = tracking.get_installation(InstallScope.USER.value)
assert user is not None
assert InstallModule.HOOKS.value in user.modules_enabled
assert InstallModule.CODEX_HOOKS.value in user.modules_enabled
project_codex = (root / ".codex" / "config.toml").read_text(encoding="utf-8")
assert project_codex == 'model = "gpt-5"\\n'
user_codex = Path("/tmp/codex-home/config.toml").read_text(encoding="utf-8")
assert "# >>> forge hooks >>>" in user_codex
assert list((root / ".claude").glob(".settings.json.forge.backup.*"))
assert list((root / ".codex").glob(".config.toml.forge.backup.*"))
print("migration-ok")
PY
            """)
        assert check.returncode == 0, f"Migration verification failed: {check.stderr}"
        assert "migration-ok" in check.stdout

        disabled = synced_container.exec(
            "cd ~/repo-hook-migration && CODEX_HOME=/tmp/codex-home "
            "/forge/.venv/bin/forge extension disable --scope project --yes"
        )
        assert disabled.returncode == 0, f"Disable failed: stdout={disabled.stdout!r} stderr={disabled.stderr!r}"
        disable_check = synced_container.exec("""
            cd /forge && CODEX_HOME=/tmp/codex-home uv run python - <<'PY'
from pathlib import Path

from forge.install.hooks import find_forge_hook_registrations
from forge.install.models import InstallScope
from forge.install.settings_merge import read_settings
from forge.install.tracking import TrackingStore

root = Path.home() / "repo-hook-migration"
assert "hooks" not in read_settings(root / ".claude" / "settings.json")
registrations = find_forge_hook_registrations(root)
assert registrations
assert {registration.scope for registration in registrations} == {"user"}
tracking = TrackingStore()
assert tracking.get_installation(InstallScope.PROJECT.value, str(root)) is None
assert tracking.get_installation(InstallScope.USER.value) is not None
print("disable-after-migration-ok")
PY
            """)
        assert disable_check.returncode == 0, f"Post-migration disable verification failed: {disable_check.stderr}"
        assert "disable-after-migration-ok" in disable_check.stdout


class TestForgeExtensionDisable:
    """Tests for forge extension disable command."""

    def test_uninstall_removes_tracked_files(self, synced_container: ContainerLike) -> None:
        """Verify forge extension disable removes installed files."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        # Init first
        synced_container.exec("cd /forge && uv run forge extension enable --scope user --profile minimal")

        # Verify installation exists
        check1 = synced_container.exec("test -d ~/.claude && echo 'exists'")
        assert "exists" in check1.stdout

        # Uninstall (--yes to avoid confirmation prompt hanging)
        result = synced_container.exec("cd /forge && uv run forge extension disable --scope user --yes")
        assert result.returncode == 0

        # Verify tracking entry removed (file may still exist but scope entry gone)
        check2 = synced_container.exec("""
            cd /forge && uv run python -c "
import json
from forge.install.tracking import get_tracking_path
tracking_path = get_tracking_path()
if not tracking_path.exists():
    print('file gone')
else:
    manifest = json.loads(tracking_path.read_text())
    if 'user' not in manifest.get('installations', {}):
        print('entry removed')
    else:
        print('entry still exists')
"
        """)
        assert "entry removed" in check2.stdout or "file gone" in check2.stdout

    def test_uninstall_without_installation_is_noop(self, synced_container: ContainerLike) -> None:
        """Verify forge extension disable on empty system is a graceful no-op."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec("cd /forge && uv run forge extension disable --scope user --yes 2>&1")
        # CLI returns 0 and informs user - graceful no-op behavior
        assert result.returncode == 0
        assert "no forge installation" in result.stdout.lower()


class TestSymlinkMode:
    """Tests for symlink installation mode."""

    def test_symlink_mode_creates_symlinks(self, synced_container: ContainerLike) -> None:
        """Verify --symlink creates symlinks not copies."""
        synced_container.exec("rm -rf ~/.claude ~/.forge")

        result = synced_container.exec(
            "cd /forge && uv run forge extension enable --scope user --profile standard --symlink"
        )
        assert result.returncode == 0

        # Check skills directory for symlinks (skills are always present in standard profile)
        check = synced_container.exec("""
            cd /forge && uv run python -c "
from pathlib import Path
skills_dir = Path.home() / '.claude' / 'skills'
skill_dirs = [d for d in skills_dir.iterdir() if d.is_dir() and not d.name.startswith('.')]
assert len(skill_dirs) > 0, 'No skill directories found'
md_files = list(skill_dirs[0].glob('*.md'))
assert len(md_files) > 0, f'No .md files in {skill_dirs[0]}'
assert md_files[0].is_symlink(), f'{md_files[0]} is not a symlink'
print('symlinks verified')
"
        """)
        assert check.returncode == 0, f"Symlink check failed: {check.stderr}"
        assert "symlinks verified" in check.stdout


class TestCodexHooksModule:
    """codex-hooks module: scope-mapped managed block in Codex config.toml."""

    def test_enable_registers_block_and_disable_removes_it(self, synced_container: ContainerLike) -> None:
        """Full cycle with a codex shim on PATH: enable writes the block, disable removes it."""
        synced_container.exec("rm -rf ~/.claude ~/.forge /tmp/codex-home /tmp/fake-bin")
        synced_container.exec(
            "mkdir -p /tmp/fake-bin /tmp/codex-home"
            " && printf '#!/bin/sh\\nexit 0\\n' > /tmp/fake-bin/codex"
            " && chmod +x /tmp/fake-bin/codex"
        )

        result = synced_container.exec(
            "cd /forge && CODEX_HOME=/tmp/codex-home PATH=/tmp/fake-bin:$PATH"
            " uv run forge extension enable --scope user --profile standard"
        )
        assert result.returncode == 0, f"Enable failed: {result.stderr}"
        assert "Next steps (Codex hooks):" in result.stdout

        config = synced_container.read_file("/tmp/codex-home/config.toml")
        assert "# >>> forge hooks >>>" in config
        assert "forge-hook codex-session-start" in config
        assert "forge-hook codex-policy-check" in config

        status = synced_container.exec(
            "cd /forge && CODEX_HOME=/tmp/codex-home uv run forge extension status --scope user"
        )
        assert "Codex:" in status.stdout

        result = synced_container.exec(
            "cd /forge && CODEX_HOME=/tmp/codex-home uv run forge extension disable --scope user --yes"
        )
        assert result.returncode == 0, f"Disable failed: {result.stderr}"
        # Forge created the file, so removing the block deletes it entirely.
        assert not synced_container.file_exists("/tmp/codex-home/config.toml")

    def test_enable_without_codex_binary_skips_visibly(self, synced_container: ContainerLike) -> None:
        """No codex on PATH: presence gate skips with a notice; no config written."""
        synced_container.exec("rm -rf ~/.claude ~/.forge /tmp/codex-home")
        synced_container.exec("mkdir -p /tmp/codex-home")

        result = synced_container.exec(
            "cd /forge && CODEX_HOME=/tmp/codex-home" " uv run forge extension enable --scope user --profile standard"
        )
        assert result.returncode == 0, f"Enable failed: {result.stderr}"
        assert "Codex hooks skipped: codex binary not found on PATH" in result.stdout
        assert not synced_container.file_exists("/tmp/codex-home/config.toml")

    def test_user_content_preserved_through_cycle(self, synced_container: ContainerLike) -> None:
        """A pre-existing codex config keeps its user content through enable + disable."""
        synced_container.exec("rm -rf ~/.claude ~/.forge /tmp/codex-home /tmp/fake-bin")
        synced_container.exec(
            "mkdir -p /tmp/fake-bin /tmp/codex-home"
            " && printf '#!/bin/sh\\nexit 0\\n' > /tmp/fake-bin/codex"
            " && chmod +x /tmp/fake-bin/codex"
        )
        synced_container.write_file("/tmp/codex-home/config.toml", 'model = "gpt-5.5-codex"\n')
        synced_container.exec("chmod 0644 /tmp/codex-home/config.toml")

        enable = (
            "cd /forge && CODEX_HOME=/tmp/codex-home PATH=/tmp/fake-bin:$PATH"
            " uv run forge extension enable --scope user --profile standard"
        )
        assert synced_container.exec(enable).returncode == 0

        config = synced_container.read_file("/tmp/codex-home/config.toml")
        assert config.startswith('model = "gpt-5.5-codex"\n')
        assert "# >>> forge hooks >>>" in config
        assert synced_container.exec("stat -c %a /tmp/codex-home/config.toml").stdout.strip() == "644"

        result = synced_container.exec(
            "cd /forge && CODEX_HOME=/tmp/codex-home uv run forge extension disable --scope user --yes"
        )
        assert result.returncode == 0
        assert synced_container.read_file("/tmp/codex-home/config.toml") == 'model = "gpt-5.5-codex"\n'
        assert synced_container.exec("stat -c %a /tmp/codex-home/config.toml").stdout.strip() == "644"
