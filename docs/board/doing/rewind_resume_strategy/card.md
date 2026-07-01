# Rewind Resume Strategy — drop the last N turns, keep an AI code-delta

**Status**: Active (in `doing/`, accepted 2026-07-01). Slices 1-2 are locked in code/docs; next implementation slice is
Slice 3 (see `checklist.md`). A new `ResumeStrategy` sibling to `ai-curated`, selected via
`forge session fork|resume --strategy rewind --drop-last N`. `docs/design.md` resume/transfer contracts remain
normative; this card defers to them on conflict.

**Type**: Single active card. Larger than a flag because it is the **first resume path that carries real Claude history
*and* a generated context file** — a deliberate break of the current `native ⟹ no context file` invariant. Treat the
invariant decision (Slice 1) as a gate before the rest.

**Decided (2026-06-22)**: Real conversational rewind, as its own strategy, over a flag on `ai-curated`. A flag cannot
express it — `ai-curated` is a transfer-mode strategy that carries no real history, and the value here is precisely
carrying *live* history minus the tail. The strategy reuses `ai-curated`'s internals but is a distinct surface and
document contract.

**Decided (2026-06-22, design refinement)**:

- **N counts turns** — the `[turn N]` grouping from `_format_transcript_for_llm`, not raw JSONL lines (resolves old Q2).
- **Parent-only** — `rewind` rewinds *this* session's own tail; multi-ancestor `--depth` is out of scope (resolves old
  Q5).
- **Fresh rewind-owned UUID** for the truncated copy, not the parent's — see "Truncated-copy identity & GC" (resolves
  old Q3).
- **`--drop-last` is required** — no default N.

**Decided (2026-07-01, Slice 1)**:

- **Fresh stem does not require envelope rewrite.** Live probe on Claude Code 2.1.197: copied a signed parent JSONL to a
  child encoded dir as `<R>.jsonl` while keeping embedded `sessionId=<parent_uuid>`, then ran
  `claude --bare --print --allowed-tools Read --permission-mode bypassPermissions --resume R --fork-session`. Result:
  `mismatch_exit=0`, parent copy unchanged, `parent_has_signature=yes`.
- **Derivation shape**: `resume_mode="native-relocate"` + `strategy="rewind"` + `context_file=<delta>` +
  `dropped_turns=N` + `rewind_relocated_session_id=R`.
- **GC-id field**: do **not** overload `relocated_parent_session_id`; it remains the parent UUID for byte-for-byte
  native-relocate copies. `rewind_relocated_session_id` records the fresh truncated-copy UUID.

**Decided (2026-07-01, Slice 2)**: `--drop-last 0` is a no-op and downgrades to plain native-relocate manifest
semantics: `strategy=null`, no `dropped_turns`, no `context_file`, and no `rewind_relocated_session_id`. The CLI should
surface that as a no-op rather than writing a rewind manifest that did not rewind.

The Slice 2 writer also pins `N>=T` at the primitive level: it writes an empty prefix and reports `kept_turns=0`. That
artifact is metadata for the caller, not a launchable native-resume head; Slice 4 must reject or fall back before any
`claude --resume` attempt.

