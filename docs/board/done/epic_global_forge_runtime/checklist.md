# Epic coordination checklist: Global Forge Runtime

Coordination only -- sequencing, shared-contract drift control, and cross-member decisions. It does **not** replace
member execution checklists (each member owns its own). Full contract in [`card.md`](card.md).

## Current focus

Closeout completed 2026-07-13. All nine live implementation members -- T1 and T3--T10 -- shipped and are in `done/`. T2
[`forge_hook_absolute_command`](../../retired/forge_hook_absolute_command/card.md) never shipped independently and is
now terminal in `retired/`: T5 folded its host-hook migration groundwork, T10 owns the sidecar contract, and the
remaining GUI `statusLine` question is the standalone
[`statusline_gui_reachability`](../../proposed/statusline_gui_reachability/card.md) proposal. The split T7 mutator sweep
also shipped as a standalone non-member follow-up. The seam audit, durable-doc sync, inbound-link sweep, and lane move
below are the final coordinator record.

## Activation bookkeeping (this branch)

- [x] Epic moved `proposed/ -> doing/` (`git mv`).
- [x] First member T1 `global_forge_install` moved `proposed/ -> doing/` (`git mv`); branch `global-forge-install`
  created from `main`.
- [x] Link maintenance for the lane move (board_contract: each member links the epic at its current board path):
  - Epic forward-links: the 8 still-`proposed/` members repointed to `../../proposed/...`; T1 (sibling) and T9 (done)
    preserved.
  - Member back-links: 9 repointed (8 proposed -> `../../doing/...`; T1 sibling -> `../`).
  - Inbound refs repointed in `done/forge_hook_legacy_writer` (T9), `done/forge_hook_matcher_consolidation` (prep), and
    `doing/cross_runtime_skills`.
  - Verified: link-resolver sweep reports **0** move-related broken relative links. (7 unrelated pre-existing broken
    board links were left untouched -- candidate for a separate board-hygiene pass, not this branch.)
- [x] T1 checklist reviewed; execution complete on branch `global-forge-install` (Phases 0--3 shipped + verified;
  `make pre-commit` clean, 14 new doctor tests + 2586 touched-suite tests pass). Lane move `doing/ -> done/` deferred to
  post-merge. doctor's minimal-PATH probe now provides the D2 evidence (recorded below).

## Decisions owed (coordination -- none block T1)

Record outcomes here as members are picked up.

- [x] **D2 timing and terminal disposition -- RESOLVED 2026-07-13: SKIP AND RETIRE T2.** The owner confirmed
  terminal-only launch on 2026-07-06, so the interim absolute-command transition was unnecessary. T2 never changed
  registered bytes. T5 later performed the one shipped host transition, from direct hooks to the literal absolute
  dispatcher command, folding T2's unmerge-before-merge groundwork; T10 implemented the separate sidecar contract.
  `forge extension doctor`'s `on_path_minimal` result remains useful for bare consumers, but it does not diagnose the
  absolute host dispatcher. The deliberately bare, project-scoped `forge status-line` residual is tracked by
  [`statusline_gui_reachability`](../../proposed/statusline_gui_reachability/card.md). T2 moved to `retired/` as
  superseded/reference-only; any reconsideration starts from the successor proposal rather than reviving T2.
- [x] **T4 benchmark (owner T4) -- RESOLVED 2026-07-08:** stdlib dispatcher shim (`forge-hook`, hyphen) wins.
  Populated-registry benchmark (40 enrolled roots, cwd depth 5, 50 cold subprocess runs) measured shim **p50 20.21 ms /
  p95 22.13 ms** under the p95 \<= 30 ms ceiling; full Forge gate representative measured **p50 419.66 ms / p95 611.78
  ms**. T5 consequently updated presence detection for the hyphenated command; no derived enrollment cache was needed.
- [x] **T3 trust model (owner T3) -- RESOLVED 2026-07-07:** enroll-on-enable + auto-enroll-on-managed-worktree, keeping
  `enrollment_source` provenance. Explicit-only rejected -- `extension enable` is itself the consent and a managed
  worktree/fork is derived consent, so explicit-only adds friction without a safety property (the dangerous design,
  enroll-on-*detection*, was never proposed) while creating the unenrolled-managed-session failure mode. Detail in the
  T3 checklist Phase 0.
