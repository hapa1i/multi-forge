# Replace legacy environment-based tier inference checklist

Current focus: implementation and verification complete; draft PR pending. Orders 17--35 remain parked.

## Activation and evidence

- [x] Close order 15 on pushed `main` at `358b39d6` after PR #194 merged as `ae7519fc` with all five checks passing.
- [x] Branch from that exact closeout and move only order 16 to `doing/`.
- [x] Reverify `_get_tier_for_model`: one definition, one internal fallback call, one direct regression consumer, and no
  repository producer for its `{LITELLM,OPENROUTER}_{HAIKU,SONNET,OPUS}_MODEL` names.
- [x] Characterize routing provenance: every production factory and auth-retry call passes the request-resolved tier;
  only the all-tier invalidation regression omits it.
- [x] Characterize cache and hyperparameter coupling: both use the explicit `(model_name, tier)` identity, and all-tier
  invalidation removes every cache entry for only the selected model.

## Implementation

- [x] Delete `_get_tier_for_model` and its false auto-detection log.
- [x] Require `get_client` callers to supply a tier explicitly.
- [x] Preserve all-tier invalidation while rebuilding its client with the named `proxy.default_tier` routing default.
- [x] Retain exact-tier authentication retry, provider detection, model mapping, cache keys, and tier hyperparameters.
- [x] Replace the parked compatibility assertion with regression coverage for explicit/default tier provenance.

## Verification and closeout

- [x] Run focused client-factory, routing, cache, authentication-retry, and named regression tests (50 passed).
- [x] Run the full proxy unit slice (794 passed, 14 deselected), `make test-unit` (9,200 passed, one skip, 122
  deselected), and `make test-regression` (913 passed).
- [x] Run targeted Docker translated-proxy integration coverage (seven passed).
- [x] Run full pre-commit, diff, design-size, and board-integrity checks: both living design documents remain below 30k
  tokens, all 886 local links across 349 board documents resolve, and Wave 7 is 15 `done` / 1 `doing` / 19 `todo`.
- [ ] Open a draft PR for order 16 and record its final proof before closeout.
