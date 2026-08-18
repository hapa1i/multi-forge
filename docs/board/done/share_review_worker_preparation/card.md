# Share review worker preparation helpers

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #206 (`242ded2d`) after all five GitHub checks passed.

**Findings**: O057 and the verified worker-spec/parser plus optional JSON-metadata-tail subset of O095.

## Goal

Centralize review resource validation, marker filling, worker identity/label preparation, and common `model:role`
parsing without hiding command-specific semantics.

## Evidence and Authority

Reverified on `8787f7e7`: consensus and adversarial runners repeat resource validation, marker replacement, worker-ID
deduplication, and label maps. Their CLI parsers also repeat model lookup, colon/quote/empty validation, custom-label
truncation, and optional JSON metadata tails. The focused review/CLI baseline passes 214 tests. This activation verified
the source and tests without invoking a Forge workflow. Authority:
[`docs/design.md` "5.2 Policy, skills, workflows, and memory"](../../../design.md#52-policy-skills-workflows-and-memory)
and
[`docs/developer/cli_style_guidelines.md` "Command Shape"](../../../developer/cli_style_guidelines.md#command-shape).

## Acceptance Criteria

- Shared pure helpers return typed prepared inputs; consensus/adversarial modules retain their named roles, stances,
  prompts, verdicts, and output schemas.
- Worker parse errors, quote handling, model lookup, custom labels, resolved-model metadata, and routing warnings remain
  byte-compatible in focused CLI tests.
- Run review consensus/adversarial and CLI unit suites. Execution verification may use mocked/local tests; no external
  model call is required for a behavior-preserving refactor.

## Exclusions

Keep Click option declarations visible on each command. Do not change default workers, context mode, routing, fan-out,
or combine consensus and adversarial result types.

## Closeout

PR #206 merged as `242ded2d` with all five GitHub checks passing. Consensus and adversarial reviews now share resource,
worker, assignment-parser, and optional JSON-metadata mechanics while retaining distinct domain types, routing, fan-out,
prompts, wire orders, and result schemas. Order 28 remains parked for separate activation from this closeout.
