"""Tests for the `forge runtime` CLI (Phase 4e).

Hermetic: PATH presence and the Claude version probe are stubbed so no real
``claude/codex/gemini --version`` subprocess runs.
"""

from __future__ import annotations

import json
from dataclasses import fields, replace

import pytest
from click.testing import CliRunner

from forge.cli.runtime import runtime
from forge.core.runtime import CodexPreflight


@pytest.fixture(autouse=True)
def _no_real_probes(monkeypatch) -> None:
    """Make detection hermetic: nothing on PATH, Claude probe returns None."""
    monkeypatch.setattr("forge.core.runtime.registry.shutil.which", lambda _name: None)
    monkeypatch.setattr("forge.install.version.get_claude_runtime_version", lambda: None)


def test_list_renders_all_runtimes() -> None:
    result = CliRunner().invoke(runtime, ["list"])
    assert result.exit_code == 0
    for rid in ("claude_code", "codex", "gemini"):
        assert rid in result.output
    # Hooks render as the honest multi-state value: Codex hooks are enrollment_gated
    # (fire only once trust-enrolled), not a bare "yes".
    assert "enrollment_gated" in result.output
    # The note's bracketed token survives Rich markup (escape, not eaten as a tag).
    assert "[features]" in result.output


def test_list_json_carries_capability_fields() -> None:
    result = CliRunner().invoke(runtime, ["list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert {d["id"] for d in data} == {"claude_code", "codex", "gemini"}

    codex = next(d for d in data if d["id"] == "codex")
    assert (
        codex["pretool_policy"] == "partial"
    )  # Phase 1: deny + updatedInput confirmed; enrollment-gated + fails open -> not "full"
    # Hooks are enrollment_gated (fire only once trust-enrolled); the floor stays
    # machine-readable but is not a firing guarantee.
    assert codex["native_hooks"] == "enrollment_gated"
    assert codex["hook_min_version"] == "0.131.0"
    assert codex["hook_feature_flag"] is None  # no required hook flag; codex_hooks remains a deprecated alias
    assert codex["installed"] is False  # nothing on PATH (stubbed)
    assert codex["version"] is None
    assert "detect" not in codex  # the callable is dropped from JSON

    claude = next(d for d in data if d["id"] == "claude_code")
    assert claude["install_scopes"] == ["user", "project", "local"]


# ── forge runtime preflight (Phase 5a) ────────────────────────────

_READY = CodexPreflight(
    installed=True,
    version="0.137.0",
    version_ok=True,
    auth_method="chatgpt_tokens",
    auth_source="codex_store",
    billing_mode="subscription_quota",
    ready=True,
    blocking_reason=None,
    hook_seam="enrollment_gated",
    proxy_responses="native_direct",
    doctor_status="warning",
)

_NOT_READY = CodexPreflight(
    installed=True,
    version="0.137.0",
    version_ok=True,
    auth_method="chatgpt_tokens",
    auth_source="codex_store",
    billing_mode="subscription_quota",
    ready=False,
    blocking_reason="Responses-unsupported: omit --proxy to run native 'codex exec'.",
    hook_seam="enrollment_gated",
    proxy_responses="proxy_unsupported",
    doctor_status="warning",
)


class TestPreflightCmd:
    def test_renders_ready_and_exits_zero(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.cli.runtime.preflight_codex", lambda **_kw: _READY)
        result = CliRunner().invoke(runtime, ["preflight", "codex"])
        assert result.exit_code == 0
        assert "Ready" in result.output
        assert "chatgpt_tokens" in result.output
        assert "native_direct" in result.output

    def test_json_carries_fields_without_secret(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.cli.runtime.preflight_codex", lambda **_kw: _READY)
        result = CliRunner().invoke(runtime, ["preflight", "codex", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["auth_method"] == "chatgpt_tokens"
        assert data["ready"] is True
        # Structural no-secret guarantee: the JSON keys are exactly the dataclass fields,
        # and there is no key holding a resolved key value.
        assert set(data) == {f.name for f in fields(CodexPreflight)}
        assert "api_key" not in data

    def test_not_ready_exits_one_and_shows_reason(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.cli.runtime.preflight_codex", lambda **_kw: _NOT_READY)
        result = CliRunner().invoke(runtime, ["preflight", "codex"])
        assert result.exit_code == 1
        assert "NO" in result.output
        assert "proxy_unsupported" in result.output
        assert "Responses-unsupported" in result.output  # the blocking reason is rendered

    def test_unknown_runtime_is_bad_parameter(self) -> None:
        result = CliRunner().invoke(runtime, ["preflight", "gemini"])
        assert result.exit_code == 2
        assert "supported: codex" in result.output

    def test_within_validated_ceiling_shows_no_reprobe_note(self, monkeypatch) -> None:
        monkeypatch.setattr("forge.cli.runtime.preflight_codex", lambda **_kw: _READY)
        result = CliRunner().invoke(runtime, ["preflight", "codex"])
        assert result.exit_code == 0
        assert "re-run scripts/experiments/codex-hooks/" not in result.output

    def test_beyond_validated_ceiling_shows_reprobe_note(self, monkeypatch) -> None:
        beyond = replace(_READY, version="0.200.0", version_beyond_validated=True)
        monkeypatch.setattr("forge.cli.runtime.preflight_codex", lambda **_kw: beyond)
        result = CliRunner().invoke(runtime, ["preflight", "codex"])
        # Non-blocking advisory: still ready, exit 0, but the operator is told to re-probe.
        assert result.exit_code == 0
        assert "ahead of the probe-validated" in result.output
        assert "scripts/experiments/codex-hooks/" in result.output


class TestVerifyEnrollment:
    """`forge runtime preflight codex --verify-enrollment` dispatch + exit codes."""

    @staticmethod
    def _verification(**over):
        from forge.core.ops.codex_enrollment import CodexEnrollmentVerification

        base = dict(
            ready=True,
            registered=True,
            config_path="/home/u/.codex/config.toml",
            attempted=True,
            codex_succeeded=True,
            enrolled=True,
            reason="codex-session-start fired: user-scope Codex hooks are trust-enrolled and active.",
            version="0.139.0",
            version_validated="0.139.0",
        )
        base.update(over)
        return CodexEnrollmentVerification(**base)

    def test_enrolled_exits_zero(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "forge.core.ops.codex_enrollment.verify_codex_enrollment",
            lambda **_kw: self._verification(),
        )
        result = CliRunner().invoke(runtime, ["preflight", "codex", "--verify-enrollment"])
        assert result.exit_code == 0
        assert "ENROLLED" in result.output

    def test_not_enrolled_exits_one(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "forge.core.ops.codex_enrollment.verify_codex_enrollment",
            lambda **_kw: self._verification(enrolled=False, reason="not trust-enrolled; grant trust"),
        )
        result = CliRunner().invoke(runtime, ["preflight", "codex", "--verify-enrollment"])
        assert result.exit_code == 1
        assert "NOT ENROLLED" in result.output
        assert "grant trust" in result.output

    def test_unverified_exits_one(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "forge.core.ops.codex_enrollment.verify_codex_enrollment",
            lambda **_kw: self._verification(enrolled=None, attempted=False, reason="codex not ready"),
        )
        result = CliRunner().invoke(runtime, ["preflight", "codex", "--verify-enrollment"])
        assert result.exit_code == 1
        assert "UNVERIFIED" in result.output

    def test_json_carries_verification_fields(self, monkeypatch) -> None:
        from dataclasses import fields as dc_fields

        from forge.core.ops.codex_enrollment import CodexEnrollmentVerification

        monkeypatch.setattr(
            "forge.core.ops.codex_enrollment.verify_codex_enrollment",
            lambda **_kw: self._verification(),
        )
        result = CliRunner().invoke(runtime, ["preflight", "codex", "--verify-enrollment", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert set(data) == {f.name for f in dc_fields(CodexEnrollmentVerification)}
        assert data["enrolled"] is True

    def test_verify_enrollment_honors_proxy_preflight(self, monkeypatch) -> None:
        seen: dict[str, object] = {}
        proxy_ready = replace(
            _READY,
            proxy_responses="proxy_unsupported",
            ready=False,
            blocking_reason="bad proxy",
        )

        def fake_preflight(**kwargs):
            seen["preflight_kwargs"] = kwargs
            return proxy_ready

        def fake_verify(**kwargs):
            seen["verify_kwargs"] = kwargs
            return self._verification(enrolled=None, attempted=False, reason="bad proxy")

        monkeypatch.setattr("forge.cli.runtime.preflight_codex", fake_preflight)
        monkeypatch.setattr("forge.core.ops.codex_enrollment.verify_codex_enrollment", fake_verify)

        result = CliRunner().invoke(runtime, ["preflight", "codex", "--verify-enrollment", "--proxy", "local"])

        assert result.exit_code == 1
        assert seen["preflight_kwargs"] == {"proxy_id": "local"}
        assert seen["verify_kwargs"] == {"preflight": proxy_ready}
