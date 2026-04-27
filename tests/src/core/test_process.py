"""Tests for forge.core.process — PID and port utilities."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from forge.core.process import find_pid_by_port, is_pid_alive


class TestIsPidAlive:
    def test_current_process_is_alive(self) -> None:
        import os

        assert is_pid_alive(os.getpid()) is True

    def test_zero_pid_is_not_alive(self) -> None:
        assert is_pid_alive(0) is False

    def test_negative_pid_is_not_alive(self) -> None:
        assert is_pid_alive(-1) is False

    def test_nonexistent_pid_is_not_alive(self) -> None:
        # PID 99999999 is almost certainly not running
        assert is_pid_alive(99999999) is False


class TestFindPidByPort:
    def test_success_returns_pid(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="12345\n")
        with patch("forge.core.process.subprocess.run", return_value=mock_result):
            assert find_pid_by_port(8085) == 12345

    def test_multiple_pids_returns_first(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="12345\n67890\n")
        with patch("forge.core.process.subprocess.run", return_value=mock_result):
            assert find_pid_by_port(8085) == 12345

    def test_lsof_not_found_returns_none(self) -> None:
        with patch("forge.core.process.subprocess.run", side_effect=FileNotFoundError):
            assert find_pid_by_port(8085) is None

    def test_lsof_timeout_returns_none(self) -> None:
        with patch(
            "forge.core.process.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="lsof", timeout=5),
        ):
            assert find_pid_by_port(8085) is None

    def test_empty_output_returns_none(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
        with patch("forge.core.process.subprocess.run", return_value=mock_result):
            assert find_pid_by_port(8085) is None

    def test_nonzero_returncode_returns_none(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with patch("forge.core.process.subprocess.run", return_value=mock_result):
            assert find_pid_by_port(8085) is None

    def test_non_numeric_output_returns_none(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="not-a-pid\n")
        with patch("forge.core.process.subprocess.run", return_value=mock_result):
            assert find_pid_by_port(8085) is None

    def test_calls_lsof_with_correct_args(self) -> None:
        mock_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="")
        with patch("forge.core.process.subprocess.run", return_value=mock_result) as mock_run:
            find_pid_by_port(9090)
            mock_run.assert_called_once_with(
                ["lsof", "-ti", "TCP:9090", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=5,
            )
