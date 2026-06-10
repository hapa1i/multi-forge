"""Tests for the native-Codex auth/runtime preflight (Phase 5a).

Hermetic: the subprocess/filesystem probe seams on ``codex_preflight`` are
monkeypatched, so no real ``codex`` runs and nothing is spawned. Each case encodes
a Stage-A empirical finding (string-boolean details, doctor-parsed-on-nonzero-exit,
overallStatus-never-gates-ready, hook-seam-never-active) as a regression guard.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

import forge.core.runtime.codex_preflight as cp
from forge.config.loader import get_proxy_file_path
from forge.core.runtime import (
    CodexPreflight,
    CodexPreflightError,
    assert_codex_ready,
    codex_api_key_for_subprocess,
    preflight_codex,
)


@pytest.fixture(autouse=True)
def _clean_codex_env(monkeypatch) -> None:
    """Default state: no Forge/Codex env tokens and no inherited CODEX_HOME.

    Tests that want an env token or a managed-config dir set them explicitly.
    """
    monkeypatch.delenv("CODEX_API_KEY", raising=False)
    monkeypatch.delenv("CODEX_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)


def _stub_probes(
    monkeypatch,
    *,
    installed: bool = True,
    version: str | None = "0.137.0",
    doctor: dict | None = None,
    features: bool | None = True,
    managed: bool = False,
    stub_managed: bool = True,
) -> None:
    """Drive ``preflight_codex`` hermetically by replacing its probe seams."""
    monkeypatch.setattr(cp, "_codex_installed", lambda _runtime: installed)
    monkeypatch.setattr(cp, "_detect_version", lambda _runtime: version)
    monkeypatch.setattr(cp, "_probe_doctor_json", lambda _runtime: doctor)
    monkeypatch.setattr(cp, "_probe_features_hooks_enabled", lambda _runtime: features)
    if stub_managed:
        monkeypatch.setattr(cp, "_read_managed_only", lambda: managed)


def _doctor(
    *,
    api_key: str = "false",
    chatgpt: str = "false",
    agent: str = "false",
    overall: str = "ok",
    extra_details: dict | None = None,
) -> dict:
    """A ``codex doctor --json`` report with string-boolean auth details (Stage-A shape)."""
    details = {
        "stored API key": api_key,
        "stored ChatGPT tokens": chatgpt,
        "stored agent identity": agent,
        "stored auth mode": "chatgpt",
    }
    if extra_details:
        details.update(extra_details)
    return {
        "schemaVersion": 1,
        "overallStatus": overall,
        "checks": {"auth.credentials": {"status": "ok", "details": details}},
    }


def _write_proxy_yaml(proxy_id: str, wire_shape: str) -> None:
    """Write a minimal valid proxy.yaml under the isolated FORGE_HOME (real loader path)."""
    path = get_proxy_file_path(proxy_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "proxy_format: 1\n"
        "provider: litellm\n"
        "proxy_endpoint: http://localhost:8085\n"
        "port: 8085\n"
        "upstream_base_url: https://example.test\n"
        "tiers:\n"
        "  sonnet: some-model\n"
        f"wire_shape: {wire_shape}\n"
    )


class TestFailClosed:
    def test_no_credential_fails_closed_naming_all_paths(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor())  # all stored-auth booleans "false"

        with pytest.raises(CodexPreflightError) as exc_info:
            assert_codex_ready()

        result = exc_info.value.result
        assert result.ready is False
        assert result.auth_method == "none"
        assert result.auth_source == "none"
        assert result.billing_mode == "unknown"
        # The blocking guidance names all three setup paths + the forge command.
        msg = str(exc_info.value)
        assert "CODEX_API_KEY" in msg
        assert "codex login --device-auth" in msg
        assert "CODEX_ACCESS_TOKEN" in msg
        assert "forge auth login -c codex-api" in msg

    def test_installed_is_a_precondition_of_ready(self, monkeypatch) -> None:
        # A resolved env key on a machine with no codex binary is still NOT ready.
        _stub_probes(monkeypatch, installed=False)
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-xyz")

        result = preflight_codex()

        assert result.installed is False
        assert result.ready is False
        assert result.blocking_reason is not None
        assert "not installed" in result.blocking_reason
        # The key resolved, but install is the controlling blocker.
        assert result.auth_method == "api_key"


class TestAuthResolution:
    def test_env_api_key_is_api_billed(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"))  # doctor present but env wins
        monkeypatch.setenv("CODEX_API_KEY", "sk-codex-xyz")

        result = preflight_codex()

        assert result.auth_method == "api_key"
        assert result.auth_source == "env"
        assert result.billing_mode == "api"
        assert result.ready is True

    def test_doctor_authoritative_when_env_absent(self, monkeypatch) -> None:
        # Proves env-only resolution would WRONGLY fail-closed on a ChatGPT machine.
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"))

        result = preflight_codex()

        assert result.ready is True
        assert result.auth_method == "chatgpt_tokens"
        assert result.auth_source == "codex_store"
        assert result.billing_mode == "subscription_quota"

    def test_access_token_env_is_enterprise_unknown(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor())
        monkeypatch.setenv("CODEX_ACCESS_TOKEN", "tok-enterprise")

        result = preflight_codex()

        assert result.auth_method == "enterprise_token"
        assert result.auth_source == "env"
        assert result.billing_mode == "unknown"  # opaque token pool is unprovable
        assert result.ready is True

    def test_doctor_agent_identity_is_enterprise_unknown(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor(agent="true"))

        result = preflight_codex()

        assert result.auth_method == "enterprise_token"
        assert result.auth_source == "codex_store"
        assert result.billing_mode == "unknown"

    def test_string_boolean_false_is_not_truthy_misread(self, monkeypatch) -> None:
        # Regression: details are JSON STRINGS; "false" is truthy in Python. A plain
        # truthiness read would treat "false" as "present" -- assert it does not.
        _stub_probes(monkeypatch, doctor=_doctor(api_key="false", chatgpt="false", agent="false"))

        result = preflight_codex()

        assert result.auth_method == "none"  # nothing stored, despite truthy "false" strings
        assert result.ready is False

    def test_env_api_key_precedence_over_doctor_apikey(self, monkeypatch) -> None:
        # Both present -> env source wins (first match).
        _stub_probes(monkeypatch, doctor=_doctor(api_key="true"))
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")

        result = preflight_codex()

        assert result.auth_method == "api_key"
        assert result.auth_source == "env"

    def test_doctor_stored_api_key_is_api_billed(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor(api_key="true"))

        result = preflight_codex()

        assert result.auth_method == "api_key"
        assert result.auth_source == "codex_store"
        assert result.billing_mode == "api"


class TestProbeDoctorJson:
    """The doctor probe parses stdout JSON regardless of exit code (Stage-A: exit 1 with
    a valid report is normal on a reachability hiccup)."""

    def _patch_subprocess(self, monkeypatch, *, returncode: int, stdout: str) -> None:
        monkeypatch.setattr(cp.shutil, "which", lambda _name: "/opt/homebrew/bin/codex")
        monkeypatch.setattr(
            cp.subprocess,
            "run",
            lambda *_a, **_k: MagicMock(returncode=returncode, stdout=stdout, stderr=""),
        )

    def test_parses_valid_json_on_nonzero_exit(self, monkeypatch) -> None:
        report = json.dumps(_doctor(chatgpt="true", overall="warning"))
        self._patch_subprocess(monkeypatch, returncode=1, stdout=report)

        data = cp._probe_doctor_json(cp.get_runtime("codex"))

        assert data is not None
        assert data["checks"]["auth.credentials"]["details"]["stored ChatGPT tokens"] == "true"

    def test_empty_stdout_returns_none(self, monkeypatch) -> None:
        self._patch_subprocess(monkeypatch, returncode=1, stdout="")
        assert cp._probe_doctor_json(cp.get_runtime("codex")) is None

    def test_non_json_stdout_returns_none(self, monkeypatch) -> None:
        self._patch_subprocess(monkeypatch, returncode=0, stdout="not json at all")
        assert cp._probe_doctor_json(cp.get_runtime("codex")) is None

    def test_non_object_json_returns_none(self, monkeypatch) -> None:
        self._patch_subprocess(monkeypatch, returncode=0, stdout="[1, 2, 3]")
        assert cp._probe_doctor_json(cp.get_runtime("codex")) is None

    def test_returns_none_when_not_on_path(self, monkeypatch) -> None:
        monkeypatch.setattr(cp.shutil, "which", lambda _name: None)
        assert cp._probe_doctor_json(cp.get_runtime("codex")) is None


class TestDoctorStatusDoesNotGateReady:
    def test_overall_warning_with_resolved_auth_is_ready(self, monkeypatch) -> None:
        # The live machine's exact shape: overallStatus warning (unrelated DB parity)
        # while auth is fine. ready must be True; doctor_status captured, not gating.
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true", overall="warning"))

        result = preflight_codex()

        assert result.ready is True
        assert result.doctor_status == "warning"

    def test_stored_auth_is_presence_based_ignoring_auth_check_status(self, monkeypatch) -> None:
        # Decision (5a): readiness is PRESENCE-based. A non-"ok" `auth.credentials.status`
        # with stored tokens present still resolves + ready -- gating on that status would
        # risk the same false-fail-closed trap as overallStatus (validity is proven at 5b).
        doctor = _doctor(chatgpt="true")
        doctor["checks"]["auth.credentials"]["status"] = "warning"
        _stub_probes(monkeypatch, doctor=doctor)

        result = preflight_codex()

        assert result.auth_method == "chatgpt_tokens"
        assert result.ready is True


class TestCredentialStoreHydration:
    def test_credential_file_key_is_ready_and_not_leaked(self, monkeypatch) -> None:
        secret = "sk-codex-from-file"
        # Simulate a key present only in the Forge credential file (not env).
        monkeypatch.setattr(cp, "resolve_env_or_credential_with_source", lambda _var: (secret, "credential_file"))
        monkeypatch.setattr(cp, "resolve_env_or_credential", lambda _var: secret)
        _stub_probes(monkeypatch)

        result = preflight_codex()

        assert result.auth_source == "credential_file"
        assert result.ready is True
        # 5b must be able to read the value for child-env injection...
        assert codex_api_key_for_subprocess() == secret
        # ...but it must NEVER live on the result (would leak via asdict()/--json).
        assert secret not in json.dumps(asdict(result))
        assert not hasattr(result, "api_key")


class TestManagedSuppression:
    # Monkeypatch `_managed_requirements_paths` to tmp-only paths so a host
    # `/etc/codex/requirements.toml` can never leak into these results (fully hermetic).
    def test_explicit_requirements_file_surfaces_managed_suppressed(self, monkeypatch, tmp_path) -> None:
        req = tmp_path / "requirements.toml"
        req.write_text("allow_managed_hooks_only = true\n")
        monkeypatch.setattr(cp, "_managed_requirements_paths", lambda: [req])
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"), stub_managed=False)

        result = preflight_codex()

        assert result.hook_seam == "managed_suppressed"
        assert result.ready is True  # a capability limit, NOT a ready blocker

    def test_nested_table_flag_surfaces_managed_suppressed(self, monkeypatch, tmp_path) -> None:
        # End-to-end coverage of the one-table-deep parser branch through real tomllib
        # (the nested placement is a defensive assumption -- no Stage-A file confirmed it).
        req = tmp_path / "requirements.toml"
        req.write_text("[hooks]\nallow_managed_hooks_only = true\n")
        monkeypatch.setattr(cp, "_managed_requirements_paths", lambda: [req])
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"), stub_managed=False)

        assert preflight_codex().hook_seam == "managed_suppressed"

    def test_no_requirements_file_does_not_infer_suppression(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setattr(cp, "_managed_requirements_paths", lambda: [tmp_path / "requirements.toml"])
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"), stub_managed=False)

        result = preflight_codex()

        assert result.hook_seam != "managed_suppressed"  # absence is not proof of "not suppressed"
        assert result.hook_seam == "enrollment_gated"  # enabled + version-OK normal case (enrollment unchecked)


class TestTomlFlagTrue:
    def test_top_level_true(self) -> None:
        assert cp._toml_flag_true({"allow_managed_hooks_only": True}, "allow_managed_hooks_only") is True

    def test_nested_one_table_deep_true(self) -> None:
        assert cp._toml_flag_true({"hooks": {"allow_managed_hooks_only": True}}, "allow_managed_hooks_only") is True

    def test_absent_is_false(self) -> None:
        assert cp._toml_flag_true({"hooks": {"other": 1}}, "allow_managed_hooks_only") is False

    def test_string_true_is_not_boolean_true(self) -> None:
        # tomllib parses TOML `true` to Python True; a string "true" must NOT count.
        assert cp._toml_flag_true({"allow_managed_hooks_only": "true"}, "allow_managed_hooks_only") is False


class TestHookSeamNeverActive:
    def test_features_hooks_false_is_disabled(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, features=False, doctor=_doctor(chatgpt="true"))
        assert preflight_codex().hook_seam == "disabled"

    def test_known_old_version_is_disabled(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, version="0.130.0", features=True, doctor=_doctor(chatgpt="true"))
        assert preflight_codex().hook_seam == "disabled"

    def test_unparseable_version_is_unknown_not_disabled(self, monkeypatch) -> None:
        # Installed but version unparseable -> we cannot prove hooks are off -> unknown.
        _stub_probes(monkeypatch, version=None, features=True, doctor=_doctor(chatgpt="true"))
        assert preflight_codex().hook_seam == "unknown"

    def test_enabled_is_enrollment_gated_never_active(self, monkeypatch) -> None:
        # Enabled + version-OK: the normal case is "enrollment_gated" -- hooks can fire,
        # but enrollment state is unchecked BY DECISION (codex_frontend Phase 1: the
        # trusted_hash is not black-box computable and a path-keyed [hooks.state] read
        # false-negatives in worktrees, so no per-hook read exists). Even a (fabricated)
        # doctor trust hint never yields "active" here.
        doctor = _doctor(chatgpt="true", extra_details={"project trusted": "true"})
        _stub_probes(monkeypatch, features=True, doctor=doctor)

        seam = preflight_codex().hook_seam

        assert seam == "enrollment_gated"
        assert seam != "active"


class TestResponsesPosture:
    def test_no_proxy_is_native_direct(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"))

        result = preflight_codex(proxy_id=None)

        assert result.proxy_responses == "native_direct"
        assert result.ready is True  # native path is not a blocker

    def test_translated_proxy_is_unsupported_and_blocks(self, monkeypatch) -> None:
        _write_proxy_yaml("codex-openai", wire_shape="openai_translated")
        _stub_probes(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")  # auth clean so blocking is the proxy

        result = preflight_codex(proxy_id="codex-openai")

        assert result.proxy_responses == "proxy_unsupported"
        assert result.ready is False
        assert result.blocking_reason is not None
        assert "openai_translated" in result.blocking_reason

    def test_passthrough_proxy_is_also_unsupported(self, monkeypatch) -> None:
        _write_proxy_yaml("codex-passthrough", wire_shape="anthropic_passthrough")
        _stub_probes(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")

        result = preflight_codex(proxy_id="codex-passthrough")

        assert result.proxy_responses == "proxy_unsupported"
        assert result.ready is False
        assert "anthropic_passthrough" in (result.blocking_reason or "")

    def test_unknown_proxy_id_reports_not_found(self, monkeypatch) -> None:
        _stub_probes(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")

        result = preflight_codex(proxy_id="no-such-proxy")

        assert result.proxy_responses == "proxy_unsupported"
        assert result.ready is False
        assert "not found" in (result.blocking_reason or "")

    def test_invalid_proxy_id_does_not_raise(self, monkeypatch) -> None:
        # A path-traversal id makes the loader raise ValueError; the preflight must stay
        # fail-closed (proxy_unsupported), not propagate a traceback.
        _stub_probes(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")

        result = preflight_codex(proxy_id="../evil")

        assert result.proxy_responses == "proxy_unsupported"
        assert result.ready is False
        assert "invalid or unreadable" in (result.blocking_reason or "")

    def test_corrupt_proxy_yaml_does_not_raise(self, monkeypatch) -> None:
        # A proxy.yaml that parses but is not a mapping makes the loader raise ValueError.
        path = get_proxy_file_path("codex-corrupt")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("- just\n- a\n- list\n")
        _stub_probes(monkeypatch)
        monkeypatch.setenv("CODEX_API_KEY", "sk-env")

        result = preflight_codex(proxy_id="codex-corrupt")

        assert result.proxy_responses == "proxy_unsupported"
        assert result.ready is False
        assert "invalid or unreadable" in (result.blocking_reason or "")


class TestVersionFlag:
    def test_below_floor_is_not_ok(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, version="0.130.0", doctor=_doctor(chatgpt="true"))
        assert preflight_codex().version_ok is False

    def test_at_or_above_floor_is_ok(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, version="0.137.0", doctor=_doctor(chatgpt="true"))
        assert preflight_codex().version_ok is True

    def test_unparseable_version_is_not_ok(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, version=None, doctor=_doctor(chatgpt="true"))
        assert preflight_codex().version_ok is False

    def test_short_version_meets_padded_floor(self, monkeypatch) -> None:
        # "0.131" must meet the "0.131.0" floor (padding, not shorter-sorts-lower).
        _stub_probes(monkeypatch, version="0.131", doctor=_doctor(chatgpt="true"))
        assert preflight_codex().version_ok is True

    def test_version_meets_floor_pads_components(self) -> None:
        assert cp._version_meets_floor("0.131", "0.131.0") is True
        assert cp._version_meets_floor("0.131.0", "0.131") is True
        assert cp._version_meets_floor("0.130", "0.131.0") is False


class TestHappyPathAndAssert:
    def test_full_ready_result_shape(self, monkeypatch) -> None:
        # Mirrors the live machine: chatgpt auth, hooks enabled, no proxy.
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true", overall="warning"))

        result = preflight_codex()

        assert result == CodexPreflight(
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

    def test_assert_returns_result_when_ready(self, monkeypatch) -> None:
        _stub_probes(monkeypatch, doctor=_doctor(chatgpt="true"))
        result = assert_codex_ready()
        assert result.ready is True

    def test_run_doctor_false_skips_doctor_probe(self, monkeypatch) -> None:
        # With doctor skipped and no env token, a ChatGPT-only machine fails closed.
        sentinel = {"called": False}

        def _should_not_run(_runtime):
            sentinel["called"] = True
            return _doctor(chatgpt="true")

        monkeypatch.setattr(cp, "_codex_installed", lambda _runtime: True)
        monkeypatch.setattr(cp, "_detect_version", lambda _runtime: "0.137.0")
        monkeypatch.setattr(cp, "_probe_doctor_json", _should_not_run)
        monkeypatch.setattr(cp, "_probe_features_hooks_enabled", lambda _runtime: True)
        monkeypatch.setattr(cp, "_read_managed_only", lambda: False)

        result = preflight_codex(run_doctor=False)

        assert sentinel["called"] is False
        assert result.auth_method == "none"
        assert result.ready is False