**References**: `docs/design.md` "Transfer mode strategies" + "Session derivation tracking", §3.9 (resume across path
boundaries); `src/forge/session/transfer.py`; `src/forge/session/manager.py`; `src/forge/cli/session_fork.py`;
`docs/board/done/forge_cli_cleanup/card.md` (option-drift findings #4/#5).

## Summary

Add a resume/fork strategy that **rewinds the conversation by N turns while keeping the code those turns produced**.

Given a parent session with turns `1..T`:

1. Carry turns `1..(T−N)` as **real Claude history** — relocate a *truncated* copy of the parent JSONL (native-relocate
   that writes a prefix, not the whole file).
2. Run a focused AI pass over **only** the dropped window `(T−N)..T` to produce a **code-delta**: which files/code
   changed, grounded in turn/file citations.
3. Deliver that delta as a context file (`--append-system-prompt-file`) alongside the truncated resume.

The child resumes as if the last N turns never happened *conversationally*, but starts knowing exactly what code those
turns left on disk. It is `ai-curated` **partially applied**: curation runs only on the dropped tail and is narrowed to
code changes, while the head is carried verbatim instead of summarized.

> **Rewind is conversational, not git.** The files on disk stay at turn-`T` state. `--drop-last` never reverts code; it
> rewinds the *conversation* and hands the agent a note describing the disk/conversation gap. This is not `git reset`.

## Problem

The two existing ways to resume past a messy tail both lose something:

- **Native / native-relocate** carries the whole conversation byte-faithfully — including the derailed tail, failed
  attempts, and polluted context you wanted to drop. There is no way to carry "most of it."
- **`ai-curated`** can shed detail, but it replaces the *entire* conversation with a prose summary — you lose all live
  history, not just the tail, and it pays to summarize turns you wanted verbatim.

Nothing offers "keep the good part of the conversation live, forget the bad tail, but don't lose the code the bad tail
wrote." Native rewind alone makes the agent forget it authored that code; full carry keeps the mess.

## Why not `/compact` or `ai-curated`?

| Aspect           | `/compact` (native) | `ai-curated`     | proposed `rewind`            |
| ---------------- | ------------------- | ---------------- | ---------------------------- |
| Boundary control | model-chosen        | whole transcript | user picks N (turns)         |
| Head carried as  | lossy summary       | summary doc      | **real live history** 1..T−N |
| Tail treatment   | folded into summary | folded in        | **code-delta only**          |
| AI-pass cost     | n/a (in-session)    | full transcript  | dropped window only          |
| Inspectable doc  | no                  | yes              | yes (delta doc)              |
| Reverts code?    | no                  | no               | **no** (conversation only)   |

The differentiator is the two middle rows: live head + code-only tail. Neither existing path offers it.

## Concept

```text
parent turns:  1 2 3 ............... T-N | T-N+1 ... T
               └────── carried verbatim ──┘ └── dropped ──┘
                      (truncated relocate)     (AI code-delta)

child sees:  real Claude history 1..T-N      +   "Code delta of dropped turns:
             (--resume --fork-session)              - src/foo.py: added retry (turn T-3)
                                                    - src/bar.py: removed X (turn T-1)
                                                    NOTE: files already contain these;
                                                    the conversation is rewound to before them."
                                                 (--append-system-prompt-file)
```

## Design context (normative constraints)

| Constraint                                                               | Source                                         | Implication                                                                                                                        |
| ------------------------------------------------------------------------ | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `strategy` is null / ignored for native modes                            | `models.py:456-459`; `session_fork.py:544-548` | This strategy makes `Derivation.strategy` non-null under `native-relocate` — the core convention change.                           |
| Native modes generate no context file                                    | `design.md` "Native mode"                      | The launch path must attach `--append-system-prompt-file` to a `--resume --fork-session` launch — new combo.                       |
| native-relocate copies the parent JSONL + records relocated id           | `manager.py:1364-1395`                         | Extend the copy to write a *truncated prefix*; record an identity that distinguishes it from the parent.                           |
| Relocate cleanup reference-counts assuming relocated id == parent id     | `manager.py:1818-1855`                         | Decided: `rewind` uses a fresh UUID + `rewind_relocated_session_id`, so parent-id reference counting remains native-relocate-only. |
| native-relocate copies byte-for-byte, refuses to clobber differing bytes | `relocate.py` (`relocate_transcript`)          | A truncated copy can't reuse the parent UUID — hence the fresh-UUID decision below.                                                |
| native-relocate is host-only, worktree/`--into` only, rejects sidecar    | `session_fork.py:473-538`                      | `rewind` inherits these; it is **not** available for same-dir or sidecar forks. Document the rejection.                            |
| Turn anchors exist via `_group_entries_into_turns` / `[turn N]`          | `transfer.py:600`                              | "Last N" is a turn split at `T−N`; reuse the grouping so the delta's citations stay groundable.                                    |
| ai-curated LLM/usage/citation helpers                                    | `transfer.py` curation helpers                 | Reuse wholesale for the delta pass — `rewind` is a new surface over shared internals, not a code fork.                             |

## Central decision: real history + a context file (Slice 1 gate)

Forge currently treats "carry real conversation" and "generate a context file" as mutually exclusive — they are
different rows of the resume-mode matrix:

| Mode                     | `resume_mode`           | real conversation? | `strategy`     | context file? |
| ------------------------ | ----------------------- | ------------------ | -------------- | ------------- |
| native / native-relocate | native(-relocate)       | yes (full)         | null (ignored) | no            |
| `ai-curated` (transfer)  | transfer                | no (summary doc)   | `"ai-curated"` | yes           |
| **`rewind` (accepted)**  | native-relocate + trunc | yes (1..T−N)       | `"rewind"`     | yes (delta)   |

`rewind` is the first path that needs both columns true. Slice 1 must decide and document:

- `Derivation.strategy = "rewind"` coexisting with `resume_mode = "native-relocate"` (today `strategy` is null for
  native).
- A `Derivation` field recording N: `dropped_turns: int | None`.
- The launch path emitting `--resume --fork-session` **and** `--append-system-prompt-file` together.
- Identity + GC for the truncated copy — **decided: a fresh rewind-owned UUID** stored as `rewind_relocated_session_id`,
  not the parent's.

Everything downstream is plumbing; this is the load-bearing change.

## Truncated-copy identity & GC (decided: fresh UUID)

native-relocate's safety rests on a **byte-identity invariant** (`relocate.py`): it copies `<parent_uuid>.jsonl`
content-untouched, refuses to clobber a destination holding *different* bytes (`RelocateConflictError`), and the GC
reference-counts on "same UUID ⟹ same bytes ⟹ one shared copy" (`manager.py:1824-1830`). A truncated copy breaks that
invariant — same parent UUID, different bytes — so reusing the parent UUID would trip the conflict guard, mis-count in
GC, or (distinct CWDs can encode to the same dir) overwrite the parent's original transcript.

**Decision**: the truncated copy gets a **fresh, rewind-owned UUID `R`**, written as `<R>.jsonl` in the child's encoded
dir; the child launches `--resume R --fork-session`. Because `R` is unique per rewind the copy is **never shared** —
cleanup deletes `<R>.jsonl` with the session, no `_find_shared_transcript_sessions` scan. This closes the GC-mis-count
risk by construction instead of extending the shared-copy machinery, and `R ≠ parent_uuid` makes overwriting the
parent's original impossible.

**Probe result (2026-07-01)**: JSONL entries carry an internal `sessionId`, but Claude Code 2.1.197 accepts `--resume R`
when the filename stem is `R` and embedded `sessionId` remains the parent UUID. The parent transcript in the probe
carried a signature and the relocated copy stayed unchanged, so Slice 5 does **not** need an envelope `sessionId`
rewrite. This probe isolated stem tolerance on a whole-copy JSONL; clean-prefix truncated JSONL resume remains a Slice 5
integration assertion.

## Proposed surface

```text
forge session fork <parent> --worktree --strategy rewind --drop-last N
forge session resume <parent> --fresh --strategy rewind --drop-last N
```

- `--strategy rewind`: new `ResumeStrategy` value + Choice entry (`session_fork.py:139` and the resume surface).
- `--drop-last N`: required non-negative integer (no default); N counts **turns** (the `[turn N]` grouping), not raw
  JSONL lines.
- Resolves to `resume_mode = native-relocate` (worktree/`--into` only). Same-dir/sidecar → rejected with the existing
  native-relocate guidance.
- Manifest for `N>0`: `derivation.resume_mode=native-relocate`, `strategy=rewind`, `dropped_turns=N`,
  `context_file=<delta>`, `rewind_relocated_session_id=R`. `N=0` downgrades to plain native-relocate metadata.

## Code-delta extraction

- **Primary source — transcript tool-calls** (`Edit`/`Write`/`MultiEdit`/`NotebookEdit`) within the dropped window: maps
  1:1 to "since the last N turns"; reuse `_group_entries_into_turns`.
- **Net change, not replay**: reconcile multiple edits to the same file into the net delta (later edits supersede
  earlier within the window).
- **Grounding**: reuse `_validate_decision_citations` so each entry cites a real dropped turn or file; drop ungrounded
  claims.
- **Prompt**: a narrowed variant of `AI_CURATION_USER_PROMPT_TEMPLATE` asking for (1) files changed + what + why, (2)
  net effect, (3) unfinished/dangling edits to resolve — plus the explicit "files already contain these; the
  conversation is rewound to before them" framing.
- **Optional**: `git diff` of the parent worktree as a cross-check, not the boundary (commits ≠ turns).

## Reuse vs new

**Reuse**: `_call_llm_for_curation` + `_emit_curation_usage` (OpenRouter direct + usage ledger, emit-before-parse-gate),
`_validate_decision_citations`, untrusted-transcript system prompt (`transfer.py:72`), turn windowing,
frontmatter/schema-marker plumbing, the fallback-chain pattern, the native-relocate copy + encoded-dir placement (but
not its shared-copy GC — `rewind` uses a fresh-UUID unshared copy instead).

**New**: turn split at `T−N`; truncated relocate (prefix copy + safe-boundary snap); code-delta prompt + renderer + new
`schema` marker; co-delivery of a context file with a native-relocate launch (the convention change);
`Derivation.dropped_turns` + `Derivation.rewind_relocated_session_id`; `ResumeStrategy.REWIND` + `--drop-last`; a
fresh-UUID, unshared truncated copy (no envelope `sessionId` rewrite needed per Slice 1).

## Risks

- **Invariant break (central).** native-relocate + context file; audit every site that assumes
  `strategy is null ⟺ native`.
- **Unsafe JSONL truncation.** Cutting mid `tool_use`/`tool_result` pair corrupts `--resume`. Need
  snap-to-last-complete- turn ≤ T−N; test a tool-call straddling the cut.
- **Empty rewind head.** `N>=T` produces `kept_turns=0` at the writer level; Slice 4 must not launch an empty
  `<R>.jsonl` as native resume.
- **Silent extra drop.** Safe-boundary snap can keep fewer turns than requested when the boundary lands in a tool chain;
  the CLI must say how many additional turns were dropped.
- **GC mis-count (resolved by design).** Reusing the parent UUID for different bytes would mis-count or overwrite the
  parent's original; the fresh-UUID decision and distinct `rewind_relocated_session_id` make the copy unshared.
- **Deliberate desync confusion.** Conversation is at T−N, disk at T. If the delta note is weak the agent may redo work
  or get confused. The note must state the gap explicitly — this is the strategy's whole UX bet.
- **Delta inaccuracy.** Tool-calls may not equal final state; reconcile to net change.
- **Inherited native-relocate limits.** Host-only, worktree/`--into` only — not a general-purpose strategy.
- **Privacy.** Dropped-window code/transcript sent to an external model; emit the same warning as `ai-curated`.

## Slices

1. **Decision + invariant slice (gate).** Lock the `Derivation` shape (non-null `strategy` under native-relocate +
   `dropped_turns` + `rewind_relocated_session_id=R`); run the `sessionId`-match probe; update the design.md
   resume-mode×strategy contract. **Done; awaiting review.**
2. **Turn window + safe truncation.** Split at T−N on a coherent boundary; truncated-JSONL writer; pin degenerate N=0
   manifest semantics (plain native-relocate); pin writer-level N≥T semantics as an empty prefix that Slice 4 must
   reject or route around before launch.
3. **Code-delta extractor + prompt.** Tool-call delta from the dropped window; net-change reconciliation; narrowed
   prompt; reuse citation grounding + usage emit + injection hardening.
4. **Wire the strategy.** `ResumeStrategy.REWIND`; `--drop-last` + Choice on fork/resume; co-deliver context file with
   the native-relocate launch; populate `Derivation`.
5. **Identity + cleanup.** Fresh-UUID truncated copy (no envelope rewrite); delete `<R>.jsonl` with the session, no
   parent-id reference-counting; test the parent/sibling transcript is never touched.
6. **Fallback + privacy + docs.** Fallback to plain native-relocate (+ "code-delta unavailable" note) on AI failure;
   privacy warning; design.md / design_appendix.md §H / cli_reference.md / end-user `transfer.md` updates.

## Acceptance tests

| Test                                  | Fixture                                    | Assertion                                                                                          | Test File                                   |
| ------------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Truncated relocate carries head       | parent with T turns, `--drop-last N`       | child JSONL has turns 1..T−N, none of T−N+1..T                                                     | `tests/src/session/test_rewind_strategy.py` |
| Truncation snaps to safe boundary     | tool_use/result pair straddling T−N        | relocated JSONL ends on a complete turn (resume not corrupted)                                     | same                                        |
| Delta cites only dropped turns        | edits in the dropped window                | delta lists changed files citing turns T−N+1..T; no head citations                                 | same                                        |
| Native resume + context file together | `--strategy rewind` worktree fork          | launch carries `--resume --fork-session` AND `--append-system-prompt-file`                         | same                                        |
| Empty head is not launched            | `--drop-last >= T`                         | CLI rejects or falls back before running `claude --resume` against an empty `<R>.jsonl`            | same                                        |
| Safe-boundary snap is disclosed       | snap keeps fewer turns than requested      | user-facing output says how many additional turns the snap dropped                                 | same                                        |
| Writer failure falls back             | non-contiguous transcript prefix           | plain native-relocate fallback + note; no traceback                                                | same                                        |
| Resume tolerates fresh UUID           | rewind launch, truncated fresh `<R>.jsonl` | child resumes from clean-prefix `<R>` with embedded parent `sessionId`; no "No conversation found" | same                                        |
| Manifest records rewind               | `--drop-last N`                            | `resume_mode=native-relocate`, `strategy=rewind`, `dropped_turns=N`                                | same                                        |
| Same-dir/sidecar rejected             | same-dir or sidecar fork + `rewind`        | rejected with native-relocate-only guidance                                                        | `tests/src/cli/test_session_fork.py`        |
| AI failure falls back                 | LLM error                                  | plain native-relocate + "code-delta unavailable" note; resume still works                          | `tests/src/session/test_rewind_strategy.py` |
| Truncated copy is unshared            | sibling/parent in same encoded dir         | `<R>.jsonl` deleted with the session; parent/sibling transcript untouched                          | same                                        |
| Net-change reconciliation             | file edited twice in the window            | delta shows net change, not both edits                                                             | same                                        |
| Privacy warning                       | any rewind run                             | "code/transcript sent to <model>" surfaced                                                         | same                                        |

## Open questions

1. **Strategy value name**: `rewind` (working) vs `tail-curated` / `code-delta` / `rewind-curated`.
2. **Delta source**: tool-calls only (recommended) vs + git-diff cross-check.
3. **Choosing N**: add a turn-boundary preview (a `forge transfer show --turns`-style view?) so users pick N without
   guessing — possible follow-up.
4. **N≥T UX**: reject with guidance or fall back to a transfer-style path; do not launch an empty native transcript.
5. **Transfer-mode variant**: ever offer a summarized-head form for same-dir, or keep `rewind` strictly native-relocate?
   (Card says strictly native-relocate.)

**Resolved (2026-06-22)**: N counts turns (old Q2), parent-only (old Q5), fresh-UUID unshared truncated copy (old Q3) —
see the Decided block and "Truncated-copy identity & GC".

## Out of scope

- Same-directory or sidecar rewind (native-relocate constraints).
- A transfer-mode (summarized-head) variant of rewind.
- Reverting code on disk / git-history rewriting — rewind is conversational only; disk stays at turn-T.
- Auto-selecting N.
- Multi-ancestor rewind (`--depth` > parent); `rewind` is parent-only by decision.
- Curating the carried real history (that is plain native-relocate; rewind only curates the dropped tail).

## References

- `src/forge/session/transfer.py` — `ResumeStrategy` (:101), strategy dispatch (:1182-1215),
  `_generate_ai_curated_context` (:944), `_call_llm_for_curation` / `_emit_curation_usage`,
  `_validate_decision_citations` (:801), `_format_transcript_for_llm` (:600), untrusted-transcript prompt (:72)
- `src/forge/session/manager.py` — native-relocate copy + derivation (:1358-1387), relocate cleanup/GC (:1812-1850)
- `src/forge/session/claude/relocate.py` — `relocate_transcript` byte-identity/conflict model (`RelocateConflictError`,
  `RelocateSameDirError`) the truncated copy must not reuse
- `src/forge/session/models.py` — `Derivation` (:367-403); `strategy` null-for-native note (:384)
- `src/forge/cli/session_fork.py` — `--strategy` Choice (:139), `--resume-mode` Choice (:161), native-relocate
  preflights (:473-538), `--strategy` ignored under native-relocate (:531)
- `docs/design.md` — "Transfer mode strategies", "Session derivation tracking", §3.9 resume across path boundaries
- `docs/board/done/forge_cli_cleanup/card.md` — option-drift findings (#4/#5) the `--drop-last` surface must respect
