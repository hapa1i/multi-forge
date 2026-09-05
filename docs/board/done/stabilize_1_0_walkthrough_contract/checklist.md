# Stabilize the 1.0 Walkthrough Contract Checklist

Status: completed 2026-09-06. PR #251 merged as `6f7cb64e` with all five GitHub checks passing. The maintainer resolved
the manual repetition gates in the
[epic release disposition](../epic_1_0_release_hardening/checklist.md#release-disposition).

## Cleanup Ownership

- [x] Require matching index and manifest identity across Forge, project, checkout, and worktree roots before deleting
  fixed-name sessions; reject symlinked manifests, session directories, and external worktrees.
- [x] Remove only walkthrough-owned artifact, search, transfer, and fixture paths.
- [x] Reject missing or ambiguous `/workspace` mounts before Docker deletion.
- [x] Preflight every fixed session, proxy, container, installation registry, project registry, and shared path before
  the first runtime deletion.
- [x] Treat structurally malformed progress as an ownership failure even when session directories are absent.
- [x] Refuse unregistered proxy residue with its exact path and verification-gated manual recovery.

## Setup Paths

- [x] Reject explicitly empty `CLAUDE_CONFIG_DIR`.
- [x] Canonicalize setup roots so symlink-parent invocation passes the shipped Claude-wrapper probe.
- [x] Reject noncanonical markers, missing repository metadata, and symlinked generated-environment boundaries before
  reset mutates owned state.
- [x] Reject symlinked source, Claude, installation, and sandbox intermediate paths before cleanup.
- [x] Recreate missing generated-home directories before gated reset and preserve the Codex-home parent during cleanup.
- [x] Give a fresh setup on an existing canonical sandbox its applicable `--reset` guidance even when a generated home
  is missing.

## State and Report Evidence

- [x] Include inherited section prerequisites in both state-engine step hashes.
- [x] Require complete prefix evidence for walkthrough resume while preserving sparse full-QA selection semantics.
- [x] Give refused QA resume recovery that retains applicable run arguments and omits the rejected `--from`.
- [x] Resume an incomplete walkthrough from its first unrecorded step while retaining Codex, sidecar, and report modes.
- [x] Give malformed walkthrough state honest manual-inspection recovery instead of an inapplicable reset command.
- [x] Verify markers, payloads, directories, and the package root without following replacement-race symlinks; reject
  unexpected directories and special filesystem entries.
- [x] Generate current package identity before every resumed report.
- [x] Keep walkthrough memory integration assertions aligned with orientation-only coverage.

## Verification

- [x] Run the complete walkthrough state, contract, package-identity, sandbox, cleanup, and report slices.
- [x] Run targeted installer and exact-wheel walkthrough Docker coverage.
- [x] Exercise setup through a symlinked parent and real cleanup ownership fixtures.
- [x] Record commands, results, and the integrated SHA for batch closeout.

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
| Init-window reset         | state immediately after `init`              | missing sidecar flag is conservatively unset | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Missing generated home    | interrupted cleanup removes one home        | reset recreates only the canonical leaf      | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Fresh setup recovery      | canonical sandbox with one missing home     | rerun names reset without mutating the home  | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Option-bearing resume     | missing prefix with Codex, sidecar, report  | recovery retains all active selections       | `tests/src/skills/test_walkthrough_state.py`                   |
| Malformed resume state    | structurally invalid progress               | recovery requires inspection; reset refuses  | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Unregistered proxy state  | fixed proxy directory without registry row  | refusal names safe inspection and remedy     | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |
| Interrupted Codex cleanup | populated generated Codex home              | cleanup empties but preserves the parent     | `tests/regression/test_bug_walkthrough_interrupted_cleanup.py` |

## Evidence

Verified against integrated code SHA `817cb5ca`.

```bash
uv run pytest -q \
  tests/src/skills/test_walkthrough_state.py \
  tests/src/skills/test_walkthrough_state_parity.py \
  tests/src/skills/test_walkthrough_report.py \
  tests/src/skills/test_walkthrough_checklist_contract.py \
  tests/src/skills/test_walkthrough_package_identity.py \
  tests/regression/test_bug_walkthrough_interrupted_cleanup.py \
  tests/regression/test_bug_o036_walkthrough_sandbox_provenance.py \
  tests/regression/test_bug_walkthrough_report_debug_env.py
```

Result: 346 passed in 173.80 seconds.

```bash
./scripts/test-integration.sh \
  tests/integration/cli/test_session_commands_integration.py::TestSessionDelete \
  tests/integration/cli/test_session_resume_proxy_integration.py \
  tests/integration/cli/test_policy_cli_contract_integration.py \
  tests/integration/docker/test_installer.py::TestForgeExtensionEnable::test_full_profile_memory_skill_contracts \
  tests/integration/docker/test_walkthrough_release_artifact.py
```

Result: 11 passed in 60.17 seconds. The selection includes the full-profile installer contract and exact-wheel
walkthrough setup, report, cleanup, and isolation test.
