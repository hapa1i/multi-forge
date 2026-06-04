"""Tests for forge.runtime_config module.

Covers: RuntimeConfig dataclass, load_runtime_config(), get_runtime_config()
singleton, write_runtime_config(), and get_default_config_content().

Note: the autouse `isolate_forge_home` fixture (tests/conftest.py) already
sets FORGE_HOME to tmp_path/forge_home for every test. Tests that need the
path use `get_forge_home()` directly rather than the `forge_home` fixture
(which would clash with the autouse fixture's mkdir).
"""

from __future__ import annotations

import logging
from dataclasses import fields
from pathlib import Path

import pytest

from forge.core.paths import get_forge_home
from forge.runtime_config import (
    RuntimeConfig,
    StatusLineConfig,
    get_default_config_content,
    get_runtime_config,
    load_runtime_config,
    reset_runtime_config,
    write_runtime_config,
)

# ---------------------------------------------------------------------------
# RuntimeConfig dataclass
# ---------------------------------------------------------------------------


class TestRuntimeConfigDefaults:
    def test_default_proxy_mode_is_host(self):
        rc = RuntimeConfig()
        assert rc.proxy_mode == "host"

    def test_default_sidecar_image(self):
        rc = RuntimeConfig()
        assert rc.sidecar_image == "forge-sidecar:latest"

    def test_context_limit(self):
        rc = RuntimeConfig()
        assert rc.context_limit == 200000

    def test_default_direct_model_is_opt_in(self):
        rc = RuntimeConfig()
        assert rc.default_direct_model == ""

    def test_default_status_timeout(self):
        rc = RuntimeConfig()
        assert rc.status_timeout == 2.0

    def test_default_memory_writer_timeout(self):
        rc = RuntimeConfig()
        assert rc.memory_writer_timeout == 300

    def test_default_user_agent_version_empty(self):
        rc = RuntimeConfig()
        assert rc.user_agent_claude_code_version == ""

    def test_tool_failure_logging_is_opt_in(self):
        rc = RuntimeConfig()
        assert rc.log_tool_failures is False

    def test_auth_ignore_env_defaults_false(self):
        rc = RuntimeConfig()
        assert rc.auth_ignore_env is False


class TestRuntimeConfigValidation:
    def test_invalid_proxy_mode_rejected(self):
        with pytest.raises(ValueError, match="Invalid proxy_mode"):
            RuntimeConfig(proxy_mode="invalid")

    def test_sidecar_proxy_mode_accepted(self):
        rc = RuntimeConfig(proxy_mode="sidecar")
        assert rc.proxy_mode == "sidecar"

    def test_host_proxy_mode_accepted(self):
        rc = RuntimeConfig(proxy_mode="host")
        assert rc.proxy_mode == "host"

    def test_zero_context_limit_rejected(self):
        with pytest.raises(ValueError, match="context_limit must be >= 1"):
            RuntimeConfig(context_limit=0)

    def test_negative_context_limit_rejected(self):
        with pytest.raises(ValueError, match="context_limit must be >= 1"):
            RuntimeConfig(context_limit=-100)

    def test_zero_status_timeout_rejected(self):
        with pytest.raises(ValueError, match="status_timeout must be > 0"):
            RuntimeConfig(status_timeout=0)

    def test_negative_status_timeout_rejected(self):
        with pytest.raises(ValueError, match="status_timeout must be > 0"):
            RuntimeConfig(status_timeout=-1.0)

    def test_zero_memory_writer_timeout_rejected(self):
        with pytest.raises(ValueError, match="memory_writer_timeout must be >= 1"):
            RuntimeConfig(memory_writer_timeout=0)

    def test_negative_log_retention_days_rejected(self):
        with pytest.raises(ValueError, match="log_retention_days must be >= 0"):
            RuntimeConfig(log_retention_days=-1)

    def test_zero_log_retention_days_accepted(self):
        rc = RuntimeConfig(log_retention_days=0)
        assert rc.log_retention_days == 0

    def test_positive_log_retention_days_accepted(self):
        rc = RuntimeConfig(log_retention_days=30)
        assert rc.log_retention_days == 30

    def test_negative_session_retention_days_rejected(self):
        with pytest.raises(ValueError, match="session_retention_days must be >= 0"):
            RuntimeConfig(session_retention_days=-1)

    def test_zero_session_retention_days_accepted(self):
        rc = RuntimeConfig(session_retention_days=0)
        assert rc.session_retention_days == 0

    def test_positive_session_retention_days_accepted(self):
        rc = RuntimeConfig(session_retention_days=90)
        assert rc.session_retention_days == 90

    def test_custom_values_accepted(self):
        rc = RuntimeConfig(
            proxy_mode="sidecar",
            sidecar_image="custom:v2",
            context_limit=1000000,
            status_timeout=0.5,
            memory_writer_timeout=60,
        )
        assert rc.proxy_mode == "sidecar"
        assert rc.sidecar_image == "custom:v2"
        assert rc.context_limit == 1000000
        assert rc.status_timeout == 0.5
        assert rc.memory_writer_timeout == 60


