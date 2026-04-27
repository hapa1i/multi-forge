"""Tests for forge.core.logging debug logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from forge.core.logging import (
    configure_console_logging,
    configure_debug_logging,
    find_latest_log,
    get_effective_log_level,
)
from forge.runtime_config import reset_runtime_config


@pytest.fixture(autouse=True)
def _isolate_forge_logger():
    """Save and restore the forge logger state between tests.

    Also resets the RuntimeConfig singleton so env var changes
    (FORGE_DEBUG) are picked up fresh — get_effective_log_level()
    delegates to the singleton.
    """
    reset_runtime_config()
    forge_logger = logging.getLogger("forge")
    original_handlers = forge_logger.handlers[:]
    original_level = forge_logger.level
    original_propagate = forge_logger.propagate
    yield
    # Close any handlers that were added during the test
    for h in forge_logger.handlers:
        if h not in original_handlers:
            h.close()
    forge_logger.handlers = original_handlers
    forge_logger.level = original_level
    forge_logger.propagate = original_propagate
    reset_runtime_config()


class TestLogLevelResolution:
    """Tests for get_effective_log_level()."""

    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        assert get_effective_log_level() == "off"
        assert get_effective_log_level() == "off"

    def test_env_override_1(self, monkeypatch):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        assert get_effective_log_level() == "debug"
        assert get_effective_log_level() != "off"

    def test_env_override_true(self, monkeypatch):
        monkeypatch.setenv("FORGE_DEBUG", "true")
        assert get_effective_log_level() == "debug"

    def test_env_override_yes(self, monkeypatch):
        monkeypatch.setenv("FORGE_DEBUG", "yes")
        assert get_effective_log_level() == "debug"

    def test_env_0_suppresses_config(self, monkeypatch, tmp_path):
        """FORGE_DEBUG=0 suppresses even if config says debug."""
        config_path = tmp_path / "forge_home" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('log_level: "debug"\n')

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)
        monkeypatch.setenv("FORGE_DEBUG", "0")

        assert get_effective_log_level() == "off"

    def test_env_off_suppresses_config(self, monkeypatch, tmp_path):
        """FORGE_DEBUG=off suppresses even if config says debug."""
        config_path = tmp_path / "forge_home" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('log_level: "debug"\n')

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)
        monkeypatch.setenv("FORGE_DEBUG", "off")

        assert get_effective_log_level() == "off"

    def test_config_debug(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        config_path = tmp_path / "forge_home" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('log_level: "debug"\n')

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)

        assert get_effective_log_level() == "debug"
        assert get_effective_log_level() != "off"

    def test_config_info(self, monkeypatch, tmp_path):
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        config_path = tmp_path / "forge_home" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('log_level: "info"\n')

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)

        assert get_effective_log_level() == "info"
        assert get_effective_log_level() != "off"

    def test_env_overrides_config(self, monkeypatch, tmp_path):
        """FORGE_DEBUG=1 overrides config even if config says info."""
        monkeypatch.setenv("FORGE_DEBUG", "1")
        config_path = tmp_path / "forge_home" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('log_level: "info"\n')

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)

        assert get_effective_log_level() == "debug"

    def test_yaml_unquoted_off_survives_roundtrip(self, monkeypatch, tmp_path):
        """Unquoted 'off' in YAML is parsed as False by PyYAML — must coerce back."""
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        config_path = tmp_path / "forge_home" / "config.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("log_level: off\n")  # no quotes — PyYAML reads as False

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)

        assert get_effective_log_level() == "off"


class TestConfigureDebugLogging:
    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        forge_logger = logging.getLogger("forge")
        before = len(forge_logger.handlers)
        configure_debug_logging(component="test", subdirectory="test")
        assert len(forge_logger.handlers) == before

    def test_creates_handler_and_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        forge_logger = logging.getLogger("forge")
        initial = len(forge_logger.handlers)

        configure_debug_logging(component="policy-check", subdirectory="hooks")

        assert len(forge_logger.handlers) == initial + 1
        handler = forge_logger.handlers[-1]
        assert isinstance(handler, RotatingFileHandler)

        log_dir = tmp_path / "forge_home" / "logs" / "hooks"
        assert log_dir.is_dir()

    def test_pid_in_filename(self, monkeypatch, tmp_path):
        """Log filename includes PID for multi-process safety."""
        import os

        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        configure_debug_logging(component="session-start", subdirectory="hooks")

        log_dir = tmp_path / "forge_home" / "logs" / "hooks"
        log_files = list(log_dir.glob("session-start.*.log"))
        assert len(log_files) == 1
        assert str(os.getpid()) in log_files[0].name

    def test_idempotent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        forge_logger = logging.getLogger("forge")
        initial = len(forge_logger.handlers)

        configure_debug_logging(component="test", subdirectory="hooks")
        configure_debug_logging(component="test", subdirectory="hooks")

        assert len(forge_logger.handlers) == initial + 1

    def test_different_component_attaches_new_handler(self, monkeypatch, tmp_path):
        """Different components should be able to attach different log files."""
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        forge_logger = logging.getLogger("forge")
        initial = len(forge_logger.handlers)

        configure_debug_logging(component="a", subdirectory="hooks")
        configure_debug_logging(component="b", subdirectory="hooks")

        assert len(forge_logger.handlers) == initial + 2

    def test_child_logger_inherits(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        configure_debug_logging(component="test", subdirectory="hooks")

        child = logging.getLogger("forge.session.manager")
        assert child.getEffectiveLevel() == logging.DEBUG

    def test_propagate_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        configure_debug_logging(component="test", subdirectory="hooks")

        forge_logger = logging.getLogger("forge")
        assert forge_logger.propagate is False

    def test_failopen_on_permission_error(self, monkeypatch, tmp_path):
        """Permission errors don't crash the command."""
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        from pathlib import Path

        def _raise_permission(*args, **kwargs):
            raise PermissionError("simulated permission denied")

        monkeypatch.setattr(Path, "mkdir", _raise_permission)

        forge_logger = logging.getLogger("forge")
        before = len(forge_logger.handlers)

        # Should not raise
        configure_debug_logging(component="test", subdirectory="hooks")

        # No handler added, but no crash
        assert len(forge_logger.handlers) == before

    def test_writes_to_file(self, monkeypatch, tmp_path):
        """Verify actual log output reaches the file."""
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        configure_debug_logging(component="test", subdirectory="hooks")

        child = logging.getLogger("forge.cli.hooks.commands")
        child.debug("test message from child logger")

        # Flush handler
        forge_logger = logging.getLogger("forge")
        for h in forge_logger.handlers:
            h.flush()

        log_dir = tmp_path / "forge_home" / "logs" / "hooks"
        log_files = list(log_dir.glob("test.*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text()
        assert "test message from child logger" in content

    def test_info_level_filters_debug(self, monkeypatch, tmp_path):
        """log_level=info should write INFO but not DEBUG messages."""
        config_path = tmp_path / "config.yaml"
        config_path.write_text('log_level: "info"\n')
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)

        configure_debug_logging(component="test", subdirectory="hooks")

        forge_logger = logging.getLogger("forge")
        assert forge_logger.level == logging.INFO

        child = logging.getLogger("forge.test.level")
        child.debug("should-not-appear")
        child.info("should-appear")

        for h in forge_logger.handlers:
            h.flush()

        log_dir = tmp_path / "forge_home" / "logs" / "hooks"
        log_files = list(log_dir.glob("test.*.log"))
        assert len(log_files) == 1
        content = log_files[0].read_text()
        assert "should-not-appear" not in content
        assert "should-appear" in content


class TestConfigureConsoleLogging:
    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        forge_logger = logging.getLogger("forge")
        before = len(forge_logger.handlers)
        configure_console_logging()
        assert len(forge_logger.handlers) == before

    def test_attaches_stderr_handler(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        forge_logger = logging.getLogger("forge")
        initial = len(forge_logger.handlers)

        configure_console_logging()

        assert len(forge_logger.handlers) == initial + 1
        handler = forge_logger.handlers[-1]
        assert isinstance(handler, logging.StreamHandler)
        assert not isinstance(handler, logging.FileHandler)

    def test_idempotent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_DEBUG", "1")
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        forge_logger = logging.getLogger("forge")
        initial = len(forge_logger.handlers)

        configure_console_logging()
        configure_console_logging()

        assert len(forge_logger.handlers) == initial + 1

    def test_respects_log_level(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text('log_level: "info"\n')
        monkeypatch.delenv("FORGE_DEBUG", raising=False)
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))

        from forge import runtime_config

        monkeypatch.setattr(runtime_config, "_config", None)
        monkeypatch.setattr(runtime_config, "get_config_path", lambda: config_path)

        configure_console_logging()

        forge_logger = logging.getLogger("forge")
        handler = forge_logger.handlers[-1]
        assert handler.level == logging.INFO


class TestFindLatestLog:
    def test_returns_none_when_dir_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
        assert find_latest_log("proxy", "proxy.*.log") is None

    def test_returns_none_when_no_matches(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
        logs_dir = tmp_path / "forge_home" / "logs" / "proxy"
        logs_dir.mkdir(parents=True)
        assert find_latest_log("proxy", "proxy.*.log") is None

    def test_returns_most_recent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "forge_home"))
        logs_dir = tmp_path / "forge_home" / "logs" / "proxy"
        logs_dir.mkdir(parents=True)

        import time

        old = logs_dir / "proxy.100.log"
        old.write_text("old")
        time.sleep(0.05)
        new = logs_dir / "proxy.200.log"
        new.write_text("new")

        result = find_latest_log("proxy", "proxy.*.log")
        assert result is not None
        assert result.name == "proxy.200.log"
