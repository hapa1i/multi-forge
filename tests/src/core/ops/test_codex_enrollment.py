"""Tests for empirical Codex hook-enrollment verification (residual-risk slice).

Hermetic: no real ``codex`` runs. The verdict-logic tests stub the probe turn and the
registration read; the mechanism tests patch ``CodexHeadlessInvoker.run`` and simulate
the hook by writing the observation receipt into the session dir the op resolves from
``FORGE_FORGE_ROOT`` (exactly how the real ``codex-session-start`` hook finds it).
"""

from __future__ import annotations

import os

import pytest

import forge.core.ops.codex_enrollment as ce
from forge.core.invoker.types import HeadlessResult
from forge.core.ops.codex_enrollment import (
    CodexEnrollmentVerification,
    verify_codex_enrollment,
)
from forge.core.runtime.codex_preflight import CodexPreflight
from forge.session.codex_handoff import write_observation_receipt
from forge.session.store import SessionStore


def _preflight(*, ready: bool = True, hook_seam: str = "enrollment_gated", **over) -> CodexPreflight:
    base = dict(
        installed=True,
        version="0.139.0",
        version_ok=True,
        auth_method="chatgpt_tokens",
        auth_source="codex_store",
        billing_mode="subscription_quota",
        ready=ready,
        blocking_reason=None if ready else "codex not authenticated",
        hook_seam=hook_seam,
        proxy_responses="native_direct",
        doctor_status="ok",
    )
    base.update(over)
    return CodexPreflight(**base)  # type: ignore[arg-type]


def _fake_result(*, returncode: int = 0) -> HeadlessResult:
    return HeadlessResult(
        label="codex-enroll-verify",
        stdout="OK",
        stderr="",
        returncode=returncode,
        duration_seconds=0.1,
    )


