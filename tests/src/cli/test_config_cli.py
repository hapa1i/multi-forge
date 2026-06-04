"""Tests for forge config CLI commands.

Note: the autouse `isolate_forge_home` fixture (tests/conftest.py) already
sets FORGE_HOME to an isolated temp directory for every test. Tests use
`get_forge_home()` to get the path rather than the `forge_home` fixture
(which clashes with the autouse fixture's mkdir).
"""

from __future__ import annotations

from click.testing import CliRunner

from forge.cli.config_cmd import config
from forge.core.paths import get_forge_home
from forge.runtime_config import reset_runtime_config


class TestConfigShow:
    """Tests for `forge config show`."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_show_auto_creates_and_displays_defaults(self):
        runner = CliRunner()
        result = runner.invoke(config, ["show"])
        assert result.exit_code == 0
        assert "proxy_mode" in result.output
        assert "Path:" in result.output

    def test_show_with_file(self):
        home = get_forge_home()
        (home / "config.yaml").write_text("proxy_mode: sidecar\n")
        runner = CliRunner()
        result = runner.invoke(config, ["show"])
        assert result.exit_code == 0
        assert "sidecar" in result.output

    def test_show_raw_output(self):
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--raw"])
        assert result.exit_code == 0
        assert "proxy_mode: host" in result.output
        assert "Forge Runtime Config" not in result.output

    def test_bare_config_prints_help(self):
        """Bare non-leaf command orients users; `show` is the explicit action."""
        runner = CliRunner()
        result = runner.invoke(config)
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "forge config show" in result.output
        assert "Commands:" in result.output
        assert "proxy_mode: host" not in result.output

    def test_help_marks_subcommand_optional(self):
        """Help usage should match the bare `forge config` help behavior."""
        runner = CliRunner()
        result = runner.invoke(config, ["--help"])
        assert result.exit_code == 0
        assert "Usage: config [OPTIONS] [COMMAND] [ARGS]..." in result.output

    def test_show_annotates_env_overrides(self, monkeypatch):
        """Env-overridden fields are annotated in show output."""
        monkeypatch.setenv("FORGE_DEBUG", "1")
        reset_runtime_config()
        runner = CliRunner()
        result = runner.invoke(config, ["show"])
        assert result.exit_code == 0
        assert "FORGE_DEBUG" in result.output
        assert "debug" in result.output


class TestConfigSet:
    """Tests for `forge config set`."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_set_creates_file(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "proxy_mode=sidecar"])
        assert result.exit_code == 0
        assert "Set" in result.output
        assert (get_forge_home() / "config.yaml").exists()

    def test_set_updates_existing_file(self):
        home = get_forge_home()
        (home / "config.yaml").write_text("proxy_mode: host\n")
        runner = CliRunner()
        result = runner.invoke(config, ["set", "proxy_mode=sidecar"])
        assert result.exit_code == 0
        content = (home / "config.yaml").read_text()
        assert "sidecar" in content

    def test_set_integer_coercion(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "context_limit=1000000"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["context_limit"] == 1000000

    def test_set_float_coercion(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "status_timeout=0.5"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["status_timeout"] == 0.5

    def test_set_unknown_key_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "unknown_key=foo"])
        assert result.exit_code == 1
        assert "Unknown config key" in result.output

    def test_set_invalid_value_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "proxy_mode=invalid"])
        assert result.exit_code == 1
        assert "Invalid configuration" in result.output

    def test_set_bad_format_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "no_equals_sign"])
        assert result.exit_code == 1
        assert "Expected format" in result.output

    def test_set_invalid_integer_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "context_limit=not_a_number"])
        assert result.exit_code == 1
        assert "Invalid value" in result.output

    def test_set_bool_true_values(self):
        runner = CliRunner()
        for val in ("true", "True", "1", "yes", "on"):
            result = runner.invoke(config, ["set", f"log_tool_failures={val}"])
            assert result.exit_code == 0, f"Failed for value: {val}"
            import yaml

            data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
            assert data["log_tool_failures"] is True, f"Expected True for: {val}"

    def test_set_bool_false_values(self):
        runner = CliRunner()
        for val in ("false", "False", "0", "no", "off"):
            result = runner.invoke(config, ["set", f"log_tool_failures={val}"])
            assert result.exit_code == 0, f"Failed for value: {val}"
            import yaml

            data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
            assert data["log_tool_failures"] is False, f"Expected False for: {val}"

    def test_set_bool_invalid_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "log_tool_failures=maybe"])
        assert result.exit_code == 1
        assert "Invalid value" in result.output

    def test_set_removed_key_rejected(self):
        """Setting the removed show_rate_limits key errors and names the replacement."""
        runner = CliRunner()
        result = runner.invoke(config, ["set", "show_rate_limits=true"])
        assert result.exit_code == 1
        assert "was removed" in result.output
        assert "statusline.segments" in result.output

    def test_reset_removed_key_rejected(self):
        # reset short-circuits when no config file exists, so write one first.
        (get_forge_home() / "config.yaml").write_text("log_level: debug\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "show_rate_limits"])
        assert result.exit_code == 1
        assert "was removed" in result.output
        assert "statusline.segments" in result.output

    def test_set_renamed_key_rejected(self):
        """Setting the old name errors and names the new key."""
        runner = CliRunner()
        result = runner.invoke(config, ["set", "handoff_timeout=99"])
        assert result.exit_code == 1
        assert "renamed" in result.output
        assert "memory_writer_timeout" in result.output

    def test_set_new_key_prunes_stale_alias(self):
        """Following the rename tip removes the lingering old key (no permanent warning)."""
        home = get_forge_home()
        (home / "config.yaml").write_text("handoff_timeout: 600\n")
        runner = CliRunner()
        result = runner.invoke(config, ["set", "memory_writer_timeout=600"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((home / "config.yaml").read_text())
        assert data["memory_writer_timeout"] == 600
        assert "handoff_timeout" not in data


class TestConfigAutoCreate:
    """Tests for auto-creation of config file on first access."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_show_auto_creates_file(self):
        config_path = get_forge_home() / "config.yaml"
        assert not config_path.exists()
        runner = CliRunner()
        result = runner.invoke(config, ["show"])
        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert "proxy_mode: host" in content

    def test_auto_created_file_not_overwritten(self):
        home = get_forge_home()
        config_path = home / "config.yaml"
        config_path.write_text("proxy_mode: sidecar\n")
        runner = CliRunner()
        runner.invoke(config, ["show"])
        assert "sidecar" in config_path.read_text()


class TestConfigReset:
    """Tests for `forge config reset`."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_reset_all_deletes_file(self):
        home = get_forge_home()
        (home / "config.yaml").write_text("proxy_mode: sidecar\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "--force"])
        assert result.exit_code == 0
        assert "Reset" in result.output
        assert not (home / "config.yaml").exists()

    def test_reset_single_key(self):
        home = get_forge_home()
        (home / "config.yaml").write_text("proxy_mode: sidecar\nstatus_timeout: 0.5\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "proxy_mode"])
        assert result.exit_code == 0
        assert "Reset" in result.output
        import yaml

        data = yaml.safe_load((home / "config.yaml").read_text())
        assert "proxy_mode" not in data
        assert data["status_timeout"] == 0.5

    def test_reset_no_file(self):
        runner = CliRunner()
        result = runner.invoke(config, ["reset"])
        assert result.exit_code == 0
        assert "already using defaults" in result.output

    def test_reset_unknown_key_rejected(self):
        (get_forge_home() / "config.yaml").write_text("proxy_mode: host\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "unknown_key"])
        assert result.exit_code == 1
        assert "Unknown config key" in result.output

    def test_reset_key_not_in_file(self):
        (get_forge_home() / "config.yaml").write_text("proxy_mode: host\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "status_timeout"])
        assert result.exit_code == 0
        assert "already using default" in result.output

    def test_reset_last_key_removes_file(self):
        """Resetting the only key in the file removes the file."""
        home = get_forge_home()
        (home / "config.yaml").write_text("proxy_mode: sidecar\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "proxy_mode"])
        assert result.exit_code == 0
        assert not (home / "config.yaml").exists()

    def test_reset_renamed_key_rejected(self):
        """Resetting the old name errors and names the new key."""
        (get_forge_home() / "config.yaml").write_text("memory_writer_timeout: 120\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "handoff_timeout"])
        assert result.exit_code == 1
        assert "renamed" in result.output
        assert "memory_writer_timeout" in result.output

    def test_reset_new_key_prunes_stale_alias(self):
        """Resetting the new key also clears a lingering old alias."""
        home = get_forge_home()
        (home / "config.yaml").write_text("proxy_mode: sidecar\nhandoff_timeout: 600\nmemory_writer_timeout: 120\n")
        runner = CliRunner()
        result = runner.invoke(config, ["reset", "memory_writer_timeout"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((home / "config.yaml").read_text())
        assert "memory_writer_timeout" not in data
        assert "handoff_timeout" not in data
        assert data["proxy_mode"] == "sidecar"


class TestConfigSetStatusline:
    """Tests for nested `forge config set statusline.<key>=<value>`."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_set_cost_mode_persists_nested(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.cost_mode=subscription"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["statusline"]["cost_mode"] == "subscription"

    def test_set_segments_comma_list(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.segments=path,model,rate_limits"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["statusline"]["segments"] == ["path", "model", "rate_limits"]

    def test_set_int_subfield(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.cache_hit_ttl=30"])
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["statusline"]["cache_hit_ttl"] == 30

    def test_set_invalid_enum_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.cost_mode=wat"])
        assert result.exit_code == 1
        assert "Invalid statusline.cost_mode" in result.output

    def test_set_unknown_segment_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.segments=path,bogus"])
        assert result.exit_code == 1
        assert "Unknown segment" in result.output
        assert "bogus" in result.output

    def test_set_reserved_future_segment_rejected(self):
        # Reserved names (cache_hit/supervisor/...) have no producer yet, so they
        # are not in the allowlist and must be rejected — otherwise they would
        # silently render nothing. They become settable when their phase lands.
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.segments=cache_hit"])
        assert result.exit_code == 1
        assert "Unknown segment" in result.output
        assert "cache_hit" in result.output

    def test_set_unknown_subkey_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.nope=1"])
        assert result.exit_code == 1
        assert "Unknown statusline key" in result.output

    def test_set_unknown_section_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "bogus.key=1"])
        assert result.exit_code == 1
        assert "Unknown config section" in result.output

    def test_set_preserves_other_statusline_keys(self):
        runner = CliRunner()
        assert runner.invoke(config, ["set", "statusline.cost_mode=api"]).exit_code == 0
        assert runner.invoke(config, ["set", "statusline.palette=earthy"]).exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["statusline"]["cost_mode"] == "api"
        assert data["statusline"]["palette"] == "earthy"

    def test_show_renders_statusline_block(self):
        runner = CliRunner()
        runner.invoke(config, ["set", "statusline.cost_mode=subscription"])
        result = runner.invoke(config, ["show", "--raw"])
        assert result.exit_code == 0
        assert "statusline:" in result.output
        assert "cost_mode: subscription" in result.output

    def test_reset_statusline_section(self):
        runner = CliRunner()
        runner.invoke(config, ["set", "statusline.cost_mode=subscription"])
        result = runner.invoke(config, ["reset", "statusline", "-y"])
        assert result.exit_code == 0
        # File may be removed (only key) or statusline dropped; either way default applies.
        reset_runtime_config()
        from forge.runtime_config import load_runtime_config

        rc = load_runtime_config()
        assert rc.statusline.cost_mode == "auto"


class TestConfigEditStatusline:
    """`forge config edit` must also enforce the segment allowlist (strict gate)."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def _run_edit_with(self, content: str, monkeypatch):
        from pathlib import Path

        from forge.cli import config_cmd

        def fake_run(cmd, *a, **k):
            # cmd = [editor, tmp_path]; simulate the user's edits to the temp file.
            Path(cmd[1]).write_text(content)

            class _Result:
                returncode = 0

            return _Result()

        monkeypatch.setattr(config_cmd.subprocess, "run", fake_run)
        monkeypatch.setenv("EDITOR", "true")
        return CliRunner().invoke(config, ["edit"])

    def test_edit_rejects_unknown_segment(self, monkeypatch):
        result = self._run_edit_with("statusline:\n  segments: [path, bogus]\n", monkeypatch)
        assert result.exit_code == 1
        assert "segment" in result.output.lower()
        assert "bogus" in result.output

    def test_edit_rejects_invalid_enum(self, monkeypatch):
        result = self._run_edit_with("statusline:\n  cost_mode: wat\n", monkeypatch)
        assert result.exit_code == 1
        assert "cost_mode" in result.output

    def test_edit_accepts_valid_statusline(self, monkeypatch):
        result = self._run_edit_with("statusline:\n  segments: [path, model]\n  cost_mode: api\n", monkeypatch)
        assert result.exit_code == 0
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["statusline"]["segments"] == ["path", "model"]
        assert data["statusline"]["cost_mode"] == "api"