- [x] **T3 file format (owner T3) -- RESOLVED 2026-07-07 (D-T3-c):** `~/.forge/projects.json` (machine-written JSON,
  house pattern; reuses the versioned-JSON helpers; dissolves T4's TOML-parse-in-shim tension), not `.toml`. Seam 2
  amended. Detail in the T3 checklist Phase 0.
- [x] Next member after T1: **T3 `forge_project_registry`** (critical path) + **T7 `forge_project_compat`** (off-path
  companion), picked up together 2026-07-06; both `git mv` `proposed/ -> doing/` on branch `forge-project-registry`,
  epic/member links repointed, execution checklists added. T3 Phase 1--3 implementation and T7's first command-path
  guard slice landed 2026-07-07 in PR #90; both member cards are now `done/`. T7's broader mutator sweep was split to
  the standalone [`forge_project_compat_mutator_sweep`](../../done/forge_project_compat_mutator_sweep/card.md), which
  later shipped via PR #98.
- [x] Next member after T3/T7: **T4 `forge_hook_dispatcher`** (critical path), picked up 2026-07-07; `git mv`
  `proposed/ -> doing/` on branch `forge-hook-dispatcher`, epic forward-link + member back-link repointed, execution
  checklist added. Shipped the dispatcher mechanism + resolver + no-op gate + metadata home; Phase 0 resolved the
  shim-vs-symlink benchmark above. Moved `doing/ -> done/` after the PR merged.
- [x] Next member after T4: **T5 `user_scope_hook_ownership`** (critical path), picked up 2026-07-08; `git mv`
  `proposed/ -> doing/` on branch `user-scope-hook-ownership`, epic forward-link + member back-link + the
  `done/forge_hook_matcher_consolidation` inbound link repointed, execution checklist added. Ships the user-scope-only
  registration flip, the hook command-byte cutover to the dispatcher form (unmerge-before-merge), the presence-detection
  update (the hyphenated `forge-hook` needle), and cross-scope double-fire detection, gated at the effective-module
  layer so tracking/status/JSON stay truthful across both normal enable and sync/update overrides. Sidecar stays
  **T10**-owned (T5 lands only an exposure gate / documented interim-gap guard); the unmerge-before-merge groundwork
  from skipped T2 folds into T5. Checklist reviewed 2026-07-08; Phase 0 decisions resolved (enable UX keeps
  `--scope user`; sidecar -> T10 with exposure gate; additive detection; explicit project/local hook overrides
  hard-reject). Moved `doing/ -> done/` after PR #93 merged.
- [x] Next member after T5: **T10 `forge_hook_sidecar_resolution`** (seam 5), picked up 2026-07-08; `git mv`
  `proposed/ -> doing/` on branch `forge-hook-sidecar-resolution`, epic forward-link + member back-link repointed, and
  execution checklist added. Phase 0 reframes the card around the shipped T5 world: T2 was skipped, so the live
  regression is a hookless sidecar plus sidecar-specific PATH/settings persistence effects, not host-absolute project
  hook bytes. Implementation verified 2026-07-09: canonical settings stage at `.forge/sidecar-home`, the entrypoint
  merges auth idempotently, bare `forge hook` resolves via image PATH, pending work is host-drainable, and the interim
  warning is retired. PR #94 merged 2026-07-10; moved `doing/ -> done/` in the separate post-merge closeout commit.
- [x] Next member after T10: **T6 `forge_hook_migration_cleanup`** (end of the critical path), picked up 2026-07-10;
  branch `forge-hook-migration-cleanup` created from `main`, card moved `proposed/ -> doing/`, epic forward-link
  repointed, and a code-grounded checklist added. D1–D6 were approved after follow-up review. Implementation is
  review-ready: tracked/frozen-shape Claude cleanup, Codex marker migration, user-only runtime transition, explicit
  preview/`--yes`, independent doctor/status-line cleanup state, and final selected-root `backfill` enrollment are all
  verified. PR #96 merged 2026-07-11; the card moved `doing/ -> done/`, all inbound links were repointed, and the epic
  briefly had no active member. (T8 was parked pending a separate activation decision at that point; it was activated
  later the same day -- see the T8 bullet below.)
  - **Member seam 1 evidence:** frozen released direct-hook shapes require exact event/matcher/timeout/wrapper identity;
    current dispatcher entries keep full canonical-entry dedupe, and ambiguous bytes stay report-only.
  - **Member seam 2 evidence:** candidate discovery uses `TrackingStore.list_installations()` without registry access;
    explicit cleanup reuses strict `ProjectRegistryStore.enroll(..., "backfill")` only after the clean/user transition.
  - **Member seam 4 evidence:** project/local runtime ownership is removed and reconciled without touching statusLine;
    final scans require user scope to be the only Forge runtime source. The epic seam boxes were retained unchecked
    until this closeout.
- [x] Next member after T6: **T8 `forge_dev_runtime_override`** (last live member, off-path), picked up 2026-07-11;
  branch `forge-dev-runtime-override` created from `main`, card `git mv` `proposed/ -> doing/`, epic forward-link +
  member back-link + the `proposed/statusline_gui_reachability` inbound link repointed, execution checklist added. Phase
  0 decisions D1-D6 were ratified in maintainer review the same day (two rounds; the core fork resolved to the
  `FORGE_DEV` env override with a deterministic recording transition table -- record in the member checklist). In the
  second round the split T7 sweep was reclassified a standalone non-member follow-up, so T8 IS the last live member:
  when it closes, the epic closeout items (seam boxes, design-doc verification, lane move) become actionable. Phases 1-2
  shipped via PR #97 (`46ff9ef6`) with the public docs/vocabulary, focused, integration, package, live-smoke, and
  pre-commit checks verified. The card moved `doing/ -> done/` in the post-merge closeout; the separate epic closeout is
  recorded below.

## Shared-contract seams (drift watch)

Each seam is honored **per-member** (seam 1 bound T5/T6, while retired T2 preserved its earlier planning record), so a
single mid-epic checkbox was ambiguous. These boxes tick at **epic closeout**; interim per-member verification lives in
the member checklists. The final focused hook/runtime audit passed **285 tests with 1 platform skip**, and the required
merged-main Docker installer suite passed **17 tests**. The closeout's doctor/dispatcher wording corrections passed
their focused **86-test** suite.

- [x] Seam 1 -- all registered command strings + shared matcher (byte-identity is the API; unmerge-before-merge).
- [x] Seam 2 -- `~/.forge/projects.json` schema (JSON, D-T3-c) + one canonicalization rule.
- [x] Seam 3 -- Forge-binary resolution contract (+ `FORGE_SESSION` / managed-session short-circuit).
- [x] Seam 4 -- runtime hooks live only at user scope (statusLine is the D3 exception -- stays project-scoped).
- [x] Seam 5 -- host vs sidecar execution (verified by T10 staging/image-PATH/deferred-queue coverage).

## Accepted decisions (reference; detail in card.md)

- **D1** -- version coupling accepted (one global binary, one version; T7 is a fail-clear guardrail, not a version
  manager).
- **D2** -- the interim T2 rewrite was skipped and retired; the dispatcher-backed user-scope cutover is the only shipped
  host hook-byte migration.
- **D3** -- statusLine stays project-scoped (scalar, cannot double-fire); the user-scope rule covers hooks only.

## Closeout (epic)

- [x] Every live member card is `done/`; retired T2 is excluded from the live/shipped count with its outcome recorded.
- [x] design.md / design_appendix §C / cli_reference reflect the shipped install + hook-ownership model.
- [x] Repointed every inbound board link that targeted the epic's former `doing/` path, including done-member back-links
  and standalone follow-ups such as [`statusline_gui_reachability`](../../proposed/statusline_gui_reachability/card.md)
  and [`forge_project_compat_mutator_sweep`](../../done/forge_project_compat_mutator_sweep/card.md) (non-member; its
  Origin line links this epic).
- [x] Epic moved `doing/ -> done/`; `change_log.md` entry added; durable lessons promoted to `impl_notes.md` after human
  review.
