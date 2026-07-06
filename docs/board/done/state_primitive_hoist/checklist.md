# state_primitive_hoist checklist

## Current focus

Hoist five low-level durable-state / JSONL primitives to their designated `core` leaf so packages import *down* instead
of re-implementing them. Structure: **one batch card, phased** -- each slice below is an independent commit/PR (no
atomic mega-merge). Slices 1-3 are drift-proven and inline-verified (ready). Slices 4-5 carry a **re-verify gate**
before code moves (their audit refuters were spend-capped; both claims have now been re-verified during implementation).

**Status: shipped via PR #80, merged to `main` as `9c6186c7`, and closed out on the board.**

## Review corrections applied (2026-07-05)

Incorporated from checklist review (each verified against the code before applying):

- **Phase 3 (High):** `session/claude/relocate.py` is **byte-preserving binary I/O**
  (`read_bytes()`/`wb`/`source_bytes`, `relocate.py:124,156`) to keep signed transcript blocks byte-exact. It must
  **not** repoint to a text helper. Phase 3 now adds a core `atomic_write_bytes(..., mode=)` primitive (with
  `atomic_write_text` layered on it); relocate uses the bytes primitive. Concurrency is safe: the canonical writer
  already uses `mkstemp` (`io.py:82`), so the shared bytes primitive preserves relocate's unique-temp
  concurrent-same-UUID guarantee.
- **Phase 5 (Medium):** there are **four** search read paths, not three -- `search/index_state.py:200` shares the
  `OSError -> IndexStateCorruptedError` bug. Added to the phase + matrix.
- **Phase 5 (Medium):** the acceptance gate was wrong. Global `forge clean` **excludes the rebuildable search cache**
  (`gc.py:594`), so "forge clean won't delete" is untestable. The real surface is `forge search clean` / search reads
  and their unreadable-vs-corrupt routing (`cli/search.py:383`).
- **Phase 2 (Medium):** dropped "wire usage-events retention" as an option -- telemetry logs **accumulate indefinitely**
  by design (design_appendix §A.9, `:498`), so a live retention caller is a behavior change, not a refactor. Phase 2 now
  moves the live pruner and **deletes** the dead exported `prune_usage_events`; retention policy is left to a separate
  design/simplicity card.
- **Phase 1 (Medium):** the private telemetry `_now_iso` helpers were **not** byte-identical to `now_iso`; they emitted
  second-precision `Z` timestamps while `core.state.now_iso` is intentionally tested as `+00:00`. Implementation
  preserves bytes by moving that format to `core.state.utc_timestamp_z()` and deleting the private local helpers.
- **Structure:** staying one `doing/` card; the card's old "When accepted" note is marked **superseded** so future
  sessions do not read it as a live instruction.

## Ground rules (from the card, non-negotiable)

- **No plane merge.** downstream / upstream / usage-ledger stay physically separate (design.md §3.14). This card shares
  *write/prune mechanics*, never joins the data.
- **No schema/content change.** Each ex-copy writes byte-identical file contents (same header comments, key order,
  indent). Adding fsync changes *durability*, not content. The binary relocate path stays **byte-for-byte** (no
  decode/re-encode).
- **Preserve the 0600 posture.** Credentials, proxy configs, and relocated transcripts write owner-only; the shared
  atomic-write primitives (`atomic_write_text` / `atomic_write_bytes`) take an optional `mode` so secure callers keep
  0600\.
- **Do not touch** `core/telemetry/vocabulary.py` or the credential-registry leaf (adjudicated deliberate, impl_notes).
- **Per-slice acceptance gate:** (a) `rg` of the removed symbol returns only the canonical home; (b) a characterization
  test asserts identical written bytes (+ 0600 where applicable) before/after; (c) the focused test module + the
  relevant integration path pass; (d) no plane data merged; (e) the two defect slices (3, 5) each carry a regression
  test.

## Caution zones (higher evidence bar)

- **Slice 3** touches credentials/config (text) **and** signed transcripts (binary) -- a durable-state reviewer signs
  off; characterization test (identical bytes + 0600) before the move; the binary path asserts byte-for-byte equality.
