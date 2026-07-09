# Epic coordination checklist: Global Forge Runtime

Coordination only -- sequencing, shared-contract drift control, and cross-member decisions. It does **not** replace
member execution checklists (each member owns its own). Full contract in [`card.md`](card.md).

## Current focus

**T5 closeout complete after PR #93 merged.** Shipped members now are T1
[`global_forge_install`](../../done/global_forge_install/card.md), T3
[`forge_project_registry`](../../done/forge_project_registry/card.md), T4
[`forge_hook_dispatcher`](../../done/forge_hook_dispatcher/card.md), T5
[`user_scope_hook_ownership`](../../done/user_scope_hook_ownership/card.md), and T7
[`forge_project_compat`](../../done/forge_project_compat/card.md). T5 flipped hook registration to user-scope-only, cut
hook command bytes over to the hyphenated dispatcher form (unmerge-before-merge), updated presence detection, and added
double-fire detection. Next cursor: **T10** sidecar resolution and **T6** migration cleanup; **T8** remains the
dev-runtime override. T7's remaining mutator-family sweep is parked in
[`forge_project_compat_mutator_sweep`](../../todo/forge_project_compat_mutator_sweep/card.md). Adjacent non-member
`env_var_interface_boundary` also landed via PR #91; T4 authored against it, and T5/T6 should continue to author new
user-facing strings against the shipped env-var vocabulary boundary.

## Activation bookkeeping (this branch)

- [x] Epic moved `proposed/ -> doing/` (`git mv`).
- [x] First member T1 `global_forge_install` moved `proposed/ -> doing/` (`git mv`); branch `global-forge-install`
  created from `main`.
- [x] Link maintenance for the lane move (board_contract: each member links the epic at its current board path):
  - Epic forward-links: the 8 still-`proposed/` members repointed to `../../proposed/...`; T1 (sibling) and T9 (done)
    preserved.
  - Member back-links: 9 repointed (8 proposed -> `../../doing/...`; T1 sibling -> `../`).
  - Inbound refs repointed in `done/forge_hook_legacy_writer` (T9), `done/forge_hook_matcher_consolidation` (prep), and
    `proposed/cross_runtime_skills`.
  - Verified: link-resolver sweep reports **0** move-related broken relative links. (7 unrelated pre-existing broken
    board links were left untouched -- candidate for a separate board-hygiene pass, not this branch.)
- [x] T1 checklist reviewed; execution complete on branch `global-forge-install` (Phases 0--3 shipped + verified;
  `make pre-commit` clean, 14 new doctor tests + 2586 touched-suite tests pass). Lane move `doing/ -> done/` deferred to
  post-merge. doctor's minimal-PATH probe now provides the D2 evidence (recorded below).

## Decisions owed (coordination -- none block T1)

Record outcomes here as members are picked up.