# ---------------------------------------------------------------------------
# load_runtime_config()
# ---------------------------------------------------------------------------


class TestLoadRuntimeConfig:
    def test_missing_file_returns_defaults(self, tmp_path: Path):
        rc = load_runtime_config(tmp_path / "nonexistent.yaml")
        assert rc.proxy_mode == "host"
        assert rc.context_limit == 200000

    def test_empty_file_returns_defaults(self, tmp_path: Path):
        """Empty YAML file (yaml.safe_load returns None)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "host"

    def test_non_mapping_yaml_returns_defaults(self, tmp_path: Path):
        """YAML that parses to a list, not a dict."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("- item1\n- item2\n")
        rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "host"

    def test_valid_yaml_parsed(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("proxy_mode: sidecar\nstatus_timeout: 0.5\n")
        rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "sidecar"
        assert rc.status_timeout == 0.5

    def test_log_tool_failures_yaml_parsed(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("log_tool_failures: true\n")
        rc = load_runtime_config(config_file)
        assert rc.log_tool_failures is True

    def test_partial_yaml_uses_defaults_for_missing(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("proxy_mode: sidecar\n")
        rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "sidecar"
        assert rc.context_limit == 200000  # Default preserved
        assert rc.status_timeout == 2.0  # Default preserved

    def test_default_direct_model_yaml_roundtrip(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text('default_direct_model: "claude-sonnet-4-6"\n')
        rc = load_runtime_config(config_file)
        assert rc.default_direct_model == "claude-sonnet-4-6"

    def test_unknown_keys_warned_and_ignored(self, tmp_path: Path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("proxy_mode: host\nfuture_setting: true\nanother_key: 42\n")
        with caplog.at_level(logging.WARNING):
            rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "host"
        assert "Unknown keys" in caplog.text
        assert "another_key" in caplog.text
        assert "future_setting" in caplog.text

    def test_invalid_value_falls_back_to_defaults(self, tmp_path: Path, caplog):
        """Invalid proxy_mode triggers validation error → fall back to defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("proxy_mode: invalid_mode\n")
        with caplog.at_level(logging.WARNING):
            rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "host"  # Fell back to default
        assert "Invalid config" in caplog.text

    def test_invalid_yaml_syntax_returns_defaults(self, tmp_path: Path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("proxy_mode: [\n")  # Broken YAML
        with caplog.at_level(logging.WARNING):
            rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "host"
        assert "Failed to read" in caplog.text

    def test_unreadable_file_returns_defaults(self, tmp_path: Path, caplog):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("proxy_mode: sidecar\n")
        config_file.chmod(0o000)
        with caplog.at_level(logging.WARNING):
            rc = load_runtime_config(config_file)
        assert rc.proxy_mode == "host"
        # Restore permissions for cleanup
        config_file.chmod(0o644)

    def test_integer_and_float_types_preserved(self, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("context_limit: 1000000\nstatus_timeout: 0.25\nmemory_writer_timeout: 60\n")
        rc = load_runtime_config(config_file)
        assert rc.context_limit == 1000000
        assert rc.status_timeout == 0.25
        assert rc.memory_writer_timeout == 60

    def test_memory_writer_timeout_yaml_parsed(self, tmp_path: Path):
        """New config key is respected."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("memory_writer_timeout: 120\n")
        rc = load_runtime_config(config_file)
        assert rc.memory_writer_timeout == 120

    def test_renamed_handoff_timeout_warned_and_ignored(self, tmp_path: Path, caplog):
        """Old key 'handoff_timeout' warns with rename guidance; value is ignored (degrades to default)."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("handoff_timeout: 600\n")
        with caplog.at_level(logging.WARNING):
            rc = load_runtime_config(config_file)
        assert rc.memory_writer_timeout == 300  # old value NOT applied
        assert "handoff_timeout" in caplog.text
        assert "memory_writer_timeout" in caplog.text
        assert "renamed" in caplog.text
        # Renamed keys get a targeted warning, not the generic "Unknown keys" line.
        assert "Unknown keys" not in caplog.text

    def test_removed_show_rate_limits_warned_with_replacement(self, tmp_path: Path, caplog):
        """Removed key 'show_rate_limits' warns naming the statusline.segments replacement."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("show_rate_limits: true\n")
        with caplog.at_level(logging.WARNING):
            load_runtime_config(config_file)
        assert "show_rate_limits" in caplog.text
        assert "removed" in caplog.text
        assert "statusline.segments" in caplog.text
        # Removed keys get a targeted warning, not the generic "Unknown keys" line.
        assert "Unknown keys" not in caplog.text


# ---------------------------------------------------------------------------
# get_runtime_config() singleton
# ---------------------------------------------------------------------------


class TestGetRuntimeConfig:
    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_returns_runtime_config(self):
        rc = get_runtime_config()
        assert isinstance(rc, RuntimeConfig)

    def test_singleton_is_cached(self):
        rc1 = get_runtime_config()
        rc2 = get_runtime_config()
        assert rc1 is rc2

    def test_reset_clears_cache(self):
        rc1 = get_runtime_config()
        reset_runtime_config()
        rc2 = get_runtime_config()
        assert rc1 is not rc2

    def test_loads_from_forge_home(self):
        """Singleton reads from FORGE_HOME/config.yaml."""
        home = get_forge_home()
        config_file = home / "config.yaml"
        config_file.write_text("proxy_mode: sidecar\n")

        reset_runtime_config()
        rc = get_runtime_config()
        assert rc.proxy_mode == "sidecar"


# ---------------------------------------------------------------------------
# write_runtime_config()
# ---------------------------------------------------------------------------


class TestWriteRuntimeConfig:
    def test_writes_yaml_file(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        write_runtime_config({"proxy_mode": "sidecar"}, path=config_path)
        assert config_path.exists()
        content = config_path.read_text()
        assert "proxy_mode: sidecar" in content

    def test_creates_parent_directories(self, tmp_path: Path):
        config_path = tmp_path / "subdir" / "config.yaml"
        write_runtime_config({"proxy_mode": "host"}, path=config_path)
        assert config_path.exists()

    def test_atomic_write_no_partial_on_error(self, tmp_path: Path):
        """If write fails after temp file created, original file is untouched."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text("original content")

        # Make os.replace fail so the atomic swap doesn't complete
        from unittest.mock import patch

        with patch("forge.runtime_config.os.replace", side_effect=OSError("mock replace")):
            with pytest.raises(OSError, match="mock replace"):
                write_runtime_config({"proxy_mode": "sidecar"}, path=config_path)

        # Original file untouched
        assert config_path.read_text() == "original content"
        # No temp file left behind
        temps = list(tmp_path.glob(".*config*.tmp"))
        assert temps == []

    def test_invalidates_singleton_cache(self):
        home = get_forge_home()
        reset_runtime_config()

        rc1 = get_runtime_config()
        assert rc1.proxy_mode == "host"

        write_runtime_config(
            {"proxy_mode": "sidecar"},
            path=home / "config.yaml",
        )

        # Cache was invalidated by write
        rc2 = get_runtime_config()
        assert rc2.proxy_mode == "sidecar"
        assert rc1 is not rc2

    def test_roundtrip_preserves_values(self, tmp_path: Path):
        config_path = tmp_path / "config.yaml"
        data = {
            "proxy_mode": "sidecar",
            "sidecar_image": "custom:v3",
            "context_limit": 500000,
            "status_timeout": 1.5,
        }
        write_runtime_config(data, path=config_path)
        rc = load_runtime_config(config_path)
        assert rc.proxy_mode == "sidecar"
        assert rc.sidecar_image == "custom:v3"
        assert rc.context_limit == 500000
        assert rc.status_timeout == 1.5


# ---------------------------------------------------------------------------
# get_default_config_content()
# ---------------------------------------------------------------------------


class TestGetDefaultConfigContent:
    def test_returns_string(self):
        content = get_default_config_content()
        assert isinstance(content, str)

    def test_contains_proxy_mode(self):
        content = get_default_config_content()
        assert "proxy_mode: host" in content

    def test_parseable_as_yaml(self):
        import yaml

        content = get_default_config_content()
        data = yaml.safe_load(content)
        assert isinstance(data, dict)
        assert data["proxy_mode"] == "host"

    def test_contains_all_documented_keys(self):
        content = get_default_config_content()
        for key in [
            "proxy_mode",
            "sidecar_image",
            "user_agent_claude_code_version",
            "default_direct_model",
            "context_limit",
            "status_timeout",
            "memory_writer_timeout",
            "log_tool_failures",
            "auth_ignore_env",
        ]:
            assert key in content, f"Missing key in default content: {key}"


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Environment variable overrides
# ---------------------------------------------------------------------------


class TestEnvVarOverrides:
    """Test three-layer resolution: defaults -> YAML -> env vars."""

    def setup_method(self):
        reset_runtime_config()

    def teardown_method(self):
        reset_runtime_config()

    def test_forge_debug_1_sets_log_level_debug(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        rc = load_runtime_config(tmp_path / "nonexistent.yaml")
        assert rc.log_level == "debug"

    def test_forge_debug_0_sets_log_level_off(self, monkeypatch, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text('log_level: "debug"\n')
        monkeypatch.setenv("FORGE_DEBUG", "0")
        rc = load_runtime_config(config_file)
        assert rc.log_level == "off"

    def test_forge_debug_overrides_yaml(self, monkeypatch, tmp_path: Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text('log_level: "info"\n')
        monkeypatch.setenv("FORGE_DEBUG", "1")
        rc = load_runtime_config(config_file)
        assert rc.log_level == "debug"

    def test_env_sources_tracked(self, monkeypatch, tmp_path: Path):
        """Verify _env_sources dict is attached for %config annotations."""
        monkeypatch.setenv("FORGE_DEBUG", "1")
        rc = load_runtime_config(tmp_path / "nonexistent.yaml")
        env_sources = getattr(rc, "_env_sources", {})
        assert env_sources == {
            "log_level": "FORGE_DEBUG",
        }

    def test_env_sources_empty_when_no_overrides(self, monkeypatch, tmp_path: Path):
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        rc = load_runtime_config(tmp_path / "nonexistent.yaml")
        env_sources = getattr(rc, "_env_sources", {})
        assert env_sources == {}

    def test_forge_debug_passthrough_info(self, monkeypatch, tmp_path: Path):
        """FORGE_DEBUG=info passes through as log_level=info."""
        monkeypatch.setenv("FORGE_DEBUG", "info")
        rc = load_runtime_config(tmp_path / "nonexistent.yaml")
        assert rc.log_level == "info"

    def test_forge_debug_passthrough_warning(self, monkeypatch, tmp_path: Path):
        """FORGE_DEBUG=warning passes through as log_level=warning."""
        monkeypatch.setenv("FORGE_DEBUG", "warning")
        rc = load_runtime_config(tmp_path / "nonexistent.yaml")
        assert rc.log_level == "warning"

    def test_env_overrides_mapping_targets_valid_fields(self):
        """Invariant: every _ENV_OVERRIDES target must be a real RuntimeConfig field."""
        from forge.runtime_config import _ENV_OVERRIDES

        valid_fields = {f.name for f in fields(RuntimeConfig)}
        for env_var, field_name in _ENV_OVERRIDES.items():
            assert field_name in valid_fields, (
                f"_ENV_OVERRIDES[{env_var!r}] targets {field_name!r} " f"which is not a RuntimeConfig field"
            )


# ---------------------------------------------------------------------------
# StatusLineConfig (nested statusline: section)
# ---------------------------------------------------------------------------


class TestStatusLineConfigDefaults:
    def test_runtime_config_has_statusline_default(self):
        rc = RuntimeConfig()
        assert isinstance(rc.statusline, StatusLineConfig)

    def test_statusline_field_defaults(self):
        sl = StatusLineConfig()
        assert sl.segments == []
        assert sl.cost_mode == "auto"
        assert sl.palette == "default"
        assert sl.glyphs == "ascii"
        assert sl.cache_hit == "auto"
        assert sl.cache_hit_ttl == 12


class TestStatusLineConfigValidation:
    def test_invalid_cost_mode_rejected(self):
        with pytest.raises(ValueError, match="Invalid statusline.cost_mode"):
            StatusLineConfig(cost_mode="wat")

    def test_invalid_palette_rejected(self):
        with pytest.raises(ValueError, match="Invalid statusline.palette"):
            StatusLineConfig(palette="neon")

    def test_invalid_glyphs_rejected(self):
        with pytest.raises(ValueError, match="Invalid statusline.glyphs"):
            StatusLineConfig(glyphs="emoji")

    def test_invalid_cache_hit_rejected(self):
        with pytest.raises(ValueError, match="Invalid statusline.cache_hit"):
            StatusLineConfig(cache_hit="sometimes")

    def test_cache_hit_ttl_must_be_positive(self):
        with pytest.raises(ValueError, match="cache_hit_ttl must be >= 1"):
            StatusLineConfig(cache_hit_ttl=0)

    def test_segments_must_be_list_of_strings(self):
        with pytest.raises(ValueError, match="segments must be a list of strings"):
            StatusLineConfig(segments=[1, 2])  # type: ignore[list-item]

    def test_segment_names_not_validated_here(self):
        """The dataclass does NOT know valid segment names (renderer/CLI own that)."""
        sl = StatusLineConfig(segments=["not-a-real-segment"])
        assert sl.segments == ["not-a-real-segment"]


class TestStatusLineConfigCoercion:
    def test_dict_coerced_via_runtime_config(self):
        """The set/edit path builds RuntimeConfig(**{statusline: {...}}) directly."""
        # __post_init__ coerces dict -> StatusLineConfig; this test exercises that path.
        rc = RuntimeConfig(statusline={"cost_mode": "subscription", "palette": "earthy"})  # type: ignore[arg-type]
        assert isinstance(rc.statusline, StatusLineConfig)
        assert rc.statusline.cost_mode == "subscription"
        assert rc.statusline.palette == "earthy"

    def test_unknown_subkey_dropped(self):
        """Unknown sub-keys are forward-compatible (dropped, not fatal)."""
        rc = RuntimeConfig(statusline={"cost_mode": "api", "future_key": 123})  # type: ignore[arg-type]  # dict coercion path
        assert rc.statusline.cost_mode == "api"
        assert not hasattr(rc.statusline, "future_key")

    def test_bad_enum_in_dict_raises(self):
        """Construction is strict so set/edit fail closed."""
        with pytest.raises(ValueError, match="Invalid statusline.cost_mode"):
            RuntimeConfig(statusline={"cost_mode": "bogus"})  # type: ignore[arg-type]  # dict coercion path


class TestStatusLineConfigLoad:
    def test_load_round_trips_statusline(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("statusline:\n  cost_mode: subscription\n  segments: [path, model]\n")
        rc = load_runtime_config(cfg)
        assert rc.statusline.cost_mode == "subscription"
        assert rc.statusline.segments == ["path", "model"]

    def test_bad_statusline_subtree_fails_open(self, tmp_path: Path, caplog):
        """A bad statusline resets ONLY statusline; other valid keys survive."""
        cfg = tmp_path / "config.yaml"
        cfg.write_text("status_timeout: 0.5\nstatusline:\n  cost_mode: bogus\n  palette: earthy\n")
        with caplog.at_level(logging.WARNING):
            rc = load_runtime_config(cfg)
        assert rc.status_timeout == 0.5  # unrelated key preserved
        assert rc.statusline.cost_mode == "auto"  # whole subtree reset to defaults
        assert rc.statusline.palette == "default"
        assert any("statusline" in r.message for r in caplog.records)

    def test_missing_statusline_uses_defaults(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("proxy_mode: host\n")
        rc = load_runtime_config(cfg)
        assert rc.statusline == StatusLineConfig()

    def test_write_round_trip(self, tmp_path: Path):
        cfg = tmp_path / "config.yaml"
        write_runtime_config({"statusline": {"glyphs": "unicode", "cache_hit_ttl": 30}}, cfg)
        rc = load_runtime_config(cfg)
        assert rc.statusline.glyphs == "unicode"
        assert rc.statusline.cache_hit_ttl == 30
