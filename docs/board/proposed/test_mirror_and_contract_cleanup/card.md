# test_mirror_and_contract_cleanup -- restore the test-mirror, fixture, output-helper, and shared-seam contracts

**Lane**: `proposed/` -- accepted-candidate refactor batch, not yet scheduled. Mostly behavior-preserving structural
corrections to test layout and contract boundaries, plus **one defect-fix slice** (Slice 5, transcript alias
normalization). Independently shippable slices.

**When accepted**: this is a batch of independent contract fixes, not one seam. Per `docs/developer/board_contract.md`
(epics coordinate independently shippable members), promote it as **separate member cards per slice** -- or an
`epic_test_contracts` coordinator if they need shared sequencing -- rather than moving the whole batch to `doing/` at
once.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; cross-cutting contract
sweeper + areas cli-session, review-search-sidecar-skills). The subpackage-mirror gaps and the back-compat shim were
adversarially verified (SURVIVES); the monkeypatch clustering, Codex `HeadlessResult` factory copies, and the
transcript-primitive divergence are auditor first-pass evidence.

**Type**: **refactor batch card**, deliberately **not an epic** as drafted. Items share the theme "structural contract
violation," not one contract; each is independently shippable (see When accepted).

**References**: `docs/developer/testing_guidelines.md` (1:1 test mirroring; 3+ identical monkeypatches -> shared
fixture); `docs/developer/coding_standards.md` §5 (internal clean-break -- delete shims, update callers atomically);
`CLAUDE.md` (recovery output only via `forge.cli.output`; test-enforced); `docs/design.md` §3.5;
`docs/board/impl_notes.md` (memory/transfer vocabulary -- `core/transcript.py` as the documented dual-format seam);
PR #77 (`08e4a787`, the session-test split -- see item 1).

---

## Why (the thesis)

