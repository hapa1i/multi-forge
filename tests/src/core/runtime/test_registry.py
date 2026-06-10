"""Tests for the runtime registry capability matrix (Phase 4e).

The registry answers the seven capability questions from the runtime-abstraction
card (installed / interactive / headless / hooks / usage / native resume / scopes)
and encodes Codex/Gemini *limits* as values, never as parity-implying omissions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from forge.core.runtime import get_runtime, installed_runtimes, list_runtimes
from forge.core.runtime.registry import _probe_version


class TestRegistryShape:
    def test_three_known_runtimes_in_declaration_order(self) -> None:
        assert [s.id for s in list_runtimes()] == ["claude_code", "codex", "gemini"]

    def test_get_runtime_returns_spec(self) -> None:
        assert get_runtime("claude_code").display_name == "Claude Code"

    def test_get_runtime_unknown_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown runtime 'bogus'"):
            get_runtime("bogus")


class TestClaudeSpec:
    def test_capability_fields(self) -> None:
        s = get_runtime("claude_code")
        assert s.headless_cmd == ("claude", "-p")
        assert s.interactive == "default"
        assert s.headless is True
        assert s.native_hooks == "full"  # ungated -- hooks work after install
        assert s.hook_min_version is None and s.hook_feature_flag is None
        assert s.pretool_policy == "full"
        assert s.usage_source == "transcript_proxy"
        assert s.native_resume is True
        assert s.install_scopes == ("user", "project", "local")
        assert s.curated_transfer_in and s.curated_transfer_out

    def test_detect_reuses_installer_version_probe(self, monkeypatch) -> None:
        # detect() is the installer's probe (lazy import) -- patch the source module.
        monkeypatch.setattr("forge.install.version.get_claude_runtime_version", lambda: "2.1.99")
        assert get_runtime("claude_code").detect() == "2.1.99"


class TestCodexSpec:
    def test_limits_encoded_not_parity(self) -> None:
        s = get_runtime("codex")
        # Phase 1 probe (2026-06-10): post-enrollment PreToolUse deny + updatedInput
        # mutation confirmed headless -> "partial", not "full" -- enforcement exists only
        # in trust-enrolled homes, malformed hook output fails open, and PermissionRequest
        # is unpinned headless.
        assert s.pretool_policy == "partial"
        assert s.interactive == "beta"  # Forge frontend integration target (codex_frontend Phase 5)
        # Probes (2026-06-10): trust-enrolled hooks fire headless AND interactively ->
        # "enrollment_gated", not "gated": the version floor is satisfied yet untrusted hooks
        # do not fire -- the gate is trust enrollment, not the version. The floor stays
        # recorded (registration/enablement, not a firing guarantee); no hook flag required
        # (codex_hooks is a deprecated alias).
        assert s.native_hooks == "enrollment_gated"
        assert s.hook_min_version == "0.131.0"
        assert s.hook_feature_flag is None
        assert s.native_resume is True
        assert s.usage_source == "jsonl_events"
        assert s.headless_cmd == ("codex", "exec")
        assert s.install_scopes == ()  # Forge does not manage Codex install
        # Note records the default-on reality + the trust-enrollment finding.
        assert s.note is not None and "default-on" in s.note and "trust-enrolled" in s.note


class TestGeminiSpec:
    def test_limits(self) -> None:
        s = get_runtime("gemini")
        assert s.interactive == "none"
        assert s.native_hooks == "none"
        assert s.hook_min_version is None and s.hook_feature_flag is None
        assert s.pretool_policy == "none"
        assert s.native_resume is False  # capability-check first -> claim nothing
        assert s.usage_source == "json_stats"
        assert s.headless_cmd == ("gemini", "-p")
        assert s.install_scopes == ()


class TestIsInstalled:
    def test_reflects_path_presence(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "forge.core.runtime.registry.shutil.which",
            lambda name: "/usr/bin/claude" if name == "claude" else None,
        )
        assert get_runtime("claude_code").is_installed() is True
        assert get_runtime("codex").is_installed() is False

    def test_installed_runtimes_filters_by_path(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "forge.core.runtime.registry.shutil.which",
            lambda name: "/x" if name == "claude" else None,
        )
        assert [s.id for s in installed_runtimes()] == ["claude_code"]


class TestProbeVersion:
    def test_returns_none_when_not_on_path(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _n: None)
        assert _probe_version(("codex", "--version")) is None

    def test_parses_version_token(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _n: "/usr/bin/codex")
        monkeypatch.setattr(
            "forge.core.runtime.registry.subprocess.run",
            lambda *_a, **_k: MagicMock(returncode=0, stdout="codex-cli 0.124.3\n", stderr=""),
        )
        assert _probe_version(("codex", "--version")) == "0.124.3"

    def test_unparseable_output_returns_none(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _n: "/usr/bin/codex")
        monkeypatch.setattr(
            "forge.core.runtime.registry.subprocess.run",
            lambda *_a, **_k: MagicMock(returncode=0, stdout="no version here", stderr=""),
        )
        assert _probe_version(("codex", "--version")) is None

    def test_nonzero_exit_returns_none(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _n: "/usr/bin/codex")
        monkeypatch.setattr(
            "forge.core.runtime.registry.subprocess.run",
            lambda *_a, **_k: MagicMock(returncode=1, stdout="", stderr="boom"),
        )
        assert _probe_version(("codex", "--version")) is None

    def test_falls_back_to_stderr(self, monkeypatch) -> None:
        # Some CLIs print --version to stderr; the probe reads either stream.
        monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _n: "/usr/bin/gemini")
        monkeypatch.setattr(
            "forge.core.runtime.registry.subprocess.run",
            lambda *_a, **_k: MagicMock(returncode=0, stdout="", stderr="gemini 1.2.0\n"),
        )
        assert _probe_version(("gemini", "--version")) == "1.2.0"

    def test_finds_version_in_stderr_despite_stdout_banner(self, monkeypatch) -> None:
        # stdout has a non-version banner; the version is on stderr. Both streams are
        # searched, so it is still found (regression: stdout must not mask stderr).
        monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _n: "/usr/bin/codex")
        monkeypatch.setattr(
            "forge.core.runtime.registry.subprocess.run",
            lambda *_a, **_k: MagicMock(returncode=0, stdout="Codex CLI -- experimental\n", stderr="0.135.0\n"),
        )
        assert _probe_version(("codex", "--version")) == "0.135.0"
