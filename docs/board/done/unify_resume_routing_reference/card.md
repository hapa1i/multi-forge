# Unify resume routing-reference resolution

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #203 (`0d041b83`) after all five GitHub checks passed.

**Finding**: O054.

## Goal

Make every resume mode derive its inherited routing reference through the existing shared helper.

## Evidence and Authority

Reverified on `6e4038db`: `_resume_fresh`, `_resume_fresh_native`, and `_resume_fresh_rewind` each duplicate the same
override/direct/inheritance calculation. All three choose only `routing.proxy_id` for an explicit override, while the
existing `_resume_context_ref` correctly falls back through `routing.proxy_id or routing.template`. The production CLI
resolver populates both fields, but `ResolvedRouting` permits template-only values and inherited legacy manifests carry
only a template. The focused resume/mode/routing baseline is 73 passing tests. Authority:
[`docs/design.md` "3.9 Session Resume"](../../../design.md#39-session-resume-context-management) and
[`docs/design.md` "3.6.12 Subprocess routing resolution"](../../../design.md#3612-subprocess-routing-resolution-normative).

## Acceptance Criteria

- Fresh/full/rewind resume paths call one helper and preserve proxy-ID precedence with template fallback.
- Characterization covers explicit proxy, inherited proxy, template-only legacy context, and direct mode.
- Run session resume/mode/routing units, regressions, and targeted session integration tests.

## Exclusions

Do not reroute direct sessions, change proxy health semantics, or alter transfer-context serialization beyond removing
the duplicated calculation.

## Closeout

PR #203 merged as `0d041b83` with all five GitHub checks passing. Transfer, native, and rewind fresh-resume paths now
share `_resume_context_ref`, retaining direct-mode null routing and proxy-ID precedence with template fallback. Order 25
remains parked for separate activation from this closeout.
