# state_primitive_hoist -- hoist durable-state + JSONL-plane primitives to core leaves

**Lane**: `doing/` -- accepted 2026-07-05, branch `refactor/state-primitive-hoist`; executing as one batch card with a
phased checklist (each slice ships as its own commit/PR). Primitive extraction; mostly behavior-preserving, with **two
defect-fix slices** (Slice 3 adds fsync durability the copies lack; Slice 5 converges the `OSError -> Corrupted`
misclassification). Independently shippable slices. Highest-priority audit output (drift already shipped on state/money
paths).

> **Execution note (2026-07-05):** the card's "When accepted" section suggested per-slice member cards or an
> `epic_state_primitives` coordinator. We are instead running the batch as a **single `doing/` card with a phased
> checklist** (see `checklist.md`) per the operator's request; each slice still lands as an independent commit/PR, so
> the "not one atomic batch" intent is preserved. During checklist verification two card anchors were corrected:
> `backend/adapters/litellm.py:24` already imports the canonical `now_iso` (it is **not** a duplicate def, so Slice 1's
> repoint set is `install/models.py` + the four private `_now_iso` only); and `prune_jsonl_shards` has three import
> sites, not four. The Slice 5 `OSError -> Corrupted` divergence was re-verified as real across all four search read
> paths.

> **Superseded (2026-07-05):** historical. Accepted as a **single `doing/` card with a phased checklist** (see the
> Execution note under **Lane** and `checklist.md`); each slice still ships independently. Do **not** treat the
> per-member-card / epic suggestion below as a live instruction.

