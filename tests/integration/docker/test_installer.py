"""End-to-end tests for installer against real ~/.claude/ paths.

These tests run in Docker containers to validate installer operations
against real filesystem paths without risk to host machine.
"""

from __future__ import annotations

import pytest

from tests.fixtures.docker import ContainerLike

# Mark all tests as integration + docker_in
pytestmark = [pytest.mark.integration, pytest.mark.docker_in]


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

        enable = (
            "cd /forge && CODEX_HOME=/tmp/codex-home PATH=/tmp/fake-bin:$PATH"
            " uv run forge extension enable --scope user --profile standard"
        )
        assert synced_container.exec(enable).returncode == 0

        config = synced_container.read_file("/tmp/codex-home/config.toml")
        assert config.startswith('model = "gpt-5.5-codex"\n')
        assert "# >>> forge hooks >>>" in config

        result = synced_container.exec(
            "cd /forge && CODEX_HOME=/tmp/codex-home uv run forge extension disable --scope user --yes"
        )
        assert result.returncode == 0
        assert synced_container.read_file("/tmp/codex-home/config.toml") == 'model = "gpt-5.5-codex"\n'