class TestVerifyVerdictLogic:
    """The gate sequence, with the probe turn + registration read stubbed."""

    def test_not_ready_skips_turn(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        # If the turn were attempted this would raise; not-ready must short-circuit first.
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: pytest.fail("turn must not run"))

        res = verify_codex_enrollment(preflight=_preflight(ready=False))

        assert res.attempted is False
        assert res.enrolled is None
        assert "not ready" in res.reason

    def test_not_registered_skips_turn(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", False))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: pytest.fail("turn must not run"))

        res = verify_codex_enrollment(preflight=_preflight())

        assert res.registered is False
        assert res.attempted is False
        assert res.enrolled is None
        assert "forge extension enable --scope user" in res.reason

    def test_receipt_seen_is_enrolled(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: (True, True))

        res = verify_codex_enrollment(preflight=_preflight())

        assert res.enrolled is True
        assert res.attempted is True
        assert "enrolled and active" in res.reason

    def test_no_receipt_after_successful_turn_is_not_enrolled(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: (True, False))

        res = verify_codex_enrollment(preflight=_preflight(hook_seam="enrollment_gated"))

        assert res.enrolled is False
        assert "not trust-enrolled" in res.reason
        assert "grant trust" in res.reason

    def test_failed_turn_is_unverified_not_refuted(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: (False, False))

        res = verify_codex_enrollment(preflight=_preflight())

        # A turn that did not complete proves nothing about enrollment.
        assert res.enrolled is None
        assert "did not complete" in res.reason

    def test_managed_suppressed_sharpens_reason(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: (True, False))

        res = verify_codex_enrollment(preflight=_preflight(hook_seam="managed_suppressed"))

        assert res.enrolled is False
        assert "allow_managed_hooks_only" in res.reason

    def test_disabled_hooks_sharpens_reason(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: (True, False))

        res = verify_codex_enrollment(preflight=_preflight(hook_seam="disabled"))

        assert res.enrolled is False
        assert "feature is disabled" in res.reason

    def test_beyond_validated_appends_reprobe_hint(self, monkeypatch) -> None:
        monkeypatch.setattr(ce, "_read_user_scope_registration", lambda: ("/cfg.toml", True))
        monkeypatch.setattr(ce, "_run_probe_turn", lambda *a, **k: (True, False))

        res = verify_codex_enrollment(preflight=_preflight(version="0.200.0", version_beyond_validated=True))

        assert res.enrolled is False
        assert "runs ahead of the probe-validated" in res.reason


class TestRunProbeTurn:
    """The turn + receipt mechanism, patching only the codex subprocess."""

    def test_receipt_written_by_hook_is_detected(self, monkeypatch) -> None:
        # Simulate the real codex-session-start hook: it resolves the session store from
        # FORGE_FORGE_ROOT (set by _temporary_run_env during the call) and writes the
        # observation receipt there. The op must then read it back as "enrolled".
        def fake_run(self, request):  # noqa: ANN001
            forge_root = os.environ["FORGE_FORGE_ROOT"]
            session_dir = SessionStore(forge_root, ce._PROBE_SESSION).session_dir
            write_observation_receipt(session_dir, session_id="thread-xyz", transcript_path=None, source="startup")
            return _fake_result(returncode=0)

        # Patch the class at its source: _run_probe_turn imports it lazily (module stays
        # cheap for cli/runtime.py), so ce.CodexHeadlessInvoker is no longer a module attr.
        monkeypatch.setattr("forge.core.invoker.CodexHeadlessInvoker.run", fake_run)

        succeeded, seen = ce._run_probe_turn(_preflight(), timeout_seconds=30)

        assert succeeded is True
        assert seen is True

    def test_no_receipt_when_hook_does_not_fire(self, monkeypatch) -> None:
        # The turn runs but writes nothing (hook absent / not enrolled).
        monkeypatch.setattr(
            "forge.core.invoker.CodexHeadlessInvoker.run", lambda self, request: _fake_result(returncode=0)
        )

        succeeded, seen = ce._run_probe_turn(_preflight(), timeout_seconds=30)

        assert succeeded is True
        assert seen is False

    def test_failed_codex_turn_reports_not_succeeded(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "forge.core.invoker.CodexHeadlessInvoker.run", lambda self, request: _fake_result(returncode=1)
        )

        succeeded, seen = ce._run_probe_turn(_preflight(), timeout_seconds=30)

        assert succeeded is False
        assert seen is False

    def test_git_init_failure_degrades(self, monkeypatch) -> None:
        # No git / git init fails: cannot run a real codex turn -> (False, False), no raise.
        monkeypatch.setattr(ce, "_init_git_repo", lambda _path: False)
        monkeypatch.setattr(
            "forge.core.invoker.CodexHeadlessInvoker.run", lambda self, request: pytest.fail("must not run codex")
        )

        succeeded, seen = ce._run_probe_turn(_preflight(), timeout_seconds=30)

        assert succeeded is False
        assert seen is False


def test_result_is_json_safe_and_secret_free() -> None:
    """The dataclass carries no resolved key/token (it is rendered via --json)."""
    from dataclasses import asdict, fields

    res = CodexEnrollmentVerification(
        ready=True,
        registered=True,
        config_path="/cfg.toml",
        attempted=True,
        codex_succeeded=True,
        enrolled=True,
        reason="ok",
        version="0.139.0",
        version_validated="0.139.0",
    )
    data = asdict(res)
    assert set(data) == {f.name for f in fields(CodexEnrollmentVerification)}
    assert not any("key" in k or "token" in k for k in data)


class TestNeverRaises:
    """The public entry point degrades to UNVERIFIED on any unexpected error (docstring contract)."""

    def test_unexpected_error_in_checks_degrades_to_unverified(self, monkeypatch) -> None:
        def boom(**_kw):
            raise RuntimeError("config exploded")

        monkeypatch.setattr(ce, "_run_enrollment_checks", boom)

        res = verify_codex_enrollment(preflight=_preflight())

        assert res.enrolled is None
        assert res.attempted is False
        assert "could not complete" in res.reason
        # The fallback still fills the required dataclass fields (no partial/None crash).
        assert res.version_validated
        assert res.config_path
