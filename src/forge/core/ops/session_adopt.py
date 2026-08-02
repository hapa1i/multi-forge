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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forge.core.models.direct_model import resolve_direct_model_pin
from forge.core.paths import get_forge_home
from forge.core.runtime.codex_rollouts import find_rollouts_by_thread_id
from forge.core.state import now_iso
from forge.core.state.lock import FileLockTimeoutError, file_lock
from forge.core.workqueue import enqueue_index_marker
from forge.install.project_compat import (
    ProjectCompatibilityError,
    enforce_project_compatibility,
)
from forge.session import SessionManager, SessionStore, UuidAlreadyBoundError
from forge.session.artifacts import (
    ADOPT_ARTIFACT_REASON,
    get_artifact_paths,
    safe_copy_file,
)
from forge.session.claude.paths import get_project_encoded_dir, get_transcript_path
from forge.session.exceptions import SessionExistsError
from forge.session.index import IndexStore
from forge.session.models import AdoptionConfirmed
from forge.session.store import CLI_LOCK_TIMEOUT_S

from .context import ExecutionContext
from .session import ForgeOpError
from .session_context import BindingLookupError, collect_bound_uuids

_log = logging.getLogger(__name__)


# Values recorded in ``confirmed.adoption.model_basis``. Constants live with the
# writing op, matching the ROLLOUT_SOURCE_* precedent in codex_session.py.
MODEL_BASIS_EXPLICIT = "explicit"
MODEL_BASIS_INFERRED = "inferred"
MODEL_BASIS_NONE = "none"

SOURCE_RUNTIME_CLAUDE = "claude_code"

