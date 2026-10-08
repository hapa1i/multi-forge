# Partition the Session Design

**Lane**: `done/`, 2026-10-08. [PR #258](https://github.com/hapa1i/multi-forge/pull/258) merged to `main` as `56d4b8f5`,
including the later runtime/B1 stack. The [checklist](checklist.md) retains the partition evidence.

Scheduled 2026-10-07 before
[B1's first normative documentation update](../../done/plan_file_supervision/checklist.md#documentation-prerequisites),
on a separate documentation branch/PR. Coordinate links with the
[runtime partition](../../done/partition_runtime_design/card.md); no shared implementation batch is implied.

## Goal

Partition `docs/design_sessions.md` into stable session-domain documents that each fit comfortably within the living
documentation target.

## Motivation

The document reached 25,420 Claude Opus 5 tokens during PR #245. That remains below the 30,000-token hard limit but is
above the repository's 25,000-token target, leaving too little room for another sessions-domain change.

The pre-partition SHA-256-matched `.file-token-counts.json` entry reported 25,797 Claude Opus 5 tokens on 2026-10-07. A
warning-only file-size check is not acceptance of additional documentation debt.

## Scope

- Identify cohesive session subdomains with clear ownership and navigation boundaries.
- Move normative material losslessly, keeping `docs/design_sessions.md` as the session-design entry point.
- Repoint all inbound links and refresh repository token-count evidence.

## Constraints

- Do not change shipped behavior or terminology while partitioning.
- Preserve every normative invariant, example, and cross-domain reference.
- Target at most 23,000 Claude Opus 5 tokens for each newly partitioned design document.

## Acceptance

1. Every resulting living document is at or below the 23,000-token partition target.
2. The repository-wide Markdown link audit passes with no stale pre-partition anchors.
3. A lossless-content audit accounts for all moved normative sections and examples.
