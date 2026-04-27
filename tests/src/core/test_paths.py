"""Tests for forge.core.paths — display_path home-directory shortening."""

from __future__ import annotations

from pathlib import Path

from forge.core.paths import display_path


class TestDisplayPath:
    def test_replaces_home_prefix(self):
        home = str(Path.home())
        assert display_path(f"{home}/workspace/project") == "~/workspace/project"

    def test_exact_home_returns_tilde(self):
        assert display_path(str(Path.home())) == "~"

    def test_non_home_path_unchanged(self):
        assert display_path("/tmp/something") == "/tmp/something"

    def test_relative_path_unchanged(self):
        assert display_path("relative/path") == "relative/path"

    def test_accepts_path_object(self):
        home = Path.home()
        assert display_path(home / "workspace") == "~/workspace"

    def test_partial_match_not_shortened(self):
        home = str(Path.home())
        assert display_path(f"{home}extra/path") == f"{home}extra/path"

    def test_empty_string(self):
        assert display_path("") == ""
