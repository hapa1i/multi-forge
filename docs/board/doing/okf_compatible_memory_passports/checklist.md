# Checklist: OKF-compatible memory passports

Execution plan for [card.md](card.md) on branch `okf-compatible-memory-passports`. The card's
[Acceptance Tests table](card.md#acceptance-tests) is the acceptance authority; each phase below names the rows it
lands. Code seams verified against `main` before planning: `extract_frontmatter` returns `(None, full_text)` for a
delimited non-mapping YAML root (`src/forge/session/passport.py:261-262`), `write_passport` then prepends a second
frontmatter block (`passport.py:503-507`), and `scan_passported_docs` already warn-skips `PassportError` per file
(`src/forge/session/project_memory.py:177-179`).

## Current focus

Phase 0 — regression pins on current behavior, before any production change.

## Phase 0: Regression pins (no behavior change)

Write the card's "Existing regression" rows first; all must pass against unmodified code.

- [ ] Passport-only doc (no OKF fields) is scanned as a memory doc — `scan_passported_docs` returns it
  (`tests/src/session/test_project_memory.py`)
- [ ] OKF-only doc (`type`, no `forge_memory`) is not a memory doc — scanner skips it
  (`tests/src/session/test_project_memory.py`)
- [ ] `docs/index.md` carrying OKF bundle metadata without `forge_memory` is ignored by the scanner
  (`tests/src/session/test_project_memory.py`)
- [ ] `forge_memory` strictness is unaffected by valid OKF outer fields: bad `update.mode` still raises the existing
  `PassportError` (`tests/src/session/test_passport.py`)
- [ ] Value-level preservation pinned as the contract: a custom outer key round-trips through `write_passport`; a test
  documents that comments and scalar spelling are NOT preserved (`tests/src/session/test_passport.py`)

## Phase 1: Non-mapping frontmatter fails clear (pre-existing write bug)

- [ ] `extract_frontmatter` raises `PassportError` for a delimited non-mapping YAML root (list/scalar) instead of
  returning `(None, full_text)` (`src/forge/session/passport.py:261-262`); absent frontmatter and empty frontmatter stay
  valid
- [ ] `write_passport` / `forge memory track` on such a file fail without modifying it: file byte-identical, no second
  frontmatter block, exit non-zero with a clear error (`tests/src/session/test_passport.py`,
  `tests/src/cli/test_memory.py`)
- [ ] Scanner posture pinned: `scan_passported_docs` over a tree containing a non-mapping-root file warn-skips via the
  existing per-file `except PassportError` — no crash (`tests/src/session/test_project_memory.py`)
- [ ] Regression file per testing-guidelines mandate (corruption-class bug):
  `tests/regression/test_bug_okf_nonmapping_frontmatter_double_block.py` reproduces the double-block corruption on the
  old behavior shape and asserts byte-identical failure now

**Decision to confirm at review**: raising in the shared parser changes the scan path for third-party non-mapping-root
files from silent-ignore to warn+skip (one `logger.warning` per scan per file). Card wording ("shared parser/write
path") supports this; the alternative — raise only on the write path, keep reads returning `None` — avoids the warning
noise but forks the parser contract. Planned: raise in the parser, accept the warning.

## Phase 2: OKF envelope builder (`passport.py`)

- [ ] New builder adds only missing `type` / `title` / `description` / `tags`; never overwrites an existing value; never
  emits `timestamp`
- [ ] Derivations: `title` from the first `# ` heading, else filename; `description` from `forge_memory.intent`; `tags`
  = `[forge, memory, <strategy>]`; generated `type` is `Memory Document`
- [ ] Reserved basenames `index.md` / `log.md` are rejected with an actionable error before any write; file untouched
- [ ] Unit coverage for all three assertions (`tests/src/session/test_passport.py`)

## Phase 3: `forge memory track` emits the envelope on passport creation only

- [ ] Newly tracked doc gains non-empty `type` plus recommended fields alongside `forge_memory`; `timestamp` absent
  (`tests/src/session/test_passport.py`)
- [ ] Re-track no-op preserved: unchanged `--strategy`/`--writers` on an existing passport writes nothing and does not
  implicitly upgrade outer metadata (`tests/src/cli/test_memory.py`)
- [ ] `--propose`: the official doc gets the envelope at passport creation; materialized shadow files under
  `.forge/memory/` get no envelope (`tests/src/cli/test_memory.py`)
- [ ] `remove_passport` still deletes only `forge_memory`; generated OKF fields survive as producer-owned metadata
  (`tests/src/session/test_passport.py`)

## Phase 4: `forge memory passport upgrade <path>` CLI leaf

- [ ] New leaf under the `forge memory passport` group: adds only missing OKF fields to an existing passport; idempotent
  — second invocation is byte-identical (`tests/src/cli/test_memory.py`)
- [ ] Fails clear, file untouched, on: doc without a passport, reserved basenames, non-mapping frontmatter root
  (`tests/src/cli/test_memory.py`)
- [ ] Recovery output through `forge.cli.output` helpers; help text and group examples follow
  `docs/developer/cli_style_guidelines.md`

## Phase 5: Docs and design sync

- [ ] `docs/design_workflows.md` §5.2 and §6.2 passport examples show the OKF envelope; state the value-level
  preservation contract and the timestamp deferral
- [ ] `docs/cli_reference.md` memory-management section adds `forge memory passport upgrade`
- [ ] `docs/end-user/memory.md` reflects the new track output shape and the upgrade command
- [ ] Card "Risks / Open Questions" updated with the decisions taken (parser posture, value-level contract)

## Deferred decisions (from card, unchanged)

- `timestamp` generation — blocked on a last-meaningful-change ownership design; Phase 1 never emits it.
- Bundle conformance (`index.md`/`log.md` maintenance, bundle-wide validation) — separate feature, out of scope.
- Comment/byte-level preservation — would require a ruamel round-trip representation; value-level is the pinned contract
  for this card.
- OKF is draft v0.1 — integration stays shallow; spec pinned at upstream commit `ee67a5ca` (card References).

## Closeout

- [ ] All rows in the card's [Acceptance Tests table](card.md#acceptance-tests) implemented and green
- [ ] `make test-unit` clean; targeted integration for the memory scan/writer path
  (`./scripts/test-integration.sh tests/integration/` memory/session files touching passport scan), since the scanner
  feeds the memory writer
- [ ] `make pre-commit` clean
- [ ] Compact entry in `docs/board/change_log.md`; durable lessons proposed for `impl_notes.md` via shadow review
- [ ] Design/end-user docs verified against shipped behavior; card moved `doing/` -> `done/`; inbound links repointed
