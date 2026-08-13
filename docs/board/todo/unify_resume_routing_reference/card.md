# Unify resume routing-reference resolution

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 session refactor work.

**Finding**: O054.

## Goal

Make every resume mode derive its inherited routing reference through the existing shared helper.

## Evidence and Authority

On `5777192a`, two resume-mode copies prefer only `proxy_id`, while `_resume_context_ref` correctly falls back through
`proxy_id or template`. Authority:
[`docs/design.md` "3.9 Session Resume"](../../../design.md#39-session-resume-context-management) and
[`docs/design.md` "3.6.12 Subprocess routing resolution"](../../../design.md#3612-subprocess-routing-resolution-normative).

## Acceptance Criteria

- Fresh/full/rewind resume paths call one helper and preserve proxy-ID precedence with template fallback.
- Characterization covers explicit proxy, inherited proxy, template-only legacy context, and direct mode.
- Run session resume/mode/routing units, regressions, and targeted session integration tests.

## Exclusions

Do not reroute direct sessions, change proxy health semantics, or alter transfer-context serialization beyond removing
the duplicated calculation.