- **Slices 2 and 4** touch money/telemetry writers -- characterization test that per-plane record bytes are unchanged
  before consolidating.

---

## Phase 1 -- `now_iso` single authority [implemented]

Repoint the public duplicate to `core/state/timestamps.now_iso` (`:12`, the authority), move telemetry's existing `Z`
timestamp format to `core/state/timestamps.utc_timestamp_z`, and delete the duplicate defs.

- [x] Repoint the one genuine **public** duplicate def `install/models.py:17` -> `core.state.now_iso`; delete the local
  def.
- [x] Repoint the **four private** `_now_iso` copies to `core.state.utc_timestamp_z` and delete them:
  `proxy/audit_logger.py:50`, `core/telemetry/downstream.py:44`, `core/telemetry/upstream.py:30`,
  `core/usage/ledger.py:75`. This preserves the existing `Z` timestamp bytes while removing local timestamp defs.
- [x] Repoint the two policy importers off the **installer** package: `policy/semantic/shadow.py:29`,
  `shadow_runner.py:31` (`from forge.install.models import now_iso` -> `from forge.core.state import now_iso`).
- **Correction vs card:** `backend/adapters/litellm.py:24` is **already correct** (it imports
  `from forge.core.state import now_iso`, used at `:123`). Not in the repoint set -- do not "fix" it.
- **Exit signal:** `rg -n 'def _?now_iso' src/forge` returns **only** `core/state/timestamps.py`;
  `rg -n 'install\.models import now_iso' src/forge/policy` is empty.

## Phase 2 -- prune to `core/state/retention.py`; kill the core->proxy inversion; drop dead pruner [implemented]

- [x] Move `prune_jsonl_shards` -> `core/state/retention.py`; delete the dead `proxy/retention.py` shim after repointing
  the live import sites: `proxy/utils.py`, `core/telemetry/downstream.py:325`.
  - Assertion: `rg -l 'from forge\.proxy\.retention' src/forge/core` is **empty** (the `downstream.py:325` inversion is
    gone -- core imports down). Live callers (audit / provider-trace / request planes) keep pruning identically.
- [x] **Delete** the dead `core/usage/ledger.py:prune_usage_events` (`:273`) + its `core/usage/__init__.py` export
  (`:32`, `:55`) + any direct test. Clean break: it has **zero callers**, and wiring a retention caller would be new
  behavior (telemetry accumulates indefinitely by design, appendix §A.9). Do **not** wire retention.
  - Assertion: `rg -n 'prune_usage_events' src/forge tests` is empty; usage-events retention policy is explicitly out of
    scope (separate design/simplicity card if ever wanted).
- **Caution zone (money/telemetry):** characterization test that which shards get pruned for a given age/size budget is
  unchanged for the live planes.
- **Exit signal:** `core/telemetry/downstream.py` imports no `forge.proxy.*`; `prune_usage_events` is gone; one pruner.

## Phase 3 -- `atomic_write_bytes` + `atomic_write_text` (fsync file+dir); repoint 4 text + 1 binary [implemented; DEFECT-FIX; caution zone]

The durability fix (`core/state/io.py:atomic_write_text` fsyncs file `:91` + dir `:96`) never propagated to five
hand-rolled tempfile+`os.replace` copies that do **zero** fsync -- a crash mid-write can corrupt credentials/config (and
skip the durability guarantee on relocated transcripts).

- [x] Add core `atomic_write_bytes(path, data: bytes, *, mode: int | None = None, create_parents=True)` in
  `core/state/io.py`, factored from the existing `mkstemp` -> write -> fsync-file -> `os.replace` -> fsync-dir pattern
  (so unique-temp concurrency + fsync are preserved). Refactor `atomic_write_text` to encode UTF-8 and **delegate** to
  it (single durability implementation).
  - Assertion: `atomic_write_text` behavior/bytes unchanged; `atomic_write_bytes` writes raw bytes with no
    decode/re-encode; `mode` sets final perms (default preserves `mkstemp` 0600).
