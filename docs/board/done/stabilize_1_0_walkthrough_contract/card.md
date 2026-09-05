# Stabilize the 1.0 Walkthrough Contract

**Lane**: `done/`

Completed 2026-09-06 after [PR #251](https://github.com/hapa1i/multi-forge/pull/251) merged as `6f7cb64e`.

**Epic**: [`1.0 Release Hardening`](../epic_1_0_release_hardening/card.md)

## Goal

Make walkthrough cleanup, setup, resume, package identity, and reporting match the documented isolated-release contract.

## Scope

- Bind cleanup to the exact sandbox root for sessions, artifacts, indexes, and Docker mounts (#1, #2, #3).
- Run registry ownership preflight before every destructive cleanup phase and fail closed on malformed progress (#7,
  #8).
- Reject empty Claude configuration roots and canonicalize safe symlink aliases consistently (#10, #16).
- Include inherited section prerequisites in step identity and require complete verified resume prefixes (#11, #12).
- Verify the exact canonical package tree and regenerate package identity for resumed reports (#13, #15).
- Replace stale walkthrough passport assertions with the current orientation contract.

## Constraints

- Foreign sessions, containers, artifacts, indexes, and installation rows are never cleanup targets.
- Reset reclaims only proven walkthrough-owned resources and preserves evidence on ownership failure.
- Walkthrough and QA state-engine copies remain behaviorally identical except for approved identity lines.
- Package identity remains bound to the answering wheel and is not reused as cleanup authority.