# The runtime label `intent.launch.runtime` uses for Codex sessions.
CODEX_RUNTIME = "codex"

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
# path is built. Accepts either casing so a pasted upper-case id gets a shape
# error only when it deserves one; normalize_conversation_id folds the result.
_UUID_RE = re.compile(r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")

# Claude wraps synthetic user entries in an XML-ish tag. Measured across 200 local
# transcripts: ~187 tagged against 608 plain human messages. None of them makes a
# useful preview, so the preview always skips them.
_SYNTHETIC_PREFIX_RE = re.compile(r"\A\s*<([a-z-]+)>")

# Of those wrappers, these carry machine output rather than anything the user did,
# so they are not turns either. The rest (`command-message`, `command-name`,
# `bash-input`) record a human action -- typing `/init` is a turn even though its
# text is generated -- and stay counted.
_MACHINE_OUTPUT_TAGS = frozenset({"local-command-caveat", "local-command-stdout", "bash-stdout", "task-notification"})

# Long enough to recognize a conversation, short enough for one terminal row.
PREVIEW_CHARS = 72


class AdoptError(ForgeOpError):
    """Raised when adoption cannot proceed."""


@contextmanager
def conversation_lock(conversation_id: str) -> Iterator[None]:
    """Serialize adoptions of one conversation, across processes and projects.

    The index write lock makes a *published* binding unique, but session creation
    writes the manifest first: a process killed between the two leaves an orphan
    manifest that already owns the conversation and never reached the index. A
    second adopt whose scan ran before that manifest appeared then publishes a
    duplicate binding, and the orphan scan can only refuse the *third* attempt --
    it cannot un-bind the two that already exist.

    Holding this around the final scan and the commit closes that window: the
    loser's scan cannot run until the winner's manifest exists, so it sees the
    orphan and refuses. ``flock`` releases on process death, so a killed adopt
    frees the lock rather than wedging every later one.

    Global (under ``FORGE_HOME``) rather than per-project, because a conversation
    is not project-scoped -- the same id can be adopted from any directory.

    ``conversation_id`` must already be canonical: this builds a path from it, and
    it is the only caller-supplied component of that path.

    Raises:
        AdoptError: If another adoption of this conversation holds the lock.
    """
    if _UUID_RE.match(conversation_id) is None:
        raise AdoptError(f"refusing to lock on a non-canonical conversation id: '{conversation_id}'")

    lock_path = get_forge_home() / "locks" / f"adopt-{conversation_id}.lock"
    try:
        with file_lock(lock_path=lock_path, timeout_s=CLI_LOCK_TIMEOUT_S):
            yield
    except FileLockTimeoutError as e:
        raise AdoptError(
            f"another adoption of conversation '{conversation_id}' is in progress. Wait for it to finish."
        ) from e


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
class TranscriptSummary:
    """Everything adoption reads out of a native transcript in one pass.

    Attributes:
        recorded_cwd: The launch directory Claude stamps on entries, or None.
        last_model: Last real assistant model; None when no assistant turn ran.
        user_turns: User entries the human caused, excluding tool results and
            machine-output wrappers. A slash command counts; its stdout does not.
        preview: First human message that is not a synthetic wrapper.
    """

    recorded_cwd: str | None
    last_model: str | None
    user_turns: int
    preview: str | None


@dataclass(frozen=True)
class AdoptCandidate:
    """An unbound native conversation that could be adopted from this directory.

    ``modified_at`` is ISO-8601 rather than an epoch float so the CLI can hand it
    to the shared relative-time formatter without the op picking a display shape.
    """

    session_uuid: str
    transcript_path: Path
    modified_at: str
    user_turns: int
    preview: str | None


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

    Must run before any path is constructed from the id, and before the id is
    compared against a stored ``claude_session_id``.

    Case is folded to lower. Claude writes lowercase transcript filenames (0 of
    470 local transcripts carry an upper-case hex digit), so lowercasing cannot
    misdirect the path lookup, while accepting mixed case verbatim would defeat
    the already-bound check: that comparison is a string equality, so ``AAAA...``
    and ``aaaa...`` would bind twice to one conversation -- and on a
    case-insensitive filesystem, which is the primary supported platform, both
    resolve to the same transcript.

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
    return candidate.lower()


def summarize_transcript(transcript_path: Path) -> TranscriptSummary:
    """Read a native transcript once and return everything adoption needs from it.

    One pass rather than a reader per field: planning needs the recorded cwd and
    the model, discovery needs the cwd, turn count and preview, and discovery
    reads every candidate in the directory.

    Unreadable or malformed content degrades to an empty summary rather than
    raising -- this is a system boundary (coding_standards section 5), and a
    truncated transcript should still be listable.
    """
    recorded_cwd: str | None = None
    last_model: str | None = None
    user_turns = 0
    preview: str | None = None

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
                if not isinstance(entry, dict):
                    continue

                if recorded_cwd is None:
                    cwd = entry.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        recorded_cwd = cwd

                entry_type = entry.get("type")
                message = entry.get("message")
                if not isinstance(message, dict):
                    continue

                if entry_type == "assistant":
                    model = message.get("model")
                    if isinstance(model, str) and model and model != SYNTHETIC_MODEL:
                        last_model = model
                    continue

                if entry_type != "user":
                    continue

                text = _user_message_text(message)
                if text is None:
                    continue

                wrapper = _SYNTHETIC_PREFIX_RE.match(text)
                if wrapper and wrapper.group(1) in _MACHINE_OUTPUT_TAGS:
                    continue

                user_turns += 1
                if preview is None and not wrapper:
                    preview = " ".join(text.split())
    except OSError as e:
        _log.debug("Could not read transcript %s: %s", transcript_path, e)

    return TranscriptSummary(
        recorded_cwd=recorded_cwd,
        last_model=last_model,
        user_turns=user_turns,
        preview=preview,
    )


def _user_message_text(message: dict[str, object]) -> str | None:
    """Return a user entry's human-authored text, or None if it is not one.

    Claude types tool results as ``user`` entries too -- 612 of 662 user entries
    across a 200-transcript sample -- so counting every ``user`` entry as a turn
    would report mostly machine traffic. Human turns carry either a plain string
    or a content list with a ``text`` block.
    """
    content = message.get("content")
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    return text
    return None


def detect_adoption_runtime(ctx: ExecutionContext, conversation_id: str) -> str:
    """Return which runtime owns this id: SOURCE_RUNTIME_CLAUDE or "codex".

    Decided by on-disk evidence, not by the shape of the id. Both runtimes name
    conversations with UUIDs, and while they currently differ by version (Claude
    v4, Codex v7 across 470 and 458 local files), that is an undocumented detail
    of two third-party tools -- and one local Claude transcript is already a v3.
    Routing on it would silently send an adopt to the wrong arm the first time
    either changed.

    Raises:
        AdoptError: If neither runtime has a matching conversation, or both do.
    """
    conversation_id = normalize_conversation_id(conversation_id)

    transcript = get_transcript_path(str(ctx.cwd), conversation_id)
    rollouts = find_rollouts_by_thread_id(conversation_id)
    has_claude = transcript.is_file()
    has_codex = bool(rollouts)

    if has_claude and has_codex:
        # Both paths are named: a dual match means something is wrong with the
        # files, so the user needs to see which two the refusal is about.
        listed = ", ".join(str(p) for p in sorted(rollouts))
        raise AdoptError(
            f"'{conversation_id}' matches both a Claude transcript ({transcript}) and a Codex rollout "
            f"({listed}). Refusing to guess which conversation to bind."
        )
    if has_claude:
        return SOURCE_RUNTIME_CLAUDE
    if has_codex:
        return CODEX_RUNTIME

    raise AdoptError(
        f"no conversation '{conversation_id}' found for this directory. Claude transcripts are "
        f"looked up under {get_project_encoded_dir(str(ctx.cwd))}, Codex threads under "
        "$CODEX_HOME/sessions/. Adopt from the directory the native session was launched from."
    )


def discover_adoptable(ctx: ExecutionContext) -> tuple[Path, list[AdoptCandidate]]:
    """List unbound native conversations launched from this exact directory.

    Returns ``(scanned_dir, candidates)`` newest-first. The directory is returned
    even when nothing matches, because "which directory did you look in" is the
    answer a user needs when the list is empty -- Claude's encoded directories
    are lossy, so the scanned path is not obvious from the cwd.

    Exact-CWD in v1, matching the adoption precondition: a candidate whose
    recorded cwd is another directory is a lossy-encoding sibling, not something
    adoptable here. CLI-only; hooks never scan a directory (design.md section 3.10).

    Raises:
        AdoptError: If not inside a Forge project.
    """
    if ctx.forge_root is None:
        raise AdoptError("not inside a Forge project")

    scanned_dir = get_project_encoded_dir(str(ctx.cwd))
    try:
        transcripts = sorted(scanned_dir.glob("*.jsonl"))
    except OSError as e:
        _log.debug("Could not scan %s: %s", scanned_dir, e)
        return scanned_dir, []

    # Collected once rather than per candidate: both lookups take the index lock,
    # and the manifest scan reads every session manifest.
    try:
        bound = collect_bound_uuids(str(ctx.forge_root))
    except BindingLookupError as e:
        raise AdoptError(str(e)) from e
    here = Path(ctx.cwd).resolve()

    found: list[tuple[float, AdoptCandidate]] = []
    for path in transcripts:
        # Skips `agent-<uuid>.jsonl` sidecar logs, which are not conversations.
        if not _UUID_RE.match(path.stem):
            continue
        session_uuid = path.stem.lower()
        if session_uuid in bound:
            continue

        summary = summarize_transcript(path)
        if summary.recorded_cwd is None or Path(summary.recorded_cwd).resolve() != here:
            continue

        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        preview = summary.preview
        if preview and len(preview) > PREVIEW_CHARS:
            preview = preview[: PREVIEW_CHARS - 1].rstrip() + "…"

        found.append(
            (
                mtime,
                AdoptCandidate(
                    session_uuid=session_uuid,
                    transcript_path=path,
                    modified_at=datetime.fromtimestamp(mtime, UTC).isoformat(),
                    user_turns=summary.user_turns,
                    preview=preview,
                ),
            )
        )

    found.sort(key=lambda pair: pair[0], reverse=True)
    return scanned_dir, [candidate for _, candidate in found]


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

    summary = _check_still_adoptable(session_uuid, transcript_path, claude_project_root, str(ctx.forge_root))

    model, basis = _resolve_model_pin(summary, model_override)

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


def _check_plan_invariants(ctx: ExecutionContext, plan: AdoptPlan) -> None:
    """Re-derive the plan's paths and reject one that does not match.

    ``AdoptPlan`` is an ordinary dataclass, so ``adopt_session`` cannot assume its
    fields came from ``plan_adoption``; a hand-built plan would otherwise reach the
    same read-and-copy that the unvalidated-id defect exploited. Internal boundary
    per coding_standards section 5: re-derive rather than trust.

    Raises:
        AdoptError: If the id, project root, or transcript path is not canonical.
    """
    if plan.session_uuid != normalize_conversation_id(plan.session_uuid):
        raise AdoptError(f"plan carries a non-canonical conversation id: '{plan.session_uuid}'")

    if Path(plan.claude_project_root).resolve() != Path(ctx.cwd).resolve():
        raise AdoptError(f"plan targets {plan.claude_project_root}, but this command is running in {ctx.cwd}")

    expected = get_transcript_path(plan.claude_project_root, plan.session_uuid)
    if plan.transcript_path.resolve() != expected.resolve():
        raise AdoptError(f"plan transcript path {plan.transcript_path} is not the canonical path for its conversation")


def _validate_adoption_artifact_destination(
    *,
    forge_root: Path,
    source: Path,
    destination: Path,
) -> None:
    """Reject artifact aliases and symlink escapes before copying user data."""

    artifact_root = forge_root.resolve() / ".forge" / "artifacts"
    try:
        canonical_artifact_root = artifact_root.resolve(strict=False)
        resolved_destination = destination.resolve(strict=False)
    except OSError as e:
        raise AdoptError(f"cannot safely resolve adoption artifact destination '{destination}': {e}") from e

    if not resolved_destination.is_relative_to(canonical_artifact_root):
        raise AdoptError(
            f"adoption artifact destination '{destination}' resolves outside the canonical artifact directory "
            f"'{canonical_artifact_root}'"
        )

    if not (destination.exists() or destination.is_symlink()):
        return
    try:
        aliases_source = source.samefile(destination)
    except OSError as e:
        raise AdoptError(f"cannot safely compare adoption artifact destination '{destination}': {e}") from e
    if aliases_source:
        raise AdoptError(f"adoption artifact destination '{destination}' aliases the native transcript")


def _check_still_adoptable(
    session_uuid: str, transcript_path: Path, claude_project_root: str, forge_root: str
) -> TranscriptSummary:
    """Run every precondition that can change between planning and writing.

    Split out of ``plan_adoption`` so ``adopt_session`` can re-run it after the
    double-attach prompt. That prompt blocks on a human, so the transcript can be
    deleted, or another terminal can adopt the same UUID, while it waits.

    Returns the summary it had to read anyway, so planning does not re-open the
    file to resolve the model.

    Raises:
        AdoptError: If the transcript is missing or belongs to another directory.
        UuidAlreadyBoundError: If the UUID already belongs to a session.
    """
    if not transcript_path.is_file():
        raise AdoptError(
            f"no transcript for conversation '{session_uuid}' under {claude_project_root}. "
            "Adopt from the directory the native session was launched from."
        )

    summary = summarize_transcript(transcript_path)
    recorded_cwd = summary.recorded_cwd
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

    # Index rows, their manifests, and orphan manifests under this project (card
    # step 1). The in-lock check inside add_session is index-only, so any binding
    # the index has not recorded would otherwise pass every gate and double-bind.
    try:
        owner = collect_bound_uuids(forge_root).get(session_uuid)
    except BindingLookupError as e:
        raise AdoptError(str(e)) from e
    if owner is not None:
        raise UuidAlreadyBoundError(session_uuid, owner)

    return summary


def _resolve_model_pin(summary: TranscriptSummary, model_override: str | None) -> tuple[str | None, str]:
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

    inferred = summary.last_model
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

    Ordering is validate -> ``start_session`` (binding **and** adoption
    provenance in one write) -> artifact copy -> index marker. The manifest and
    index row cannot be separated: ``start_session`` writes them back-to-back
    inside one try block and self-rolls-back on failure there.

    Compensation for anything after ``start_session`` returns is this function's
    job -- that block is unreachable once it returns, so the two stages are
    disjoint in time and cannot both fire for one failure.

    Raises:
        AdoptError: If the copy fails (after unwinding).
        UuidAlreadyBoundError: If another adopt bound this UUID first.
    """
    if ctx.forge_root is None:
        raise AdoptError("not inside a Forge project")

    _check_plan_invariants(ctx, plan)
    store = SessionStore(str(ctx.forge_root), name)
    paths = get_artifact_paths(ctx.forge_root, name)
    dst_abs = paths.transcripts_abs / f"{plan.session_uuid}.jsonl"
    dst_rel = paths.transcripts_rel / f"{plan.session_uuid}.jsonl"
    _validate_adoption_artifact_destination(
        forge_root=ctx.forge_root,
        source=plan.transcript_path,
        destination=dst_abs,
    )

    # Compatibility is re-enforced, not just re-read: the prompt between planning
    # and here blocks on a human, long enough for .forge/project.toml to change.
    try:
        enforce_project_compatibility(ctx.forge_root)
    except ProjectCompatibilityError as e:
        raise AdoptError(str(e)) from e

    # Scan and commit under one lock, for the reason given on conversation_lock:
    # a crashed adopt's orphan manifest owns the conversation without an index row,
    # so the index write lock alone cannot see it.
    with conversation_lock(plan.session_uuid):
        summary = _check_still_adoptable(
            plan.session_uuid, plan.transcript_path, plan.claude_project_root, str(ctx.forge_root)
        )

        # Re-resolve from the transcript as it is NOW. The double-attach prompt
        # blocks on a human, and a still-attached native client can add turns on a
        # different model while it waits -- persisting the planned pin would then
        # produce exactly the first-resume surprise the pin exists to prevent. An
        # explicit --model is the user's instruction, so it is never re-derived.
        model, model_basis = _resolve_model_pin(
            summary, plan.model if plan.model_basis == MODEL_BASIS_EXPLICIT else None
        )

        # worktree_path is passed explicitly rather than left to start_session's
        # `Path.cwd()` default (manager.py:542): the op must not depend on process
        # cwd. create_worktree stays False -- adoption binds an existing conversation
        # in place, and a True here would arm _rollback_worktree against a checkout
        # Forge did not create. Adoption provenance rides this same write, not the
        # artifact update below: a kill in between must not leave a bound session
        # that _adopted_source_uuids cannot recognize, or the retention sweep
        # would delete the user's native transcript.
        try:
            state = SessionManager().start_session(
                name,
                worktree_path=str(ctx.cwd),
                direct=True,
                claude_session_id=plan.session_uuid,
                direct_model=model,
                adoption=AdoptionConfirmed(
                    source_runtime=SOURCE_RUNTIME_CLAUDE,
                    adopted_at=now_iso(),
                    source_path=str(plan.transcript_path),
                    model_basis=model_basis,
                ),
                confirmed_by="cli:adopt",
                require_uuid_unbound=True,
            )
        except SessionExistsError:
            # A same-UUID adopt that got here first owns the derived name too, so
            # the name collision fires before the UUID check. Report the binding,
            # which is the contract, rather than a name clash the user did not
            # choose.
            try:
                owner = collect_bound_uuids(str(ctx.forge_root)).get(plan.session_uuid)
            except BindingLookupError as lookup_err:
                raise AdoptError(str(lookup_err)) from lookup_err
            if owner is not None:
                raise UuidAlreadyBoundError(plan.session_uuid, owner) from None
            raise

    artifact_created = False
    try:
        # Revalidate after publishing the binding: another process could replace
        # an artifact parent with a symlink between preflight and this copy.
        _validate_adoption_artifact_destination(
            forge_root=ctx.forge_root,
            source=plan.transcript_path,
            destination=dst_abs,
        )
        destination_existed = dst_abs.exists() or dst_abs.is_symlink()
        copied = safe_copy_file(plan.transcript_path, dst_abs, overwrite=True)
        artifact_created = copied and not destination_existed

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
            # confirmed.adoption was pre-seeded by start_session (write-once);
            # only the copy-dependent facts land here.
            m.confirmed.confirmed_by = "cli:adopt"
            m.confirmed.confirmed_at = now_iso()

        store.update(timeout_s=CLI_LOCK_TIMEOUT_S, mutate=_mutate)
    except Exception as e:
        _rollback_adoption(
            name,
            ctx=ctx,
            store=store,
            artifact_abs=dst_abs if artifact_created else None,
        )
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
        model=state.intent.launch.direct_model if state.intent.launch else model,
        model_basis=model_basis,
        artifact_rel=str(dst_rel),
        indexed=marker is not None,
    )


def _rollback_adoption(
    name: str,
    *,
    ctx: ExecutionContext,
    store: SessionStore,
    artifact_abs: Path | None,
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
    if artifact_abs is not None:
        try:
            artifact_abs.unlink(missing_ok=True)
        except OSError as e:
            _log.warning("Adopt rollback failed (artifact copy): %s", e)

    def _delete_manifest() -> None:
        # Removes .forge/sessions/<name>/ only -- not the artifact copy, which
        # lives under .forge/artifacts/<name>/ and is unlinked above.
        store.delete()

    try:
        # Keep the row and manifest removal under the same index lock as ordinary
        # deletion. Otherwise a same-name creator can publish between the two and
        # lose its manifest to this rollback.
        IndexStore().delete_session_txn(
            name,
            forge_root=str(ctx.forge_root),
            expect_manifest_absent=False,
            delete_manifest=_delete_manifest,
        )
    except Exception as e:
        _log.warning("Adopt rollback failed (session state): %s", e)
