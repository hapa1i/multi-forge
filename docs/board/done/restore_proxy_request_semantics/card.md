# Restore proxy request semantics

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #170 (`acae1b9e`) after implementation and verification on
`agent/restore-proxy-request-semantics` from merged `main` at `7f705aad`.

**Findings**: D030, O008, O015, and O035.

## Goal

Make proxy-owned tier configuration authoritative across initial/auth-retry requests and preserve required request
constraints while translating or force-enabling reasoning.

## Evidence and Authority

Rechecked on merged `main` at `7f705aad`: undocumented tier environment variables override proxy config, auth retry
omits the resolved tier, reasoning pinning leaves incompatible sampling fields, and Anthropic `tool_choice:any` maps to
OpenAI `auto`.
[`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface) defines
proxy precedence and the translated wire contract.

The appendix's generic internal layering note ends in `env`, but its explicit hyperparameter chain is request value,
per-tier proxy override, then catalog default. No documentation or repository producer defines the direct
`{LITELLM,OPENROUTER}_{TIER}_{MAX_TOKENS,REASONING_EFFORT,VERBOSITY,THINKING_*}` reads in `client_factory.py`. This
member therefore treats those hyperparameter reads as uncontracted bypasses rather than a supported environment surface.
The separate `_MODEL` lookup and fallback tier inference remain parked under Wave 7 O051; credential and connection
environment precedence also remains unchanged.

The final regression artifact produces six expected failures and three compatibility passes on `7f705aad`: D030 is
parametrized for both providers, and the count includes the later adapter seam. A separate GPT Responses check also
failed before correction. Following O035 past the cited converter showed that fixing only the `auto` literal would not
have restored required-tool behavior.

## Implementation Outcome

- Removed only the undocumented tier-hyperparameter environment reads; `_MODEL` fallback inference remains for O051, and
  documented credential/connection environment resolution is unchanged.
- Authentication refresh now rebuilds the already resolved `(model, tier)` cache identity.
- A reasoning pin that changes `thinking` removes `temperature`, `top_p`, and `top_k` and records the sorted key names
  only; no-op pins preserve request sampling.
- Anthropic `any` becomes `required` and now reaches both Chat Completions and GPT Responses upstreams. The existing
  `auto`, named-tool, and `none` translations remain covered.
- Synchronized the normative precedence, retry, reasoning-mutation, audit-schema, and translated-tool contracts with the
  end-user proxy guide.

## Verification

- Fail-first: the final regression artifact collects `6 failed, 3 passed` on `7f705aad` (D030 is parametrized for both
  providers, the artifact includes the later adapter seam, and the satisfied-floor control adds the third pass); the
  separate GPT Responses seam also failed before its fix.
- Focused proxy/core slice: `204 passed`.
- Marked regression gate: `773 passed`.
- Unit gate: `9001 passed, 1 skipped, 122 deselected`.
- Translated-proxy Docker integration file: `4 passed`. The first file run exposed an older cumulative-event-count order
  dependency after the new request passed; the test now compares its own event delta, and the complete rerun is green.
- Full pre-commit and the explicit new-file hook run passed. Their first passes caught optional-mock-call typing guards
  in the adapter unit and untracked regression, and normalized Markdown; the corrected reruns are green.
- Board audit: 289 files, 713 relative links, no missing targets or stale lane references. The change log is 22,273
  tokens; size and diff checks pass. Shipped in PR #170 (`acae1b9e`).

## Acceptance Criteria

- Runtime hyperparameters come from proxy-owned config, not undocumented tier env variables.
- Authentication retry requests the same resolved tier and does not cache a differently shaped client.
- Force-enabled thinking removes incompatible sampling parameters while recording only metadata about the mutation.
- Anthropic `any` maps to OpenAI `required`; `auto`, named-tool, and `none` mappings remain stable.
- Retain converter/intercept/client regressions and run translated-proxy integration tests.

## Compatibility and Exclusions

Do not absorb Wave 7 removal of `_MODEL`-based legacy tier inference, change tier model selection, or expose request
content in logs.