Six live structural contracts the repo enforces elsewhere have local violations (a seventh -- the 4933-line session-test
monolith -- was **resolved by PR #77**, retained below as context so the next audit does not re-flag it). Most are
behavior-preserving; the transcript-parser convergence (item 7 / Slice 5) also fixes an observable defect and so carries
a mandatory regression test.

1. **(Resolved by PR #77 -- context, no action.)** The 4933-line `tests/src/cli/test_session_commands.py` monolith was
   split in `08e4a787` into 15 focused files (`test_session_fork.py`, `test_session_resume.py`,
   `test_session_start_delete.py`, ...) plus a shared `session_command_support.py` (`successful_claude_launch()`). #77
   split by **behavior**, not strict source-mirror (there is no `test_session_lifecycle.py`), which resolves the monolith
   concern; re-splitting to a strict source mirror would only churn #77's fresh work. Retained so the next audit does not
   re-flag it.
2. **Two source subpackages have no mirrored test directory.** `cli/statusline/` (5 modules) and `session/claude/` (4
   modules) are tested by flat files in the parent test dir (`tests/src/cli/test_statusline_registry.py`,
   `tests/src/session/test_claude_paths.py`) instead of `tests/src/cli/statusline/` and `tests/src/session/claude/`.
   (Unaffected by #77 -- its new files are all flat in `tests/src/cli/`.)
3. **Monkeypatch clustering above the documented 3+ threshold with no shared fixture.** A credential stub + proxy-server
   stubs are patched identically across `tests/src/proxy/test_passthrough.py:212`,
   `test_responses_transport.py:549`, `tests/src/review/test_models.py:273`, `tests/src/policy/team/test_handlers.py:372`,
   `tests/src/session/test_memory_writer.py:735` while `tests/src/proxy/conftest.py:136` (`server_stubs`) lacks them.
4. **Recovery `Tip:` lines hand-rolled below the output-helper floor.** `review/routing.py:336,360` build recovery hints
   in exception messages instead of via `forge.cli.output` (the CLAUDE.md-enforced surface); `cli/workflow.py:193` is the
   render site.
5. **A back-compat re-export shim on an internal surface.** `sidecar/secrets.py:8` re-exports for compatibility;
   `coding_standards.md` §5 says internal surfaces take a clean break (delete + repoint callers atomically), not a shim.
6. **Codex `HeadlessResult` test factory copied across three consumer suites.** `tests/src/policy/semantic/test_supervisor.py:55`,
   `tests/src/session/test_shadow_curation.py:626`, and `tests/src/session/test_memory_writer.py:1791` each define a
   near-identical `_codex_result(**overrides)` helper for `CodexHeadlessInvoker.run` results. The only meaningful
   differences are call-site labels/comments and stdout defaults; a future `HeadlessResult` field change would require a
   three-file test update.
7. **Transcript-entry primitives re-implemented divergently while `core/transcript.py` is the documented seam.**
   `session/transfer.py:257-309` owns `_normalize_transcript_role` / `_resolve_entry_role` / `_extract_entry_blocks` /
   `_group_entries_into_turns`; `cli/status_line.py:410-421` has a **divergent** local `_resolve_entry_role` (no
   `human`/`ai` alias normalization -- Surfaced Defect); `session/rewind.py:17-19` imports transfer's private
   `_`-named helpers. `core/transcript.py:1-9` documents itself as the shared home for "low-level parsing of Claude Code
   transcript files."

Plus two placement smells: the byte-identical `_find_git_root` walkers (`cli/extensions.py:47`, `core/ops/context.py:65`,
`cli/codex.py:131`, `session/claude/paths.py:181`) and the `direct_model` env-pin helper living in the session domain
while serving review/ops/CLI.

---

## Non-goals / must-not-break

- **No behavior change on Slices 1-4, 6.** Tests assert the same things after moving; helpers return the same values.
  **Slice 5 is a deliberate defect-fix** (alias normalization) -- it changes an observable and ships with a regression
  test, not framed as behavior-preserving.
- **Do not re-split the #77 session tests.** #77's behavior-based split resolved the monolith; a strict source-mirror
  rename is churn, not a contract fix.
- **Delete-and-repoint atomically** (coding_standards §5): the `sidecar/secrets.py` shim removal updates
  `sidecar/__init__.py:17` and both tests in the same commit -- no tombstone.
- **Preserve the deliberate divergence where it is intentional.** The `status_line` transcript parser converges to
  `core/transcript.py` semantics (the alias gap is a bug to fix) -- but its lazy `RenderContext` I/O discipline
  (impl_notes statusline) stays.
- **Slice 3 stays test-support only** -- share the `HeadlessResult` construction, never unify the three Codex consumer
  contracts (they intentionally differ, impl_notes T6b/T6c).
- **Do not re-flag the state-script copies** (`walkthrough`/`qa` `walkthrough-state.py`) -- documented independent
  (testing_guidelines).

---

## Target shape

| Contract | Target | Current violation |
| --- | --- | --- |
| Session-test monolith | session monolith split -- **done in #77** (behavior-based) | -- (resolved) |
| Test subpackage mirror | `tests/src/cli/statusline/`, `tests/src/session/claude/` | flat files in parent dir |
| 3+ monkeypatch -> fixture | credential/server stub in `tests/src/proxy/conftest.py` | 5 identical inline patches |
| Codex `HeadlessResult` test factory | one shared test helper | 3 `_codex_result(**overrides)` copies |
| Recovery output via `forge.cli.output` | `print_error_with_tip` / `handle_session_error` | review/routing.py:336,360 hand-rolled `Tip:` |
| No internal back-compat shim | delete `sidecar/secrets.py`, repoint `__init__.py:17` + tests | re-export shim |
| Transcript parsing in `core/transcript.py` | move the 4 helpers; converge status_line + rewind onto it | 3 divergent/private copies |
| Git-root walker | one home (a `core/paths` leaf) | 4 copies |

---

## Phased plan (each slice independently landable; each promotable to its own member card)

| Slice | Scope | Kind | Exit signal |
| --- | --- | --- | --- |
| 1 | Move `cli/statusline/` + `session/claude/` tests into mirrored dirs (`tests/src/cli/statusline/`, `tests/src/session/claude/`). Tests moved, never skipped. (Session monolith already done in #77.) | refactor | mirror-check (source -> test path) clean for the two subpackage areas |
| 2 | Extract the credential/server stubs into `tests/src/proxy/conftest.py`; repoint the 5 inline patches. | refactor | `rg 'monkeypatch'` cluster gone; one fixture |
| 3 | Add a shared Codex `HeadlessResult` test factory; repoint supervisor, shadow-curation, and memory-writer tests. | refactor | one helper builds Codex headless results; per-consumer tests keep only behavior-specific stdout/label values |
| 4 | Route `review/routing.py` recovery hints through `forge.cli.output`; delete the `sidecar/secrets.py` shim + repoint. | refactor | `test_cli_rich_tips_go_through_output_helpers` scope satisfied; no re-export shim |
| 5 | Move the 4 transcript helpers to `core/transcript.py`; converge `status_line` + `rewind` onto it (**fixes the alias gap**). | **defect-fix** | one transcript parser; **regression test for the `human`/`ai` alias normalization** is required to tick this slice |
| 6 | One git-root walker leaf; relocate `direct_model` helper if a neutral home is warranted. | refactor | `rg 'def _find_git_root\|_detect_git_project_root'` -> one home |

## Blast radius

- **Test moves are the safest churn** (moving tests, not code). Slice 1 must *move*, never skip (testing_guidelines). The
  larger session-monolith split already landed in #77, so this card's Slice 1 is the smaller subpackage-mirror move.
- Slice 3 is test-only but touches three hot consumer suites; keep the helper in test support code and do not move
  production `HeadlessResult` adaptation behavior.
- Slice 5 touches `status_line.py` (lazy-I/O sensitive) and `rewind.py` (durable-resume) -- converge carefully; rewind
  imports transfer's privates today, so making them public in `core/transcript.py` is the enabling move.
- `sidecar/secrets.py` removal: 2 test importers + `__init__.py`; integration test `test_auth_secrets_propagation.py`.

## What was verified vs. first-pass

- **Adversarially verified SURVIVES:** subpackage mirror gaps ([57]); back-compat shim ([60]). The test-monolith split
  ([20]) was independently **confirmed by PR #77 shipping it**.
- **First-pass (Medium):** monkeypatch clustering ([56]); Codex `HeadlessResult` factory copies; transcript-primitive
  divergence ([70]); `Tip:` hand-roll ([63]); git-root walkers ([29]).

## Adversarial verification (survived where run)

The test-monolith was not adjudicated deliberate -- PR #77 shipped exactly the split this audit proposed, the strongest
possible confirmation. The `sidecar/secrets.py` shim is an internal surface, so §5 clean-break applies (no deprecation
period owed).

## Risks

- **Skipping is forbidden** (testing_guidelines) -- Slice 1 moves tests, it never disables them.
- **Slice 5 is a defect-fix, not a pure move** -- the alias-normalization convergence changes an observable and must ship
  with a regression test; do not wave it through as behavior-preserving.
- **Slice 3 must stay test-support only** -- sharing the factory must not tempt a production unification of the three
  Codex consumer contracts, which intentionally differ.
- Low overall risk; sequence Slice 1 after any in-flight session-test edits to avoid rebase churn (lanes are empty
  today).

## Metric / falsifiable prediction

Prediction: a change to one session command touches its focused test file (post-#77), not a monolith; a new proxy test
reuses the fixture instead of a 6th inline stub; a `HeadlessResult` field addition updates one test factory; a
transcript-format change touches `core/transcript.py` once. Confirm on the next session-command PR and the next
transcript-parsing PR.

## Acceptance (per-slice)

Tick only when: (a) a source->test mirror-path check is clean for the scoped area; (b) tests were moved, not skipped; (c)
the output-helper enforcement tests pass; (d) Slice 3 keeps consumer-specific assertions local while sharing only the
`HeadlessResult` construction; (e) **Slice 5 carries the alias-normalization regression test** (defect-fix gate).

## Closeout

(pending)
