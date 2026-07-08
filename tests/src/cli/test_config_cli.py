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
from forge.runtime_config import get_runtime_config, reset_runtime_config


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
        assert "# Proxy execution mode." in result.output
        assert "proxy_mode: host" in result.output
        assert "# Provider-trace observability preferences." in result.output
        assert "Forge Runtime Config" not in result.output

    def test_show_displays_commented_yaml(self):
        runner = CliRunner()
        result = runner.invoke(config, ["show"])
        assert result.exit_code == 0
        assert "# Status-line display preferences." in result.output
        assert "# Ordered segment list." in result.output
        assert "provider_trace:" in result.output

    def test_bare_config_prints_help(self):
        """Bare non-leaf prints help to stderr and exits 2 (usage error), like every other group."""
        runner = CliRunner()
        result = runner.invoke(config)
        assert result.exit_code == 2
        assert "Usage:" in result.stderr
        assert "forge config show" in result.stderr
        assert "Commands:" in result.stderr
        assert "proxy_mode: host" not in result.stderr

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

    def test_show_help_documents_json_shape(self):
        result = CliRunner().invoke(config, ["show", "--help"])

        assert result.exit_code == 0
        assert "{path, env_sources, config}" in result.output


class TestConfigShowJson:
    """Tests for `forge config show --json`.

    Shape: {path, env_sources, config} where config is the effective
    RuntimeConfig mapping (nested sections render as plain dicts).
    """

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_json_has_three_top_level_keys(self):
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--json"])
        assert result.exit_code == 0
        import json

        payload = json.loads(result.output)
        assert set(payload.keys()) == {"path", "env_sources", "config"}

    def test_json_path_points_at_config_file(self):
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--json"])
        assert result.exit_code == 0
        import json

        payload = json.loads(result.output)
        assert payload["path"] == str(get_forge_home() / "config.yaml")

    def test_json_config_contains_known_runtime_fields(self):
        """config maps every RuntimeConfig field, including nested sections."""
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--json"])
        assert result.exit_code == 0
        assert "#" not in result.output
        import json
        from dataclasses import fields

        from forge.runtime_config import RuntimeConfig

        payload = json.loads(result.output)
        cfg = payload["config"]
        expected = {f.name for f in fields(RuntimeConfig)}
        assert set(cfg.keys()) == expected
        # Spot-check representative fields across types (str/int/nested).
        assert cfg["proxy_mode"] == "host"
        assert cfg["context_limit"] == 200000
        # Nested dataclasses must serialize as plain mappings (json can't dump a
        # dataclass instance; show_cmd asdict()s them).
        assert isinstance(cfg["statusline"], dict)
        assert isinstance(cfg["provider_trace"], dict)

    def test_json_env_sources_empty_without_overrides(self):
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--json"])
        assert result.exit_code == 0
        import json

        payload = json.loads(result.output)
        assert payload["env_sources"] == {}

    def test_json_reflects_file_values(self):
        (get_forge_home() / "config.yaml").write_text("proxy_mode: sidecar\n")
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--json"])
        assert result.exit_code == 0
        import json

        payload = json.loads(result.output)
        assert payload["config"]["proxy_mode"] == "sidecar"

    def test_json_surfaces_env_override_in_env_sources(self, monkeypatch):
        """An env override is reported in env_sources AND applied in config.

        Mirrors test_show_annotates_env_overrides: FORGE_DEBUG maps to log_level.
        """
        monkeypatch.setenv("FORGE_DEBUG", "1")
        reset_runtime_config()
        runner = CliRunner()
        result = runner.invoke(config, ["show", "--json"])
        assert result.exit_code == 0
        import json

        payload = json.loads(result.output)
        assert payload["env_sources"] == {"log_level": "FORGE_DEBUG"}
        assert payload["config"]["log_level"] == "debug"


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
        content = (get_forge_home() / "config.yaml").read_text()
        assert "# Proxy execution mode." in content
        assert "proxy_mode: sidecar" in content

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
        assert result.stdout == ""
        assert "Unknown config key" in result.stderr
        assert "Available keys" in result.stderr

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

    def test_set_help_shows_nested_key_examples(self):
        result = CliRunner().invoke(config, ["set", "--help"])

        assert result.exit_code == 0
        assert "statusline.cost_mode=actual" in result.output
        assert "provider_trace.inject_provider_user=true" in result.output

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
        result = runner.invoke(config, ["reset", "--yes"])
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
        assert result.stdout == ""
        assert "Unknown config key" in result.stderr
        assert "Available keys" in result.stderr

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
        assert result.stdout == ""
        assert "Unknown segment" in result.stderr
        assert "bogus" in result.stderr
        assert "Valid segments" in result.stderr

    def test_set_forge_unique_segments_accepted(self):
        # All Forge-unique opt-in segments (Phases 4-5) are in the allowlist.
        runner = CliRunner()
        result = runner.invoke(
            config,
            [
                "set",
                "statusline.segments=path,hooks,supervisor,policy,audit,drift,spend_cap",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_set_unknown_subkey_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "statusline.nope=1"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Unknown statusline key" in result.stderr
        assert "Available" in result.stderr

    def test_set_unknown_section_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "bogus.key=1"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Unknown config section" in result.stderr
        assert "Nested sections" in result.stderr

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


class TestConfigSetProviderTrace:
    """Tests for nested `forge config set provider_trace.inject_provider_user=...`."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_set_inject_provider_user_true_round_trips(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "provider_trace.inject_provider_user=true"])
        assert result.exit_code == 0, result.output
        import yaml

        data = yaml.safe_load((get_forge_home() / "config.yaml").read_text())
        assert data["provider_trace"]["inject_provider_user"] is True
        # Round-trips through the loader (the value the proxied + direct paths read).
        assert get_runtime_config().provider_trace.inject_provider_user is True

    def test_set_inject_provider_user_false(self):
        runner = CliRunner()
        assert runner.invoke(config, ["set", "provider_trace.inject_provider_user=false"]).exit_code == 0
        assert get_runtime_config().provider_trace.inject_provider_user is False

    def test_set_invalid_bool_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "provider_trace.inject_provider_user=maybe"])
        assert result.exit_code == 1
        assert "Invalid value for 'provider_trace.inject_provider_user'" in result.output

    def test_set_unknown_subkey_rejected(self):
        runner = CliRunner()
        result = runner.invoke(config, ["set", "provider_trace.nope=1"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Unknown provider_trace key" in result.stderr
        assert "Available" in result.stderr

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


class TestConfigEdit:
    """`forge config edit` is a write surface: it must reject unknown nested subkeys and bad values
    (strict gate, parity with `forge config set`), not silently drop them."""

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
        assert result.stdout == ""
        assert "segment" in result.stderr.lower()
        assert "bogus" in result.stderr
        assert "Your changes are saved at" in result.stderr

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

    def test_edit_rejects_unknown_provider_trace_subkey(self, monkeypatch):
        # A misspelled subkey must NOT silently persist while the toggle stays off (the edit-path
        # fail-open hole: RuntimeConfig construction drops unknown nested subkeys, then the original
        # YAML is written). Parity with `forge config set`, which already rejects unknown subkeys.
        result = self._run_edit_with("provider_trace:\n  inject_provider_usre: true\n", monkeypatch)
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "provider_trace" in result.stderr
        assert "inject_provider_usre" in result.stderr
        assert "Your changes are saved at" in result.stderr

    def test_edit_accepts_valid_provider_trace(self, monkeypatch):
        result = self._run_edit_with("provider_trace:\n  inject_provider_user: true\n", monkeypatch)
        assert result.exit_code == 0
        # The toggle actually loads on after the edit (the whole point of the user-facing switch).
        assert get_runtime_config().provider_trace.inject_provider_user is True
