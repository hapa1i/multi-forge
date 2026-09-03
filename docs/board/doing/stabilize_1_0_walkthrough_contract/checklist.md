# Stabilize the 1.0 Walkthrough Contract Checklist

Current focus: final-audit hardening is implemented; current-head focused, packaged, and Docker reruns remain pending.

## Cleanup Ownership

- [x] Require matching index and manifest identity across Forge, project, checkout, and worktree roots before deleting
  fixed-name sessions; reject symlinked manifests, session directories, and external worktrees.
- [x] Remove only walkthrough-owned artifact, search, transfer, and fixture paths.
- [x] Reject missing or ambiguous `/workspace` mounts before Docker deletion.
- [x] Preflight every fixed session, proxy, container, installation registry, project registry, and shared path before
  the first runtime deletion.
- [x] Treat structurally malformed progress as an ownership failure even when session directories are absent.

## Setup Paths

- [x] Reject explicitly empty `CLAUDE_CONFIG_DIR`.
- [x] Canonicalize setup roots so symlink-parent invocation passes the shipped Claude-wrapper probe.
- [x] Reject noncanonical markers, missing repository metadata, and symlinked generated-environment boundaries before
  reset mutates owned state.
- [x] Reject symlinked source, Claude, installation, and sandbox intermediate paths before cleanup.

## State and Report Evidence

- [x] Include inherited section prerequisites in both state-engine step hashes.
- [x] Require complete prefix evidence for walkthrough resume while preserving sparse full-QA selection semantics.
- [x] Give refused QA resume recovery that retains applicable run arguments and omits the rejected `--from`.
- [x] Verify markers, payloads, directories, and the package root without following replacement-race symlinks; reject
  unexpected directories and special filesystem entries.
- [x] Generate current package identity before every resumed report.
- [x] Keep walkthrough memory integration assertions aligned with orientation-only coverage.

## Verification

- [ ] Run the complete walkthrough state, contract, package-identity, sandbox, cleanup, and report slices.
- [ ] Run targeted installer and exact-wheel walkthrough Docker coverage.
- [ ] Exercise setup through a symlinked parent and real cleanup ownership fixtures.
- [ ] Record commands, results, and the integrated SHA for batch closeout.

## Acceptance Tests

| Test                      | Fixture                                     | Assertion                                    | Test File                                                      |
| ------------------------- | ------------------------------------------- | -------------------------------------------- | -------------------------------------------------------------- |
| Session ownership         | same name in sibling root                   | foreign session survives cleanup             | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Atomic runtime preflight  | valid early resource plus invalid later one | no fixed resource is deleted                 | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Container ownership       | fixed name without one workspace mount      | cleanup refuses deletion                     | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Reset preflight           | malformed progress and stale runtime        | reset preserves runtime evidence             | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Path trust boundaries     | symlinked shared, runtime, or env path      | cleanup/reset refuses before mutation        | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Nested Git root           | missing or symlinked sandbox `.git`         | parent repository state is untouched         | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Canonical setup           | test root beneath a symlinked parent        | shipped Claude probe succeeds                | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Mode-aware resume         | incomplete walkthrough and sparse QA runs   | strict/sparse contracts remain distinct      | `tests/src/skills/test_walkthrough_state.py`                   |
| Exact package identity    | node and root replacement races             | identity command exits non-zero              | `tests/src/skills/test_walkthrough_package_identity.py`        |
| Resume report             | existing run with `--from` and `--report`   | package identity is regenerated before state | `tests/src/skills/test_walkthrough_checklist_contract.py`      |
| Installed memory contract | full profile wheel install                  | QA owns schema; walkthrough owns orientation | `tests/integration/docker/test_installer.py`                   |

## Evidence

Current-head evidence is pending the integrated final SHA.
