"""Empirical Codex hook-enrollment verification (residual-risk slice).

The Codex trust ceremony (design.md section 3.9) is **unverifiable pre-turn**: the
``[hooks.state]`` ``trusted_hash`` is not black-box computable, so Forge can neither
perform nor validate enrollment from a config read. Enrollment can only be confirmed by
its *effect* -- an enrolled ``codex-session-start`` hook fires on a managed turn and
writes an observation receipt (the Phase 5 nothing-staged capture channel).

This op runs ONE trivial ``codex exec`` turn in a throwaway git repo, pointed at a
disposable managed session via ``FORGE_SESSION``/``FORGE_FORGE_ROOT``, and checks whether
the observation receipt appeared. Receipt present -> the hook fires (enrolled); absent
after a turn that ran -> not enrolled, with the candidate causes enumerated honestly.

**Scope**: this exercises **user-scope** registration (``$CODEX_HOME/config.toml``), the
path-stable scope where one ceremony covers every project (codex_frontend stage 84). A
*project*-scope hook is keyed to a specific project path, so it cannot be verified from a
throwaway repo -- that needs a turn inside the project itself (not built here).

Costs one real (cheap, read-only, trivial-prompt) ``codex exec`` turn -- opt-in only,
never on the readiness path.
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forge.core.runtime.codex_preflight import (
    CODEX_VERSION_VALIDATED,
    CodexPreflight,
    preflight_codex,
)

# The probe-turn machinery (invoker, bridge, session store) is imported lazily inside
# _run_probe_turn so importing this module stays cheap -- cli/runtime.py top-level imports
# CodexEnrollmentVerification for `forge runtime list`/`preflight`, which must not drag the
# invoker graph (this also lets that module avoid a TYPE_CHECKING workaround, banned here).

logger = logging.getLogger(__name__)

# A disposable session name for the probe turn. The receipt lands under a temp forge_root
# that is deleted with the run, so this never collides with a real session.
_PROBE_SESSION = "forge-enroll-probe"
_PROBE_PROMPT = "Reply with the single word OK. Make no file changes."


@dataclass(frozen=True)
class CodexEnrollmentVerification:
    """Result of an empirical enrollment check. Flat, JSON-safe, secret-free."""

    ready: bool  # preflight ready (a turn could even be attempted)
    registered: bool  # codex-session-start present in the user-scope codex config
    config_path: str  # the user-scope config inspected for registration
    attempted: bool  # a codex exec turn actually ran
    codex_succeeded: bool  # that turn returned success
    enrolled: bool | None  # True=receipt seen; False=ran, no receipt; None=could not attempt
    reason: str  # human summary / candidate causes
    version: str | None
    version_validated: str


def verify_codex_enrollment(
    *,
    preflight: CodexPreflight | None = None,
    timeout_seconds: int = 120,
) -> CodexEnrollmentVerification:
    """Confirm (or refute) that Forge's user-scope Codex hooks are trust-enrolled.

    Walks: preflight ready? -> ``codex-session-start`` registered (user scope)? -> run a
    trivial managed ``codex exec`` turn -> did the observation receipt appear? Each
    negative gate short-circuits with an actionable reason and spends NO turn when the
    answer is already knowable (not ready / not registered).

    Never raises: this is an opt-in diagnostic, so any unexpected failure (an unreadable
    config, a preflight error) degrades to an UNVERIFIED result instead of a traceback.
    """
    try:
        return _run_enrollment_checks(preflight=preflight, timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - diagnostic must never traceback (docstring contract)
        logger.debug("Codex enrollment verification failed unexpectedly", exc_info=True)
        return CodexEnrollmentVerification(
            ready=False,
            registered=False,
            config_path=_user_scope_config_path_safe(),
            attempted=False,
            codex_succeeded=False,
            enrolled=None,
            reason=(
                f"Enrollment verification could not complete ({type(exc).__name__}); "
                "see the hooks debug log (set FORGE_DEBUG=1)."
            ),
            version=None,
            version_validated=CODEX_VERSION_VALIDATED,
        )


def _run_enrollment_checks(
    *,
    preflight: CodexPreflight | None,
    timeout_seconds: int,
) -> CodexEnrollmentVerification:
    """Gate sequence behind :func:`verify_codex_enrollment` (may raise; the caller guards)."""
    pf = preflight or preflight_codex(run_doctor=True)

    config_path, registered = _read_user_scope_registration()

    if not pf.ready:
        return _result(
            pf,
            registered=registered,
            config_path=config_path,
            attempted=False,
            codex_succeeded=False,
            enrolled=None,
            reason=f"Codex is not ready, so enrollment cannot be verified: {pf.blocking_reason}",
        )

    if not registered:
        return _result(
            pf,
            registered=False,
            config_path=config_path,
            attempted=False,
            codex_succeeded=False,
            enrolled=None,
            reason=(
                f"'forge hook codex-session-start' is not registered at {config_path}. "
                "Run 'forge extension enable --scope user' first, then grant trust in 'codex'."
            ),
        )

    codex_succeeded, enrolled_seen = _run_probe_turn(pf, timeout_seconds=timeout_seconds)

    if enrolled_seen:
        reason = "codex-session-start fired: user-scope Codex hooks are trust-enrolled and active."
        enrolled: bool | None = True
    elif not codex_succeeded:
        # The turn never completed, so receipt-absence proves nothing about enrollment.
        enrolled = None
        reason = (
            "The verification 'codex exec' turn did not complete, so enrollment could not be "
            "confirmed. Re-run 'forge runtime preflight codex' and check codex auth/connectivity."
        )
    else:
        enrolled = False
        reason = _not_enrolled_reason(pf, config_path)

    return _result(
        pf,
        registered=True,
        config_path=config_path,
        attempted=True,
        codex_succeeded=codex_succeeded,
        enrolled=enrolled,
        reason=reason,
    )


def _read_user_scope_registration() -> tuple[str, bool]:
    """Return (config_path, codex-session-start registered UNDER SessionStart) for user scope.

    Event-aware on purpose: a Forge command registered under the WRONG event is not a
    working SessionStart hook and must not read as registered -- otherwise the probe
    burns a real ``codex exec`` turn and the advice misdiagnoses a wrong-event entry as
    "registered but not trust-enrolled". Uses logical ``codex_registration_keys``
    (event + command identity), NOT ``read_codex_registration``'s event-agnostic
    reporting set. Lazy install import (the ``core/ops/gc.py`` precedent) keeps a
    ``core -> install`` edge off load time.
    """
    from forge.install.codex_hooks import (
        codex_registration_key,
        codex_registration_keys,
        get_builtin_codex_entries,
        get_codex_config_path,
    )
    from forge.install.models import InstallScope

    session_start = next(e for e in get_builtin_codex_entries() if e.event == "SessionStart")
    config_path = get_codex_config_path(InstallScope.USER)
    keys = codex_registration_keys(config_path)
    return str(config_path), codex_registration_key(session_start.event, session_start.command) in keys


def _user_scope_config_path_safe() -> str:
    """Best-effort user-scope Codex config path for the never-raise fallback result."""
    try:
        from forge.install.codex_hooks import get_codex_config_path
        from forge.install.models import InstallScope

        return str(get_codex_config_path(InstallScope.USER))
    except Exception:  # noqa: BLE001 - the fallback path itself must not raise
        return "<unknown>"


def _run_probe_turn(preflight: CodexPreflight, *, timeout_seconds: int) -> tuple[bool, bool]:
    """Run one managed ``codex exec`` turn in a throwaway repo; return (succeeded, receipt_seen).

    The turn runs against the REAL ``$CODEX_HOME`` (that is where trust lives), but a
    temp git repo + temp forge_root so it pollutes no real session. ``_temporary_run_env``
    sets ``FORGE_SESSION``/``FORGE_FORGE_ROOT`` into the ambient env, which the codex child
    (and thus the ``codex-session-start`` hook) inherits -- the hook then resolves the
    disposable session store and writes its observation receipt there if it fires.
    """
    # Lazy (module-import stays cheap; see the import-block note above).
    from forge.core.invoker import CodexHeadlessInvoker, prepare_codex_request
    from forge.core.invoker.types import Attribution
    from forge.core.ops.codex_bridge import _temporary_run_env
    from forge.core.reactive.env import new_root_run_identity
    from forge.session.codex_handoff import (
        clear_observation_receipt,
        read_observation_receipt,
    )
    from forge.session.store import SessionStore

    with tempfile.TemporaryDirectory(prefix="forge-codex-enroll-") as tmp:
        repo = Path(tmp)
        if not _init_git_repo(repo):
            logger.debug("Codex enrollment probe: git init failed; cannot run codex exec")
            return False, False

        forge_root = repo  # the temp repo doubles as the disposable forge_root
        (forge_root / ".forge").mkdir(exist_ok=True)
        session_dir = SessionStore(str(forge_root), _PROBE_SESSION).session_dir
        clear_observation_receipt(session_dir)  # only read a receipt THIS turn wrote

        root = new_root_run_identity()
        with _temporary_run_env(root, _PROBE_SESSION, forge_root=str(forge_root)):
            request = prepare_codex_request(
                prompt=_PROBE_PROMPT,
                preflight=preflight,
                # session left untagged: a throwaway probe must not pollute `forge telemetry activity`.
                attribution=Attribution(command="codex-enroll-verify"),
                cwd=str(repo),
                sandbox="read-only",
                timeout_seconds=timeout_seconds,
                label="codex-enroll-verify",
            )
            result = CodexHeadlessInvoker().run(request)

        receipt = read_observation_receipt(session_dir)
        return result.success, receipt is not None


def _init_git_repo(path: Path) -> bool:
    """Init a minimal git repo (codex exec refuses to run outside one). Best-effort."""
    try:
        for argv in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "enroll-probe@forge.local"],
            ["git", "config", "user.name", "forge-enroll-probe"],
        ):
            subprocess.run(argv, cwd=path, check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("Codex enrollment probe: git init failed: %s", e)
        return False
    return True


def _not_enrolled_reason(preflight: CodexPreflight, config_path: str) -> str:
    """Sharpen the not-enrolled message using the preflight's hook-seam posture."""
    if preflight.hook_seam == "managed_suppressed":
        return (
            "codex-session-start did not fire and a managed-hooks policy is in effect "
            "(allow_managed_hooks_only). Managed/MDM policy can suppress user hooks regardless of trust."
        )
    if preflight.hook_seam == "disabled":
        return (
            "codex-session-start did not fire: the codex 'hooks' feature is disabled or the codex "
            "version is below the hook floor. Enable hooks / upgrade codex, then grant trust."
        )
    # Normal enrollment_gated case: registered + hooks enabled + a turn ran, but no receipt.
    tail = ""
    if preflight.version_beyond_validated:
        tail = (
            f" (codex {preflight.version} also runs ahead of the probe-validated "
            f"{preflight.version_validated}; re-run scripts/experiments/codex-hooks/ if this is unexpected)"
        )
    return (
        f"codex-session-start is registered at {config_path} but did not fire, so the hook is "
        "not trust-enrolled. Run 'codex' interactively in any project and grant trust ('trust all'), "
        f"then re-run this check.{tail}"
    )


def _result(
    pf: CodexPreflight,
    *,
    registered: bool,
    config_path: str,
    attempted: bool,
    codex_succeeded: bool,
    enrolled: bool | None,
    reason: str,
) -> CodexEnrollmentVerification:
    return CodexEnrollmentVerification(
        ready=pf.ready,
        registered=registered,
        config_path=config_path,
        attempted=attempted,
        codex_succeeded=codex_succeeded,
        enrolled=enrolled,
        reason=reason,
        version=pf.version,
        version_validated=pf.version_validated,
    )
