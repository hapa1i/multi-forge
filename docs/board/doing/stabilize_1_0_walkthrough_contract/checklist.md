# Stabilize the 1.0 Walkthrough Contract Checklist

Current focus: implement the fixed walkthrough findings as the third contiguous batch series.

## Cleanup Ownership

- [ ] Require exact `forge_root` equality before deleting fixed-name sessions.
- [ ] Remove only walkthrough-owned artifact, search, transfer, and fixture paths.
- [ ] Reject missing or ambiguous `/workspace` mounts before Docker deletion.
- [ ] Run strict installation and project-registry preflight before runtime cleanup in every phase.
- [ ] Treat malformed progress as an ownership failure even when session directories are absent.

## Setup Paths

- [ ] Reject explicitly empty `CLAUDE_CONFIG_DIR`.
- [ ] Canonicalize setup roots so symlink-parent invocation passes the shipped Claude-wrapper probe.

## State and Report Evidence

- [ ] Include inherited section prerequisites in both state-engine step hashes.
- [ ] Refuse resume when any selected prefix step lacks current hash evidence.
- [ ] Reject noncanonical markers, unexpected directories, symlinked sentinels, and special filesystem entries.
- [ ] Generate current package identity before every resumed report.
- [ ] Keep walkthrough memory integration assertions aligned with orientation-only coverage.

## Verification

- [ ] Run the complete walkthrough state, contract, package-identity, sandbox, cleanup, and report slices.
- [ ] Run targeted installer and exact-wheel walkthrough Docker coverage.
- [ ] Exercise setup through a symlinked parent and real cleanup ownership fixtures.
- [ ] Record commands and results for batch closeout.

## Acceptance Tests

| Test                      | Fixture                                   | Assertion                                    | Test File                                               |
| ------------------------- | ----------------------------------------- | -------------------------------------------- | ------------------------------------------------------- |
| Session ownership         | same name in sibling root                 | foreign session survives cleanup             | `tests/src/skills/test_walkthrough_cleanup.py`          |
| Container ownership       | fixed name without one workspace mount    | cleanup refuses deletion                     | `tests/src/skills/test_walkthrough_cleanup.py`          |
| Reset preflight           | malformed progress and stale runtime      | reset preserves runtime evidence             | `tests/src/skills/test_walkthrough_setup.py`            |
| Canonical setup           | test root beneath a symlinked parent      | shipped Claude probe succeeds                | `tests/src/skills/test_walkthrough_setup.py`            |
| Complete resume prefix    | missing prior result                      | validation refuses without mutation          | `tests/src/skills/test_walkthrough_state.py`            |
| Exact package identity    | noncanonical marker or special tree node  | identity command exits non-zero              | `tests/src/skills/test_walkthrough_package_identity.py` |
| Resume report             | existing run with `--from` and `--report` | package identity exists and report runs      | `tests/src/skills/test_walkthrough_content.py`          |
| Installed memory contract | full profile wheel install                | QA owns schema; walkthrough owns orientation | `tests/integration/docker/test_installer.py`            |
