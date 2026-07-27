"""Adopt a pre-existing native conversation as a managed Forge session (command-core).

UI-agnostic per design.md section 3.12: returns structured data, raises typed
exceptions, and never prints or imports click. The CLI leaf owns all rendering.

The operation splits in two because the double-attach policy needs a decision
point before anything is written:

- ``plan_adoption`` is read-only. It runs every precondition and reports whether
  the transcript looks recently active, so the caller can confirm first.
- ``adopt_session`` mutates. It re-validates through the plan, then writes.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from forge.core.models.direct_model import resolve_direct_model_pin
from forge.core.state import now_iso
from forge.core.workqueue import enqueue_index_marker
from forge.install.project_compat import (
    ProjectCompatibilityError,
    enforce_project_compatibility,
)
from forge.session import SessionManager, SessionStore, UuidAlreadyBoundError
from forge.session.artifacts import get_artifact_paths, safe_copy_file
from forge.session.claude.paths import get_transcript_path
from forge.session.index import IndexStore
from forge.session.models import AdoptionConfirmed
from forge.session.store import CLI_LOCK_TIMEOUT_S

from .context import ExecutionContext
from .session import ForgeOpError
from .session_context import scan_manifests_for_uuid

_log = logging.getLogger(__name__)


# Values recorded in ``confirmed.adoption.model_basis``. Constants live with the
# writing op, matching the ROLLOUT_SOURCE_* precedent in codex_session.py.
MODEL_BASIS_EXPLICIT = "explicit"
MODEL_BASIS_INFERRED = "inferred"
MODEL_BASIS_NONE = "none"

SOURCE_RUNTIME_CLAUDE = "claude_code"

# Matches the Stop hook's artifact vocabulary (cli/hooks/commands.py:550).
ADOPT_ARTIFACT_REASON = "adopt"

# Claude stamps this sentinel instead of a model id on synthetic assistant turns.
# Measured on 13 of 470 local transcripts; it is not a resolvable model.
SYNTHETIC_MODEL = "<synthetic>"

# Below this age a native client may still be attached. Forge cannot observe one
# (ActiveSessionStore only tracks Forge launches), so this drives a confirmation
# prompt rather than a refusal.
RECENT_ACTIVITY_WINDOW_S = 30 * 60

# Claude names transcripts `<uuid>.jsonl`, so the id is the only caller-controlled
# component of every path adoption touches. `Path(base) / "/etc/passwd"` silently
# discards `base`, which would point both the read and the artifact copy outside
# the project; anchoring the id to canonical UUID shape closes that before any
# path is built. Case-insensitive because Claude has emitted both casings.
_UUID_RE = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")


class AdoptError(ForgeOpError):
    """Raised when adoption cannot proceed."""


@dataclass(frozen=True)
class AdoptPlan:
    """Read-only result of validating an adoption request.

    Attributes:
        session_uuid: The native conversation UUID.
        transcript_path: Absolute path to the native JSONL.
        claude_project_root: CWD to record, which is also the encoding input for
            locating the transcript on a later resume.
        model: Resolved future-resume model pin, or None when no basis exists.
        model_basis: Which of MODEL_BASIS_* produced ``model``.
        recently_active: Transcript mtime is within RECENT_ACTIVITY_WINDOW_S, so
            a native client may still be attached.
    """

    session_uuid: str
    transcript_path: Path
    claude_project_root: str
    model: str | None
    model_basis: str
    recently_active: bool


@dataclass(frozen=True)
class AdoptResult:
    """What adoption actually wrote."""

    name: str
    session_uuid: str
    model: str | None
    model_basis: str
    artifact_rel: str
    indexed: bool


def normalize_conversation_id(session_uuid: str) -> str:
    """Return the id in canonical form, rejecting anything that is not a UUID.

    Must run before any path is constructed from the id. Case is preserved rather
    than folded: the id is a filename component, and lowercasing an
    upper-case-on-disk transcript would turn a valid adopt into a spurious
    "no transcript" on case-sensitive filesystems.

    Raises:
        AdoptError: If the id is empty or not canonical 8-4-4-4-12 UUID shape.
    """
    candidate = session_uuid.strip()
    if not candidate:
        raise AdoptError("a conversation id is required")
    if not _UUID_RE.match(candidate):
        raise AdoptError(
            f"'{session_uuid}' is not a conversation id. Expected a full UUID like "
            "470b1a1b-2c3d-4e5f-8a9b-0c1d2e3f4a5b, which is the transcript filename "
            "Claude records under ~/.claude/projects/."
        )
    return candidate


def read_transcript_cwd(transcript_path: Path) -> str | None:
    """Return the launch CWD a Claude transcript records, or None.

    Claude stamps ``cwd`` on every user/assistant/system entry. Reading the first
    one is the Claude analog of the Codex arm's ``_rollout_head_cwd``: it proves
    the transcript belongs to this directory rather than to a lossy-encoding
    sibling (``a.b``, ``a_b`` and ``a-b`` share one encoded directory).
    """
    try:
        with transcript_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict):
                    cwd = entry.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        return cwd
    except OSError as e:
        _log.debug("Could not read cwd from %s: %s", transcript_path, e)
    return None


def infer_transcript_model(transcript_path: Path) -> str | None:
    """Return the model to pin for future resumes, or None if none is inferable.

    Takes the **last** real assistant model. A single conversation can span two
    real models (measured on 2 of 470 local transcripts), and last-wins is the
    only deterministic reading of "what this conversation is running on now".
    Filters the ``<synthetic>`` sentinel, which is not a model id.
    """
    latest: str | None = None
    try:
        with transcript_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict) or entry.get("type") != "assistant":
                    continue
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue
                model = message.get("model")
                if isinstance(model, str) and model and model != SYNTHETIC_MODEL:
                    latest = model
    except OSError as e:
        _log.debug("Could not infer model from %s: %s", transcript_path, e)
    return latest


def plan_adoption(
    ctx: ExecutionContext,
    session_uuid: str,
    *,
    model_override: str | None = None,
) -> AdoptPlan:
    """Validate an adoption request without writing anything.

    Raises:
        AdoptError: On any failed precondition.
        UuidAlreadyBoundError: If the UUID already belongs to a session. Advisory
            only -- the authoritative check runs inside the index write lock, since
            this one releases its lock before adoption writes.
    """
    session_uuid = normalize_conversation_id(session_uuid)

    if ctx.forge_root is None:
        raise AdoptError("not inside a Forge project")

    try:
        enforce_project_compatibility(ctx.forge_root)
    except ProjectCompatibilityError as e:
        raise AdoptError(str(e)) from e

    # v1 treats the current directory as the native launch CWD (card step 2).
    claude_project_root = str(ctx.cwd)
    transcript_path = get_transcript_path(claude_project_root, session_uuid)

    _check_still_adoptable(session_uuid, transcript_path, claude_project_root)

    model, basis = _resolve_model_pin(transcript_path, model_override)

    try:
        age_s = time.time() - transcript_path.stat().st_mtime
    except OSError:
        age_s = float("inf")

    return AdoptPlan(
        session_uuid=session_uuid,
        transcript_path=transcript_path,
        claude_project_root=claude_project_root,
        model=model,
        model_basis=basis,
        recently_active=age_s < RECENT_ACTIVITY_WINDOW_S,
    )


def _check_still_adoptable(session_uuid: str, transcript_path: Path, claude_project_root: str) -> None:
    """Run every precondition that can change between planning and writing.

    Split out of ``plan_adoption`` so ``adopt_session`` can re-run it after the
    double-attach prompt. That prompt blocks on a human, so the transcript can be
    deleted, or another terminal can adopt the same UUID, while it waits.

    Raises:
        AdoptError: If the transcript is missing or belongs to another directory.
        UuidAlreadyBoundError: If the UUID already belongs to a session.
    """
    if not transcript_path.is_file():
        raise AdoptError(
            f"no transcript for conversation '{session_uuid}' under {claude_project_root}. "
            "Adopt from the directory the native session was launched from."
        )

    recorded_cwd = read_transcript_cwd(transcript_path)
    if recorded_cwd is None:
        raise AdoptError(
            f"transcript for '{session_uuid}' records no launch directory, so it cannot be verified as belonging "
            f"to {claude_project_root}"
        )
    if Path(recorded_cwd).resolve() != Path(claude_project_root).resolve():
        raise AdoptError(
            f"transcript for '{session_uuid}' was launched from {recorded_cwd}, not {claude_project_root}. "
            "Claude's project directories are lossy, so a sibling directory's transcript can appear here. "
            "Adopt from the recorded directory instead."
        )

    # Index first, then manifests (card step 1). The in-lock check inside
    # add_session is index-only, so a UUID recorded in a manifest but missing
    # from its index column would otherwise pass every gate and double-bind.
    owner = IndexStore().find_session_by_uuid(session_uuid)
    if owner is None:
        owner = scan_manifests_for_uuid(session_uuid)
    if owner is not None:
        raise UuidAlreadyBoundError(session_uuid, owner[0])


def _resolve_model_pin(transcript_path: Path, model_override: str | None) -> tuple[str | None, str]:
    """Return the (pin, basis) to persist, normalized the way `session start` does.

    Both branches must store ``DirectModelPin.env_model`` rather than the raw
    string. A pin the catalog cannot resolve is not inert: a later
    ``resume --proxy`` reaches ``_apply_direct_model_env_if_supported``
    (model_pin.py:61), which calls ``resolve_direct_model_pin`` unguarded and
    raises. Persisting an unresolvable value would permanently break resume.

    The two sources get opposite failure policies. An explicit ``--model`` is
    typed by the user, so an unknown value is their error to fix. An inferred
    model is best-effort evidence about a conversation that really ran, so an
    unknown id (a model newer than the catalog) drops to no pin instead of
    failing an otherwise valid adoption.
    """
    if model_override:
        try:
            return resolve_direct_model_pin(model_override).env_model, MODEL_BASIS_EXPLICIT
        except ValueError as e:
            raise AdoptError(str(e)) from e

    inferred = infer_transcript_model(transcript_path)
    if not inferred:
        # No basis means the field stays unset: persisting the current default
        # would change nothing on the direct path (it already falls back) while
        # silently pinning a later `resume --proxy`.
        return None, MODEL_BASIS_NONE

    try:
        return resolve_direct_model_pin(inferred).env_model, MODEL_BASIS_INFERRED
    except ValueError as e:
        _log.debug("Transcript model %r is not in the catalog, adopting without a pin: %s", inferred, e)
        return None, MODEL_BASIS_NONE


def adopt_session(ctx: ExecutionContext, plan: AdoptPlan, *, name: str) -> AdoptResult:
    """Bind a Forge session to the planned native conversation.

    Ordering is validate -> ``start_session`` -> artifact copy -> index marker.
    The manifest and index row cannot be separated: ``start_session`` writes them
    back-to-back inside one try block and self-rolls-back on failure there.

    Compensation for anything after ``start_session`` returns is this function's
    job -- that block is unreachable once it returns, so the two stages are
    disjoint in time and cannot both fire for one failure.

    Raises:
        AdoptError: If the copy fails (after unwinding).
        UuidAlreadyBoundError: If another adopt bound this UUID first.
    """
    if ctx.forge_root is None:
        raise AdoptError("not inside a Forge project")

    _check_still_adoptable(plan.session_uuid, plan.transcript_path, plan.claude_project_root)

    # worktree_path is passed explicitly rather than left to start_session's
    # `Path.cwd()` default (manager.py:542): the op must not depend on process
    # cwd. create_worktree stays False -- adoption binds an existing conversation
    # in place, and a True here would arm _rollback_worktree against a checkout
    # Forge did not create.
    state = SessionManager().start_session(
        name,
        worktree_path=str(ctx.cwd),
        direct=True,
        claude_session_id=plan.session_uuid,
        direct_model=plan.model,
        require_uuid_unbound=True,
    )

    store = SessionStore(str(ctx.forge_root), name)
    paths = get_artifact_paths(ctx.forge_root, name)
    dst_abs = paths.transcripts_abs / f"{plan.session_uuid}.jsonl"
    dst_rel = paths.transcripts_rel / f"{plan.session_uuid}.jsonl"

    try:
        safe_copy_file(plan.transcript_path, dst_abs, overwrite=True)

        def _mutate(m: object) -> None:
            from forge.session.models import SessionState

            if not isinstance(m, SessionState):
                raise TypeError(f"Expected SessionState, got {type(m)}")
            entries = m.confirmed.artifacts.setdefault("transcripts", [])
            if not isinstance(entries, list):
                entries = []
                m.confirmed.artifacts["transcripts"] = entries
            entries.append(
                {
                    "captured_at": now_iso(),
                    "reason": ADOPT_ARTIFACT_REASON,
                    "source_path": str(plan.transcript_path),
                    "session_id": plan.session_uuid,
                    "copied_path": str(dst_rel),
                    "copied": True,
                }
            )
            m.confirmed.claude_project_root = plan.claude_project_root
            m.confirmed.adoption = AdoptionConfirmed(
                source_runtime=SOURCE_RUNTIME_CLAUDE,
                adopted_at=now_iso(),
                source_path=str(plan.transcript_path),
                model_basis=plan.model_basis,
            )
            m.confirmed.confirmed_by = "cli:adopt"
            m.confirmed.confirmed_at = now_iso()

        store.update(timeout_s=CLI_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        _rollback_adoption(name, ctx=ctx, store=store, artifact_abs=dst_abs)
        raise AdoptError(f"could not capture the transcript for '{plan.session_uuid}': {e}") from e

    # Search indexing goes through the same deferred marker the Stop hook uses.
    # Memory is deliberately NOT enqueued: curation stays tied to a real Stop
    # handoff rather than running because adoption copied a file.
    marker = enqueue_index_marker(
        session_id=plan.session_uuid,
        worktree_path=ctx.forge_root,
        session_name=name,
        transcript_snapshot_rel=str(dst_rel),
        forge_root=str(ctx.forge_root),
    )

    return AdoptResult(
        name=name,
        session_uuid=plan.session_uuid,
        model=state.intent.launch.direct_model if state.intent.launch else plan.model,
        model_basis=plan.model_basis,
        artifact_rel=str(dst_rel),
        indexed=marker is not None,
    )


def _rollback_adoption(
    name: str,
    *,
    ctx: ExecutionContext,
    store: SessionStore,
    artifact_abs: Path,
) -> None:
    """Undo adoption's own writes, and only those.

    Deliberately does NOT call ``SessionManager.delete_session``: its default
    ``delete_transcripts=True`` reaches ``delete_session_data``, which unlinks
    ``get_transcript_path(...)`` and its agent logs under ``~/.claude/projects``.
    For an adopted session that path is the **user's** native conversation, so
    the convenient rollback would delete what they asked Forge to adopt.

    Takes no index marker: enqueueing happens after the guarded block, so a
    marker only ever exists on a path that already succeeded.

    Best-effort throughout: a failed unwind must not mask the original error.
    """
    try:
        artifact_abs.unlink(missing_ok=True)
    except OSError as e:
        _log.warning("Adopt rollback failed (artifact copy): %s", e)

    try:
        IndexStore().remove_session(name, forge_root=str(ctx.forge_root))
    except Exception as e:
        _log.warning("Adopt rollback failed (index entry): %s", e)

    try:
        # Removes .forge/sessions/<name>/ only -- not the artifact copy, which
        # lives under .forge/artifacts/<name>/ and is unlinked above.
        store.delete()
    except Exception as e:
        _log.warning("Adopt rollback failed (manifest): %s", e)