**When accepted**: a batch of independent primitive hoists, not one seam. Per `docs/developer/board_contract.md`,
promote as **separate member cards per slice** (or an `epic_state_primitives` coordinator if the leaf-module moves need
shared sequencing) rather than moving the whole batch to `doing/` at once.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`). 14 fan-out auditors + a
cross-cutting duplication sweeper. The atomic-write fsync gap, the `prune_usage_events` re-copy, the `now_iso` twin, and
the layering inversion were **inline-verified by diff** during the audit; the versioned-JSON read-skeleton /
`OSError->Corrupted` divergence is auditor first-pass evidence (its adversarial refuter was cut off by a spend cap --
re-verify before the Slice that touches it).

**Type**: single **refactor batch card**, deliberately **not an epic**. The slices share a theme (core owns the
primitive; packages import down), not one load-bearing contract. Each slice is independently landable.

**References**: `docs/design.md` §3.5 (file ownership), §3.14 (telemetry planes joined, not merged);
`docs/design_appendix.md` §A.13-A.14 (ledger/downstream schemas); `docs/developer/coding_standards.md` §5 (durable-state
discipline); `docs/board/impl_notes.md` ("One pruner for all JSONL planes", proxy_log_hygiene; "shared cost/usage
vocabulary Literals live in a telemetry leaf"); archetype `docs/board/done/session_op_layer_extraction/card.md`.

---

## Why (the thesis)

Multi-Forge has clean high-level layering (0 `forge.cli` imports in `core/`, 0 Click/print/exit in `core/ops/`). The
residual debt is one level down: **low-level durable-state and JSONL primitives that each package re-implements instead
of importing from a `core` leaf.** Three of these have already drifted -- the signature that proves a copy pair is
must-stay-identical, not benign:

1. **Atomic-write durability drifted.** `core/state/io.py:atomic_write_text` (`:58`) fsyncs the file **and** the parent
   dir (`:88-100`); Slice 3 will factor that durability into a bytes-capable helper with text layered on top. Five
   hand-rolled copies do tempfile + `os.replace` + chmod with **no fsync**: `config/loader.py:514-531`,
   `core/auth/credentials_file.py:228-238`, `runtime_config.py:721-730` (comment admits "matches proxy config pattern"),
   `cli/statusline/throttle.py:52-56`, `session/claude/relocate.py:153-159`. The durability fix never propagated -- a
   crash mid-write can corrupt credentials/config on the copies but not the canonical.
2. **The one-pruner contract is self-documented, then violated.** `proxy/retention.py:prune_jsonl_shards` (`:22-81`)
   says in its own docstring: *"This was duplicated byte-for-byte; centralizing it keeps the policy from drifting
   between planes."* Yet `core/usage/ledger.py:prune_usage_events` (`:273-309`) re-hand-rolls the exact age-then-size
   loop. And `core/telemetry/downstream.py:325` imports the canonical helper **from `forge.proxy.retention`** -- a
   core->proxy layering inversion.
3. **`now_iso` has no authority, so the installer became one -- and four private timestamp helpers hide from a naive
   grep.** `install/models.py:now_iso` (`:14-19`) is byte-identical to `core/state/timestamps.py:now_iso` (`:12-20`)
   with a stale provenance comment; `backend/adapters/litellm.py:24` already imports the canonical core helper (not a
   duplicate). The four private telemetry `_now_iso` copies emit a distinct second-precision `Z` format --
   `proxy/audit_logger.py:50`, `core/telemetry/downstream.py:44`, `core/telemetry/upstream.py:30`,
   `core/usage/ledger.py:75` -- so implementation preserves that byte format via a core `utc_timestamp_z()` helper. On
   top of that, `policy/semantic/shadow.py:29` + `shadow_runner.py:31` import `now_iso` **from `forge.install.models`**
   -- policy code depending on the *installer* package for a timestamp, while their sibling policy modules
   (`engine.py:14`, `store.py:13`, `team/handlers.py:24`) use the `core.state` authority. A metric that greps only
   `def now_iso` would miss the four private copies and report a false "single authority" at closeout.

Two more primitives are copied without (yet) proven drift: the secure-append writer mechanics (`downstream.py:143-160`,
`upstream.py:86-104`, `ledger.py:163-186`, whose comment says "mirrors audit_logger") and the versioned-JSON store
`read()` skeleton (`backend/registry.py`, `proxy/proxies.py`, `session/index.py`, `install/tracking.py`) -- with the
four `search/*_store.py` copies **already diverged** on classifying `OSError` as `Corrupted` vs `Unreadable`
(contradicts the PR #50 invariant that a failed read is environmental, not corruption).

This is behavior-preserving extraction of shared primitives to their designated home. It is not a deletion and not a
plane merge (the telemetry planes stay physically separate per §3.14 -- only the *write/prune mechanics* are hoisted).

---

## Non-goals / must-not-break

- **No plane merge.** downstream / upstream / usage-ledger stay physically separate (§3.14). This card shares
  *mechanics*, never joins the data.
- **No schema change.** File contents written by each copy stay byte-identical (same header comments, same key order,
  same indent). Adding fsync changes durability, not content.
- **Preserve the 0600 posture.** Credentials, proxy configs, and relocated transcripts write owner-only; the shared
  atomic-write primitives must accept an optional `mode` so the secure copies keep 0600.
- **Preserve `search` store semantics deliberately** where they are correct; the divergent `OSError->Corrupted`
  classification is the *bug to converge*, not a behavior to keep -- pin the corrected invariant with a test first.
- **Do not touch `core/telemetry/vocabulary.py`** or the credential-registry leaf (adjudicated deliberate, impl_notes)
  -- this card adds sibling primitive leaves, it does not reshape the existing ones.

---

## Target shape (core leaves; packages import down)

| Primitive                                                   | Canonical home (target)                                                   | Current copies to repoint                                                                                                             |
| ----------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Atomic text/bytes write (+ optional `mode`, fsync file+dir) | `core/state/io.py:atomic_write_bytes` + `atomic_write_text` delegates     | text: loader.py:514, credentials_file.py:228, runtime_config.py:721, statusline/throttle.py:52; bytes: session/claude/relocate.py:153 |
| JSONL secure-append record write                            | new `core/telemetry/jsonl_io.py` (or extend `open_secure_append` callers) | downstream.py:143, upstream.py:86, ledger.py:163                                                                                      |
| JSONL shard prune (age-then-size)                           | **move** `prune_jsonl_shards` -> `core/state/retention.py`                | proxy callers are repointed; dead ledger `prune_usage_events` is deleted, not wired                                                   |
| `now_iso()` / telemetry `Z` timestamp                       | `core/state/timestamps.py:now_iso` + `utc_timestamp_z`                    | install/models.py:17, four private `_now_iso` copies, policy shadow.py/shadow_runner.py imports                                       |
| Versioned-JSON store `read()` skeleton                      | new `core/state/versioned_store.py` helper                                | backend/registry.py, proxy/proxies.py, session/index.py, install/tracking.py, search/\*\_store.py (converge `OSError` policy)         |

---

## Phased plan (each slice independently landable)

| Slice | Scope                                                                                                                                                                                                                                                                                                                                                                                                | Exit signal                                                                                                                                  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | `now_iso` single authority: repoint the genuine public duplicate (`install/models.py`) and policy `shadow*.py` imports to `core.state.now_iso`; delete the four private `_now_iso` copies (`proxy/audit_logger.py:50`, `core/telemetry/downstream.py:44`, `core/telemetry/upstream.py:30`, `core/usage/ledger.py:75`) by moving their existing `Z` timestamp format to `core.state.utc_timestamp_z`. | `rg 'def _?now_iso' src/forge` returns only `core/state/timestamps.py`; policy no longer imports from `forge.install.models`                 |
| 2     | Move `prune_jsonl_shards` -> `core/state/retention.py`; proxy callers import down and `downstream.py` loses the inversion. Delete the dead exported `prune_usage_events` instead of wiring retention -- telemetry logs intentionally accumulate indefinitely.                                                                                                                                        | `core/telemetry/downstream.py` imports no `forge.proxy.*`; `rg -n 'prune_usage_events' src/forge tests` is empty                             |
| 3     | Add `atomic_write_bytes(mode=None)` with file+dir fsync, layer `atomic_write_text` on it, and repoint the 4 text copies plus the 1 binary transcript relocation copy.                                                                                                                                                                                                                                | 5 copies gone; characterization asserts identical text bytes, byte-for-byte transcript relocation, fsync file+dir, and 0600 where applicable |
| 4     | Secure-append JSONL writer: hoist the 0700-dir + lock + compact-JSON + swallow tail shared by the three plane writers.                                                                                                                                                                                                                                                                               | `downstream`/`upstream`/`ledger` write via one helper; per-plane record shape unchanged                                                      |
| 5     | Versioned-JSON `read()` skeleton to a `core/state` helper; converge the `search` stores' `OSError`->Unreadable classification to the PR #50 invariant.                                                                                                                                                                                                                                               | one read skeleton; `search` stores no longer classify `OSError` as `Corrupted`; regression test pins it                                      |

Slices 1-3 are the drift-proven, high-value work; 4-5 are consolidation with a re-verify gate on the auditor's
first-pass evidence.

---

## Blast radius

- Each primitive is a dependency leaf -> low importer count; the risk is caution-zone *correctness*, not patch churn.
- `prune_jsonl_shards` move: ~4 importers (audit, provider-trace, request, usage). `now_iso`: leaf util, wide but
  mechanical importer set (repoint, not restructure).
- **Caution zone:** credentials/config durable state (Slice 3) and money/telemetry writers (Slices 2, 4). Higher
  evidence bar; characterization test before each move.

## What was verified vs. first-pass

- **Inline-verified by diff (High):** fsync gap (io.py has it; loader.py + credentials_file.py copies lack it);
  `prune_jsonl_shards` docstring self-documents the anti-dup intent; `now_iso` byte-identical twin; core->proxy import
  inversion.
- **First-pass, re-verify before Slice 4/5 (Medium):** secure-append triplication; versioned-JSON read skeleton;
  `search`-store `OSError->Corrupted` divergence. Their adversarial refuters were cut off by a spend cap.

## Adversarial verification (survived where run)

The "provider-trace folded into downstream" adjudication (impl_notes) forbids recreating a separate *plane*; this card
proposes no plane change, only hoisting write/prune *mechanics* -- refuter brief 1 fails. Blast radius is leaf-scoped
(brief 2 fails). The copies are must-stay-identical (a durability/retention fix that lands on one and not the others is
a bug), so "allowed to diverge" (brief 3) fails.

## Risks

- **Durability change is not content change but is observable** (extra fsync syscalls, slower writes). Frame Slice 3 as
  the point of the card; a durable-state reviewer signs off.
- **`prune_usage_events` is also dead** (zero callers today -- see Surfaced Defect). Slice 2 deletes the dead export;
  wiring retention would be new behavior because telemetry logs intentionally accumulate indefinitely.
- **Search-store convergence changes error classification** at the search command surface. Pin the corrected
  `Unreadable`-not-`Corrupted` behavior with a regression test for `forge search clean` / search reads (PR #50
  invariant).

## Metric / falsifiable prediction

```bash
targeted tests with an os.fsync spy              # all 5 ex-copy paths fsync file + parent dir through the shared helper
rg -l 'from forge\.proxy\.retention' src/forge/core   # -> empty after Slice 2 (inversion gone)
rg -n 'def _?now_iso' src/forge                # -> 1 (single authority; catches the private _now_iso copies too)
```

Prediction: the next durability or retention fix touches **1 leaf, not 5**; adding a JSONL plane reuses the writer
instead of a 4th copy. Confirm on the next 3 telemetry/state PRs.

## Acceptance (per-slice)

A slice ticks only when: (a) `rg` of the removed symbol/copy returns only the canonical home; (b) a characterization
test asserts identical written bytes (and 0600 where applicable) before/after; (c) the focused test module plus the
relevant integration path pass; (d) no plane data was merged (planes stay separate); (e) **the two defect-fix slices
carry a regression test** -- Slice 3 asserts the durability behavior (fsync file+dir now applies on the ex-copies) and
Slice 5 asserts a failed read classifies as `Unreadable`, not `Corrupted` (the PR #50 invariant).

## Closeout

(pending)
