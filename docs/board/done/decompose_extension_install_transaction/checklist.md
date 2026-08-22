# Decompose the extension install transaction checklist

Current focus: closed -- order 33 shipped in PR #212; orders 34--35 remain parked.

- [x] Close order 32 on pushed `main`, create the order-33 branch from that exact commit, and activate only this member.
- [x] Reverify `Installer.init` as a 425-line transaction and find 20 installer `get_target_root` patches across seven
  test files, including the existing dual-binding regression.
- [x] Record the phase-order and fault matrix before changing production code.
- [x] Replace repeated namespace patches with one environment-backed Claude-target fixture and prove installer,
  path-policy legacy fallback, and runtime removal agree on the same root.
- [x] Extract typed file-apply, settings, stale-reconciliation, Codex, and final-assembly phase inputs/results without
  reordering side effects.
- [x] Keep planning and conflict return ahead of mutation, and keep tracking commit last.
- [x] Preserve every existing injected failure's filesystem, settings ownership, Codex config, and tracking outcome.
- [x] Update install ownership documentation without changing installer or runtime-scoped semantics.
- [x] Run focused installer/path-policy/runtime-removal tests and all regression tests.
- [x] Run targeted Docker installer/runtime-skill lifecycle tests, build, and clean-wheel enable/disable verification.
- [x] Run `make test-unit`, `make pre-commit`, design token checks, board integrity, and `git diff --check`.
- [x] Merge PR #212 as `f1afb30c` and close this member without activating order 34.

## Phase-order and fault matrix

| Order | Phase                              | Existing side effects                                               | Existing failure/rollback contract                                                                                       |
| ----: | ---------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
|     0 | Plan and conflict preflight        | None                                                                | Ownership validation raises; conflicts return the plan before mutation.                                                  |
|     1 | Apply setup                        | Optional Claude anchor creation and user-hook migration reads       | Anchor creation follows conflict preflight; known malformed hook input fails before extension writes or tracking.        |
|     2 | Compiled-skill materialization     | Compiler-owned cache entries only                                   | Cache failure reports that extension targets and tracking were unchanged.                                                |
|     3 | Dispatcher and file apply          | Dispatcher plus planned install/update file writes                  | File failures remove only newly created or unrecorded targets; prior targets and tracking retain current behavior.       |
|     4 | Claude settings and ownership      | Settings backup, merge/write, and added-settings ownership snapshot | Failure restores captured settings state and newly created files; tracking remains unchanged.                            |
|     5 | Stale reconciliation               | Verified stale-file deletion and empty-directory cleanup            | Failure uses the file/settings rollback inputs; already deleted stale targets are not reconstructed.                     |
|     6 | Codex apply                        | Managed Codex block mutation and registration readback              | Failure additionally restores captured Codex config state.                                                               |
|     7 | Final assembly and tracking commit | Pure installation assembly, then one tracking write                 | Tracking writes last; failure rolls back newly created files, settings state, and Codex state under the existing policy. |

## Acceptance coverage

| Boundary       | Required proof                                                                                                 |
| -------------- | -------------------------------------------------------------------------------------------------------------- |
| Root fixture   | All three imported bindings resolve one isolated environment-backed Claude target without namespace patching.  |
| Phase order    | A call-order test pins setup, cache, files, settings, stale cleanup, Codex, assembly, and tracking sequencing. |
| Fault behavior | Existing fault tests remain byte/state-equivalent at each named phase boundary.                                |
| Packaging      | Docker installer lifecycle, runtime-scoped enable/disable, build, and clean-wheel smoke all pass.              |

No Forge workflow command is authorized for this member.

## Verification

- Installer units: 829 passed, one skipped; full units: 9,303 passed, one skipped, 122 deselected.
- Regressions: 925 passed. Targeted Docker installer/runtime-skill lifecycle: 23 passed.
- `uv build` and `./scripts/test-wheel-runtime.sh` passed; the Docker lifecycle exercised built-wheel dual-runtime
  enable, sync, runtime-scoped disable, and full disable.
- Full pre-commit passed after expected Markdown normalization. Opus 5 local counts are 29,985 for `design.md` and
  29,984 for the former consolidated design appendix; 894 local links across 369 board documents resolve.