- [x] **D2 timing (owner T2) -- RESOLVED 2026-07-06: SKIP T2.** Epic owner confirmed terminal-only launch; resolution in
  the Decision bullet at the end of this block. Rationale kept for the record: after T1, ship the interim absolute-path
  fix `forge_hook_absolute_command` (T2), or jump straight to the user-scope model (T3 -> T4 -> T5 -> T6)? Cost weighs
  against T2: it re-runs the epic's riskiest maneuver (registered-byte changes under append+dedupe merge, the statusLine
  scalar conflict-abort path, a paired T10 sidecar exemption, one Codex re-trust) -- the same seams T5 must touch -- to
  produce bytes T5 deletes and a second re-trust supersedes. T2's only residual value after T1 is a hook subprocess on a
  minimal PATH that lacks `~/.local/bin`.
  - **Criterion (decide via T1 doctor evidence):** skip T2 unless, post-T1, `forge` is unreachable in a launch
    environment actually in use -- probed mechanically by doctor's minimal-PATH check
    (`PATH=/usr/bin:/bin:/usr/sbin:/sbin`, the GUI/launchd case that excludes `~/.local/bin`). Terminal-launched Claude
    inherits the shell PATH (has `forge`); GUI-launched (Dock/IDE) inherits launchd's minimal PATH (may not).
    Terminal-only usage -> **skip, next member is T3**. Even the unreachable case has a "launch from a terminal"
    workaround the original exit-127 incident never had.
  - **Consequence if skipped (record, don't orphan silently):** T2 is the *only* member that rewrites `statusLine` to an
    absolute path (D3 keeps it project-scoped; T5 covers hooks only), so skipping T2 leaves `forge status-line` bare
    permanently. Likely fine -- it self-gates on `FORGE_SESSION` and Claude tolerates a failing statusLine gracefully
    (the same facts D3 leaned on) -- but recorded as a consequence, not a silent orphan.
  - **T2-card disposition if skipped:** fold T2's groundwork (unmerge-before-merge on the ~16 hook entries; the paired
    T10 sidecar exemption) into T5, don't abandon the card.
  - **T1 doctor evidence (gathered):** `forge extension doctor` reports `on_path_minimal=false` on the editable dev
    install, and by construction it is also `false` for a global `~/.local/bin` install (launchd's minimal PATH excludes
    `~/.local/bin`). So the GUI/launchd reachability gap is **mechanically real even after T1** -- a global install does
    not by itself put `forge` on a Dock/IDE-launched hook's PATH. The decision now reduces to the *usage* question the
    criterion names: is a GUI/Dock launch actually in use, or is launch terminal-only (which inherits the shell PATH and
    resolves `forge`)?
  - **Decision (2026-07-06): SKIP T2 -- epic owner confirmed terminal-only launch.** Claude is launched from a terminal,
    which inherits the shell PATH and already resolves `forge`, so the minimal-PATH hook reachability gap (T2's only
    residual value after T1) does not apply. Next members: **T3** (critical path) + **T7** (off-path guardrail), picked
    up together. **Recorded consequences:** (a) `forge status-line` stays bare permanently -- T2 was its only
    absolute-path rewriter, D3 keeps it project-scoped, and it self-gates on `FORGE_SESSION` (acceptable); (b) **T2-card
    disposition** -- fold its unmerge-before-merge groundwork into T5, while the paired sidecar exemption is implemented
    by T10 and release-gated by T5; the T2 card stays in `proposed/` as superseded-not-abandoned. Reopen only if a
    GUI/Dock/IDE launch becomes a supported path.
- [x] **T4 benchmark (owner T4) -- RESOLVED 2026-07-08:** stdlib dispatcher shim (`forge-hook`, hyphen) wins.
  Populated-registry benchmark (40 enrolled roots, cwd depth 5, 50 cold subprocess runs) measured shim **p50 20.21 ms /
  p95 22.13 ms** under the p95 \<= 30 ms ceiling; full Forge gate representative measured **p50 419.66 ms / p95 611.78
  ms**. Consequences: T5 must update presence detection because the current `has_forge_hook` needle is `"forge hook"`
  with a space; no derived enrollment cache is needed.
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
  `todo/forge_project_compat_mutator_sweep/`.
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
  hook bytes.

## Shared-contract seams (drift watch)

Each seam is honored **per-member** (seam 1 alone binds T2/T5/T6), so a single mid-epic checkbox is ambiguous -- these
boxes tick at **epic closeout**; interim per-member verification lives in the member checklists.

- [ ] Seam 1 -- all registered command strings + shared matcher (byte-identity is the API; unmerge-before-merge).
- [ ] Seam 2 -- `~/.forge/projects.json` schema (JSON, D-T3-c) + one canonicalization rule.
- [ ] Seam 3 -- Forge-binary resolution contract (+ `FORGE_SESSION` / managed-session short-circuit).
- [ ] Seam 4 -- runtime hooks live only at user scope (statusLine is the D3 exception -- stays project-scoped).
- [ ] Seam 5 -- host vs sidecar execution (T10 owns in-container resolution, `FORGE_SIDECAR`-keyed).

## Accepted decisions (reference; detail in card.md)

- **D1** -- version coupling accepted (one global binary, one version; T7 is a fail-clear guardrail, not a version
  manager).
- **D2** -- split the reachability bug fix (T2) from the migration (T3-T6).
- **D3** -- statusLine stays project-scoped (scalar, cannot double-fire); the user-scope rule covers hooks only.

## Closeout (epic)

- [ ] Every live member card is `done/` (or the shared contract is folded into normative design docs).
- [ ] design.md / design_appendix §C / cli_reference reflect the shipped install + hook-ownership model.
- [ ] Epic moved `doing/ -> done/`; `change_log.md` entry added; durable lessons promoted to `impl_notes.md` after human
  review.
