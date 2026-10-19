# Remove retired Jev consumer experiments

**Status**: Active cleanup on `codex/remove-retired-jev-experiments`, based on `39ba8cbb`.

The [Jev epic](../../retired/epic_jev_support/card.md), [A2](../../retired/jev_rule_pack/card.md) and
[A3](../../retired/jev_cascade/card.md) are retired. Their experiment runners, rule definitions and unused consent
integration still add package and maintenance cost. Remove that implementation with its tests while retaining the
shipped [A1 client](../../done/jev_client_probes/card.md) and the historical evidence.

## Boundary and compatibility

A2 never exposed an activation command or registered `jev_rule_pack` as a supported policy bundle. Remove its private
`policy.rule_pack` modules, consent guards and session hooks without a compatibility layer. Generic unknown-bundle and
unknown-config-owner validation continues to reject unsupported policy configuration. Existing ordinary policy,
supervisor and session behavior must remain covered.

A2/A3 experiment scripts were explicitly invoked developer tools; remove those commands and their dedicated tests.
Historical JSON evidence and source identities remain unchanged. Historical instructions link to the last complete
[source revision](https://github.com/hapa1i/multi-forge/tree/39ba8cbb49d2ca3906f196edae2b139705a51bf1). Keep A1 judgment
types, transport, run identity, telemetry, probe, fixtures and tests. Independent policy-feedback fixes also remain.
This cleanup does not reopen or replace the retired feature cards.

## Acceptance

- No remaining runtime import or installed resource references removed modules.
- No current instructions prescribe deleted experiment commands; historical reproduction names a fixed revision.
- A1 remains importable from a clean wheel and its tests pass.
- Ordinary session and policy operations pass unit, regression and applicable integration checks.
- Preserved JSON evidence is byte-identical to the branch base.
