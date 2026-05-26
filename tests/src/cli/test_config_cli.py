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
            result = runner.invoke(config, ["set", f"show_rate_limits={val}"])
            assert result.exit_code == 0, f"Failed for value: {val}"
            import yaml

            data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
            assert data["show_rate_limits"] is True, f"Expected True for: {val}"

    def test_set_bool_false_values(self):
        runner = CliRunner()
        for val in ("false", "False", "0", "no", "off"):
            result = runner.invoke(config, ["set", f"show_rate_limits={val}"])
            assert result.exit_code == 0, f"Failed for value: {val}"
            import yaml

            data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
            assert data["show_rate_limits"] is False, f"Expected False for: {val}"

    def test_set_bool_invalid_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "show_rate_limits=maybe"])
        assert result.exit_code == 1
        assert "Invalid value" in result.output


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