- [x] Repoint the **four text** copies -> `atomic_write_text`: `config/loader.py`, `core/auth/credentials_file.py`,
  `runtime_config.py`, `cli/statusline/throttle.py`.
- [x] Repoint the **one binary** copy -> `atomic_write_bytes(mode=0o600)`: `session/claude/relocate.py:156`. Keep
  `read_bytes()` -> write bytes; **no** text decode. Preserve the unique-temp (concurrent same-UUID relocation) and 0600
  guarantees (both inherent to the shared `mkstemp` primitive).
- **Regression test required** (defect-fix gate): `os.fsync` invoked for file fd **and** parent-dir fd on each of the 5
  ex-copy paths; **text** paths write byte-identical content + mode; the **binary** relocate path writes a file
  byte-for-byte equal to `source_bytes` (signed transcript preserved, no decode drift).
- **Durable-state reviewer sign-off required** before merge (durability is an observable change: extra fsync syscalls).
- **Exit signal:** the 5 copies are gone; targeted tests prove all 5 ex-copy paths fsync file+dir through the shared
  helper; regression + characterization green.

## Phase 4 -- secure-append JSONL writer hoist [implemented]

**Gate resolved:** re-verified the triplication first. Confirmed the 0700-dir + lock + compact-JSON + swallow-tail is
genuinely shared by `downstream.py:143`, `upstream.py:86`, `ledger.py:163` before extracting.

- [x] Hoist the shared secure-append mechanics into one helper (new `core/telemetry/jsonl_io.py`, or extend the existing
  `open_secure_append` callers). The three plane writers append via it; **per-plane record shape/bytes unchanged**.
- **Caution zone (money/telemetry):** characterization test per plane -- a written record is byte-identical.
- **Exit signal:** one secure-append writer; three planes delegate; record shapes unchanged.

## Phase 5 -- versioned-JSON read skeleton + converge search `OSError` policy (4 stores) [implemented; DEFECT-FIX]

**Re-verify status: the divergence is CONFIRMED** (2026-07-05) across **all four** search stores -- a read `OSError` is
classified `Corrupted`, contradicting the PR #50 invariant (a failed read is environmental = `Unreadable`, not
corruption): `search/content_store.py:95`, `search/bm25_store.py:122`, `search/store.py:108`,
`search/index_state.py:200`. The five readers PR #50 fixed (store-index-tracking-proxies-backend) never included the
search stores.

- [x] Extract the versioned-JSON `read()` skeleton (backend/registry, proxy/proxies, session/index, install/tracking,
  search x4) into a `core/state/versioned_store.py` helper. **Re-verify the skeleton claim per-store before collapsing**
  (first-pass evidence). Each store keeps its own record shape + exception *type*.
- [x] Converge the **four** search stores' `OSError` handling to **Unreadable**, not `Corrupted`. Introduce four
  search-specific subclasses under `core/state/exceptions.StateUnreadableError` (`:40`):
  `SearchDocumentStoreUnreadableError`, `BM25IndexUnreadableError`, `ContentStoreUnreadableError`,
  `IndexStateUnreadableError` (decision: domain-specific subclasses, not bare `StateUnreadableError` -- keeps CLI
  JSON/error handling crisp). A bad/missing `schema_version` or invalid JSON stays `Corrupted`; **only** `OSError`
  becomes `Unreadable`.
  - Assertion: a read `OSError` in each of the four stores raises its `*UnreadableError`; JSON/schema faults still raise
    `*CorruptedError`.
- [x] Route the new Unreadable variants correctly at the **search** surface: `forge search clean` / search read commands
  (`cli/search.py:383`) treat Unreadable as check/retry, not reset/corrupt.
  - **Note (corrected gate):** global `forge clean` **excludes** the rebuildable search cache (`gc.py:594`), so it is
    **not** the surface under test -- assert on `forge search clean` / search reads, not `forge clean`.
- **Regression test required** (defect-fix gate): a patched `open()` raising `OSError` in each of the four stores yields
  the store's `*UnreadableError`, not `*CorruptedError`; `forge search clean` routes it as check/retry.
- **Exit signal:** one read skeleton; four search stores classify `OSError` as `Unreadable`; regression pins it.

