"""Adopt a pre-existing native Codex thread as a managed Forge session (command-core).

The Codex arm of `forge session adopt` (card Phase 2). UI-agnostic per design.md
section 3.12, and split plan/adopt for the same reason as the Claude arm: the
double-attach decision needs a point before anything is written.

Where the two arms differ is discovery. Claude names a transcript after the
conversation and files it under an encoding of the launch directory, so the path
*is* the lookup. Codex files rollouts under `$CODEX_HOME/sessions/YYYY/MM/DD/`
with the thread id only as a filename suffix, so the lookup is a glob that can
return more than one hit -- and the cwd lives inside the file rather than in its
path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from forge.core.runtime.codex_preflight import (
    CodexPreflight,
    CodexPreflightError,
    assert_codex_ready,
)
from forge.core.runtime.codex_rollouts import (
    find_rollouts_by_thread_id,
    parse_rollout_filename,
    rollout_head_cwd,
)
from forge.core.state import now_iso
from forge.install.project_compat import (
    ProjectCompatibilityError,
    enforce_project_compatibility,
)
from forge.session import SessionManager, UuidAlreadyBoundError
from forge.session.exceptions import SessionExistsError
from forge.session.models import AdoptionConfirmed, CodexConfirmed

from .context import ExecutionContext
from .session_adopt import (
    RECENT_ACTIVITY_WINDOW_S,
    AdoptError,
    normalize_conversation_id,
)
from .session_context import BindingLookupError, collect_bound_codex_threads

# Recorded in ``confirmed.codex.rollout_source``. Sits with its writing op, like
# ROLLOUT_SOURCE_DISCOVERED (codex_session.py) and ROLLOUT_SOURCE_POST_EXIT
# (codex_interactive.py).
ROLLOUT_SOURCE_ADOPTED = "adopted"

SOURCE_RUNTIME_CODEX = "codex"

CODEX_RUNTIME = "codex"


@dataclass(frozen=True)
class CodexAdoptPlan:
    """Read-only result of validating a Codex adoption request.

    Attributes:
        thread_id: The native Codex thread id.
        rollout_path: Absolute path to the matched rollout JSONL.
        recorded_cwd: The launch directory the rollout's head records.
        recently_active: Rollout mtime is within RECENT_ACTIVITY_WINDOW_S, so a
            native client may still be attached.
    """

    thread_id: str
    rollout_path: Path
    recorded_cwd: str
    recently_active: bool


@dataclass(frozen=True)
class CodexAdoptResult:
    """What adoption actually bound.

    ``rollout_path`` is re-resolved at write time, so it can differ from the plan's
    when codex rotated the file while the double-attach prompt blocked on a human.
    Callers report this one, not the plan's.
    """

    name: str
    thread_id: str
    rollout_path: Path


def find_adoptable_rollout(thread_id: str, cwd: Path) -> Path:
    """Return the one rollout for ``thread_id`` launched from ``cwd``.

    Deliberately does not use ``find_rollout_path``: its newest-mtime tie-break is
    fine for provenance on a session Forge already owns, but adoption *binds* to
    whatever it picks, so a wrong guess is a session pointed at someone else's
    conversation. Every failure mode is named instead.

    A rollout whose head cannot be read keeps the set ambiguous rather than being
    dropped -- the same policy ``find_rollouts_since`` applies, and for the same
    reason: the head shape is not pinned across codex versions, so an unreadable
    head is missing evidence, not evidence of a different directory. Silently
    preferring the one verifiable match would bind the wrong conversation exactly
    when Forge understands the files least.

    Raises:
        AdoptError: On no match, a cwd mismatch, or an ambiguous match in ``cwd``.
    """
    matches = [p for p in find_rollouts_by_thread_id(thread_id) if parse_rollout_filename(p) is not None]
    if not matches:
        raise AdoptError(
            f"no Codex rollout for thread '{thread_id}'. Adoption reads "
            "$CODEX_HOME/sessions/; check the id with 'codex resume --list'."
        )

    here = cwd.resolve()
    in_cwd: list[Path] = []
    unverifiable: list[Path] = []
    elsewhere: list[str] = []
    for path in matches:
        recorded = rollout_head_cwd(path)
        if recorded is None:
            unverifiable.append(path)
        elif Path(recorded).resolve() == here:
            in_cwd.append(path)
        else:
            elsewhere.append(recorded)

    if not in_cwd and not unverifiable:
        raise AdoptError(
            f"Codex thread '{thread_id}' was launched from {elsewhere[0]}, not {cwd}. "
            "Adopt from the recorded directory instead."
        )

    candidates = sorted(in_cwd + unverifiable)
    if len(candidates) > 1:
        listed = ", ".join(str(p) for p in candidates)
        raise AdoptError(
            f"Codex thread '{thread_id}' matches {len(candidates)} rollouts for {cwd}: {listed}. "
            "Refusing to guess which conversation to bind."
        )

    if not in_cwd:
        raise AdoptError(
            f"Codex thread '{thread_id}' has a rollout ({candidates[0]}), but it records no launch "
            f"directory, so it cannot be verified as belonging to {cwd}"
        )

    return in_cwd[0]


def plan_codex_adoption(ctx: ExecutionContext, thread_id: str) -> CodexAdoptPlan:
    """Validate a Codex adoption request without writing anything.

    Raises:
        AdoptError: On any failed precondition, including an unready Codex.
        UuidAlreadyBoundError: If the thread already belongs to a session.
    """
    thread_id = normalize_conversation_id(thread_id)

    if ctx.forge_root is None:
        raise AdoptError("not inside a Forge project")

    try:
        enforce_project_compatibility(ctx.forge_root)
    except ProjectCompatibilityError as e:
        raise AdoptError(str(e)) from e

    # Preflight before any state exists: adopting onto a machine that cannot run
    # Codex produces a session whose only possible next step fails.
    _assert_ready()

    rollout_path = find_adoptable_rollout(thread_id, Path(ctx.cwd))

    try:
        owner = collect_bound_codex_threads(str(ctx.forge_root)).get(thread_id)
    except BindingLookupError as e:
        raise AdoptError(str(e)) from e
    if owner is not None:
        raise UuidAlreadyBoundError(thread_id, owner)

    try:
        age_s = time.time() - rollout_path.stat().st_mtime
    except OSError:
        age_s = float("inf")

    recorded_cwd = rollout_head_cwd(rollout_path) or str(ctx.cwd)

    return CodexAdoptPlan(
        thread_id=thread_id,
        rollout_path=rollout_path,
        recorded_cwd=recorded_cwd,
        recently_active=age_s < RECENT_ACTIVITY_WINDOW_S,
    )


def adopt_codex_session(ctx: ExecutionContext, plan: CodexAdoptPlan, *, name: str) -> CodexAdoptResult:
    """Bind a Forge session to the planned Codex thread.

    No artifact copy, unlike the Claude arm: `confirmed.codex.rollout_path` points
    at the live rollout, which is how every other Codex session records it. Search
    indexing of Codex threads is not part of this arm.

    The whole binding is handed to ``start_session`` rather than written afterwards.
    The pre-check below runs under its own lock acquisition, so on its own it cannot
    stop two differently-named adopts of one thread from both passing; committing the
    thread id with the session makes the index write lock the arbiter, and leaves no
    window where an indexed Codex session exists with ``confirmed.codex = None``.

    Raises:
        AdoptError: If the plan no longer holds.
        UuidAlreadyBoundError: If another adopt bound this thread first.
    """
    if ctx.forge_root is None:
        raise AdoptError("not inside a Forge project")

    try:
        enforce_project_compatibility(ctx.forge_root)
    except ProjectCompatibilityError as e:
        raise AdoptError(str(e)) from e

    preflight = _assert_ready()

    # Re-derive rather than trust the plan: it may have been hand-built, and the
    # prompt between planning and here blocks on a human.
    if plan.thread_id != normalize_conversation_id(plan.thread_id):
        raise AdoptError(f"plan carries a non-canonical thread id: '{plan.thread_id}'")
    rollout_path = find_adoptable_rollout(plan.thread_id, Path(ctx.cwd))

    try:
        owner = collect_bound_codex_threads(str(ctx.forge_root)).get(plan.thread_id)
    except BindingLookupError as e:
        raise AdoptError(str(e)) from e
    if owner is not None:
        raise UuidAlreadyBoundError(plan.thread_id, owner)

    timestamp = now_iso()
    codex_confirmed = CodexConfirmed(
        thread_id=plan.thread_id,
        rollout_path=str(rollout_path),
        rollout_source=ROLLOUT_SOURCE_ADOPTED,
        auth_method=preflight.auth_method,
        auth_source=preflight.auth_source,
        billing_mode=preflight.billing_mode,
        # last_run_at stays None: adoption did not run a turn, and context_delivery
        # stays None because no transfer context was delivered.
    )

    try:
        state = SessionManager().start_session(
            name,
            worktree_path=str(ctx.cwd),
            direct=True,
            runtime=CODEX_RUNTIME,
            codex_confirmed=codex_confirmed,
            adoption=AdoptionConfirmed(
                source_runtime=SOURCE_RUNTIME_CODEX,
                adopted_at=timestamp,
                source_path=str(rollout_path),
                model_basis=None,
            ),
            confirmed_by="cli:adopt",
            require_uuid_unbound=True,
        )
    except SessionExistsError:
        # A same-thread adopt that got here first owns the derived name too, so the
        # name collision fires before the uniqueness check. Report the binding, which
        # is the contract, rather than a name clash the user did not choose.
        owner = collect_bound_codex_threads(str(ctx.forge_root)).get(plan.thread_id)
        if owner is not None:
            raise UuidAlreadyBoundError(plan.thread_id, owner) from None
        raise

    return CodexAdoptResult(name=state.name, thread_id=plan.thread_id, rollout_path=rollout_path)


def _assert_ready() -> CodexPreflight:
    try:
        return assert_codex_ready()
    except CodexPreflightError as e:
        raise AdoptError(f"Codex is not ready on this machine: {e}") from e
