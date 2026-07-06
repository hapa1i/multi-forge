# Epic coordination checklist: Global Forge Runtime

Coordination only -- sequencing, shared-contract drift control, and cross-member decisions. It does **not** replace
member execution checklists (each member owns its own). Full contract in [`card.md`](card.md).

## Current focus

Active member: **T1 [`global_forge_install`](../global_forge_install/card.md)** (in `doing/`, branch
`global-forge-install`). Chosen as the first ticket because it is dependency-free (card: "Ship first") and is a
prerequisite for **both** the incident track (T1 -> T2) and the user-scope-model track (T1 -> T3 -> T4 -> T5 -> T6), so
starting it does **not** force the still-open D2 timing decision.

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
- [ ] T1 checklist reviewed; execution started.

## Decisions owed (coordination -- none block T1)

Record outcomes here as members are picked up.

- [ ] **D2 timing (owner T2) -- presumptive SKIP of T2, with a named criterion:** after T1, ship the interim
  absolute-path fix `forge_hook_absolute_command` (T2), or jump straight to the user-scope model (T3 -> T4 -> T5 -> T6)?
  Cost weighs against T2: it re-runs the epic's riskiest maneuver (registered-byte changes under append+dedupe merge,
  the statusLine scalar conflict-abort path, a paired T10 sidecar exemption, one Codex re-trust) -- the same seams T5
  must touch -- to produce bytes T5 deletes and a second re-trust supersedes. T2's only residual value after T1 is a
  hook subprocess on a minimal PATH that lacks `~/.local/bin`.
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
  - **Decision: pending** -- resolve at T1 closeout on the minimal-PATH evidence.
- [ ] **T4 benchmark (owner T4):** dispatcher shim (`forge-hook`, hyphen) vs absolute-symlink. Outcome decides whether
  T5 must update presence detection (the `has_forge_hook` needle is `"forge hook"`, with a space).
- [ ] **T3 trust model (owner T3):** explicit enroll only vs auto-enroll on enable / worktree-create for
  `~/.forge/projects.toml`.
- [ ] Next member after T1: pick per the D2 decision (T2 on the incident track, or T3 to open the model track).

## Shared-contract seams (drift watch)

Each seam is honored **per-member** (seam 1 alone binds T2/T5/T6), so a single mid-epic checkbox is ambiguous -- these
boxes tick at **epic closeout**; interim per-member verification lives in the member checklists.

- [ ] Seam 1 -- all registered command strings + shared matcher (byte-identity is the API; unmerge-before-merge).
- [ ] Seam 2 -- `~/.forge/projects.toml` schema + one canonicalization rule.
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