---

## Acceptance tests (fixture-grounded)

| Test                              | Fixture                                          | Assertion                                                                            | Test File (target)                                                   |
| --------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| `now_iso` single authority        | repo static scan                                 | `rg 'def _?now_iso' src/forge` -> only `core/state/timestamps.py`                    | `tests/src/core/state/test_timestamps.py` (+ grep guard)             |
| prune moved; inversion gone       | telemetry shards over an age/size budget         | downstream imports no `forge.proxy.*`; same shards pruned; no `prune_usage_events`   | `tests/src/core/state/test_retention.py` (new)                       |
| atomic-write durability -- text   | temp path, `os.fsync` spy; credential/proxy 0600 | fsync on file fd + parent-dir fd; bytes + 0600 unchanged                             | `tests/regression/test_bug_state_atomic_write_fsync.py` (new)        |
| atomic-write durability -- binary | relocate a transcript with signed bytes          | written file == `source_bytes` byte-for-byte (no decode drift); fsync file+dir; 0600 | same regression file (relocate case)                                 |
| secure-append parity (S4)         | one record through each of 3 plane writers       | per-plane written bytes identical before/after                                       | `tests/src/core/telemetry/test_jsonl_io.py` (new)                    |
| search read `OSError` -- 4 stores | each store; patched `open()` -> `OSError`        | raises the store's `*UnreadableError`, not `*CorruptedError`                         | `tests/regression/test_bug_search_store_oserror_unreadable.py` (new) |
| search clean/read routing (S5)    | `forge search clean` over an unreadable store    | routed as check/retry (unreadable), not reset/corrupt                                | `tests/src/cli/test_search.py` (extend)                              |

Existing homes confirmed: `tests/src/core/state/{test_io,test_timestamps,test_exceptions}.py` exist; regression
precedent `tests/regression/test_bug_state_unreadable_not_deleted.py` (PR #50 family).

## Blockers / deferred decisions

- **[Phase 2] RESOLVED:** delete the dead exported `prune_usage_events`; do **not** wire retention (telemetry
  accumulates indefinitely by design, appendix §A.9). Any real usage-events retention is a separate design card.
- **[Phase 5] RESOLVED:** four domain-specific Unreadable subclasses under `StateUnreadableError`
  (`SearchDocumentStore`/`BM25Index`/`ContentStore`/`IndexState`), not bare `StateUnreadableError`.
- **[Phases 4-5] Re-verify gate.** Both rest on first-pass audit evidence; re-confirm the per-site triplication (S4) and
  the read-skeleton claim (S5) before extracting. (S5's `OSError->Corrupted` divergence is already re-verified.)
- **[Structure]** Running as one `doing/` card with a phased checklist (card's old "When accepted" note now marked
  superseded). Reversible: any slice can spin out to its own card if it needs independent sequencing.

## Doc sync (per board_contract Design Doc Sync)

- **impl_notes** "One pruner for all JSONL planes" names `proxy/retention.py::prune_jsonl_shards` as the canonical home;
  update that note's path after Slice 2 moves it to `core/state/retention.py`.
- These are internal primitive moves with **no** user-facing or ownership-model change, so `design.md`/`design_appendix`
  are expected untouched. Confirm at closeout; if a `core/state` leaf becomes a documented ownership boundary, add the
  breadcrumb.

## Closeout

- [x] Add a compact `docs/board/change_log.md` entry with Goal / Key changes / Verification.
- [x] Confirm the metric predictions: targeted fsync tests cover all 5 ex-copy paths;
  `rg -l 'from forge\.proxy\.retention' src/forge/core` empty; `rg 'def _?now_iso' src/forge` -> 1;
  `rg -n 'prune_usage_events' src/forge tests` empty.
- [x] Promote durable lessons to `impl_notes.md` **after human review** (e.g. the corrected now_iso set; the
  text-vs-bytes atomic-write split; the search-store Unreadable convergence).
- [x] `make pre-commit` clean; focused suites + the relevant integration path green.
- [x] Move `doing/state_primitive_hoist/` -> `done/` after the final slice merges to `main`.
