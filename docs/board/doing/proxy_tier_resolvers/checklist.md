# Checklist: proxy_tier_resolvers (Seam B)

Execution plan for the proxy tier/model-resolution seam. See `card.md` for the thesis and target shape.

**Type**: behavior-preserving refactor, **money/wire caution zone**. Two slices, **shipped as two PRs** (B1 then B2); B2
is gated on a characterization test.

**Branch**: `refactor/proxy-tier-resolvers` (cut 2026-07-06 from main `863ea3a3`) carries the plan + **B1**. **B2**
ships on a fresh branch from post-B1 main. Independent of Seam A -- no shared code.

---

## Current focus

**B1 implemented and verified on `refactor/proxy-tier-resolvers`; ready for PR 1.** B2 remains the money/wire follow-up
(`create_message`/`count_tokens` resolution + the port probe) and ships on a fresh post-B1 branch.

### Recorded review decisions

**Round 1**

- **Q1 SPLIT** -- this card = Seam B (B1+B2); sibling `ops_policy_seam` = Seam A (shipped, merged #84). No epic.
- **Q2** -- own branch `refactor/proxy-tier-resolvers`.

**Round 2 (checklist review, verified against code)**

- **F1 count_tokens integration gap -- RESOLVED (add smoke).** Existing proxy E2Es post only to `/v1/messages`
  (`test_session_routing_e2e.py:56/79/102`); the `count_tokens` hits under `tests/integration/` are the LLM-client
  method (`core/llm/test_litellm_real.py`), not the proxy `/v1/messages/count_tokens` endpoint. B2.1 changes BOTH
  halves, so add a count-tokens E2E smoke beside the routing tests -- not unit-only.
- **F2 port exception contract -- RESOLVED (preserve).** `server.find_available_port` (`:2288`) raises `RuntimeError`;
  `orchestrator._find_available_port` (`:1217`) raises `ProxyStartError`. Their range messages also differ:
  `{start}-{start+max}` vs `{start}-{start+max-1}` (an off-by-one). Consolidation must keep each caller's exception type
  and exact message; characterize both before extracting.
- **Decision port-home:** `src/forge/proxy/ports.py` (loopback probe is proxy-domain policy, not core networking),
  socket-only plus a local neutral exception. NOT `core/net.py`. If ever hoisted to core, name it narrowly
  (`find_available_loopback_port`), not a generic `net` junk drawer.
- **Decision granularity:** split PRs -- B1 first (low-risk, independently useful), B2 second (smaller money/wire review
  surface). B2.0 characterization is a green commit before the B2.1 extraction commit.

---

## Pre-flight findings (RE-VERIFIED 2026-07-06 against main `863ea3a3`, post-#84/#85)

These anchors supersede `card.md` (verified against the older `052a37c0`). Every card *claim* still holds -- bodies were
read, not just located -- but line numbers drifted and #85 moved the statusline tests.

- **`server.py` = 2494 LOC (cap 2500).** Unchanged; B2's LOC relief is load-bearing, not incidental.
- **B1 tier-word leaf is a confirmed 1:1 mirror across three sites** (bodies compared):
  - `proxy/data_models.py:_detect_tier` (`:20`, fable at `:37`) plus the second opus/fable line at `:232`.
  - `proxy/server.py:_tier_from_model_name` (`:764`) -- identical loop, `fable→opus`, `None` default.
  - `cli/status_line.py:explicit_tier_from_model` (**`:353`**, was `:351`) -- identical body; docstring says "1:1
    mirror".
- **Divergent variant to PRESERVE:** `cli/status_line.py:get_tier_from_display_name` (**`:340`**, was `:338`) --
  opus-first precedence, defaults `sonnet`, returns `str` (not `str | None`). Do NOT fold into the leaf.
- **#85 moved the statusline tests.** The parity-TODO home is now
  `tests/src/cli/statusline/test_statusline_forge_segments.py`.
- **Prefix-vocab home:** `core/llm/detection.py:10-20` -- `LITELLM_REMOTE_PREFIXES` (`:10`, incl. `vertex_ai/`) and
  `LITELLM_LOCAL_PREFIXES` (`:20`, `gemini/`).
- **B2 resolution anchors (drifted; re-pin exact block ranges under B2.0):** `_resolve_model_with_alternatives`
  (`:492`); `create_message` def `:1066`, tier/explicit-backend block ~`:1117-1159` (call `:1159`); `count_tokens` def
  `:1754`, block ~`:1784-1812` (hand-sync marker "Match the /v1/messages model resolution" at `:1784`, call `:1812`).
- **Inline litellm prefixes (drifted):** `data_models.py:253` (plus a second prefix check at `:220`),
  `client_factory.py:171`, `server.py:1139` + `:1799`.
- **Port-probe divergence:** `server.py:find_available_port` (`:2288`, public, positional, `max_attempts=10` default,
  inline bind, raises `RuntimeError`) vs `proxy_orchestrator.py:_find_available_port` (`:1217`, keyword-only, no
  default, delegates to `_is_port_in_use`, raises `ProxyStartError`). Both bind `127.0.0.1`. See F2 for the
  contract-preservation requirement.

---

## Slice B1 -- `core/tiers.py` tier-word leaf (PR 1)

- [x] **B1.1 Create `core/tiers.py`** with one `detect_tier_word(model: str) -> str | None` (haiku/sonnet/opus, plus the
  `fable → opus` rule). Neutral leaf -- no proxy/CLI imports. New unit test `tests/src/core/test_tiers.py` (archetype:
  the leaf never imports server/CLI).
- [x] **B1.2 Repoint the three mirror sites** to `detect_tier_word`:
  - `proxy/data_models.py:_detect_tier` (`:20`) calls the leaf, then keeps its dict fields
    (`has_explicit_tier = tier is not None`); also repoint the `:232` opus/fable line.
  - `proxy/server.py:_tier_from_model_name` (`:764`) delegates.
  - `cli/status_line.py:explicit_tier_from_model` (`:353`) delegates.
  - Assertion: no residual tier-word loop / opus-or-fable literal remains at these sites.
- [x] **B1.3 DO NOT TOUCH** `cli/status_line.py:get_tier_from_display_name` (`:340`). Assertion: its body is
  byte-identical in the diff.
- [x] **B1.4 Drop the parity TODO.** Replace the "Follow-up: extract a shared helper" comment in
  `tests/src/cli/statusline/test_statusline_forge_segments.py` with one parametrized parity test over the three
  delegating sites.

**Exit signal:** one tier-word function (plus the preserved divergent one); the parity test drops its TODO.

## Slice B2 -- shared model resolution + prefixes + one port probe (PR 2)

- [ ] **B2.0 Characterization test FIRST (money/wire gate).** Before touching resolution, pin tier + resolved model +
  cost decision for `create_message` and `count_tokens` across representative inputs (explicit backend, tier alias,
  passthrough), and re-pin the exact current block line ranges. **Land as a green commit before B2.1.** Home: new
  `tests/src/proxy/test_server_model_resolution.py`.
- [ ] **B2.1 Extend `server._resolve_model_with_alternatives` (`:492`)** to own the shared tier + explicit-backend
  block; `create_message` (~`:1117-1159`) and `count_tokens` (~`:1784-1812`) both call it. Assertion: the block lives
  once; characterization test unchanged.
- [ ] **B2.2 Import prefix vocab from `core/llm/detection.py`** at the inline sites (`data_models.py:253` and `:220`,
  `client_factory.py:171`, `server.py:1139` + `:1799`). Assertion: no inline prefix tuple literal remains in those
  files.
- [ ] **B2.3 One shared port probe in `src/forge/proxy/ports.py`** (new; socket-only + a local neutral exception, e.g.
  `NoAvailablePortError`). Repoint `server.find_available_port` (`:2288`) and `orchestrator._find_available_port`
  (`:1217`) to it. Each caller **keeps its current public signature** and **translates the neutral exception to its own
  contract**: `server → RuntimeError` (message `{start}-{start+max}`), `orchestrator → ProxyStartError` (message
  `{start}-{start+max-1}`). Both bind `127.0.0.1`. Assertion: single scan primitive; each caller's exception type +
  exact message preserved (test-guarded); the message off-by-one is preserved unless we explicitly decide to normalize
  it (that would be a documented behavior change, out of scope here).
- [ ] **B2.4 `server.py` LOC drops.** Assertion: `wc -l src/forge/proxy/server.py` < 2494.

**Exit signal:** `server.py` LOC drops below cap comfortably; the resolution block and the port probe each live once.

---

## Acceptance test table

| Test                        | Fixture                                              | Assertion                                                                                                                              | Test File                                                             |
| --------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| B1-a one tier-word leaf     | model names `…haiku/…sonnet/…opus/…fable`            | `core.tiers.detect_tier_word` returns the right tier (`fable→opus`); the 3 sites delegate to it                                        | `tests/src/core/test_tiers.py`, `tests/src/proxy/test_data_models.py` |
| B1-b divergent variant kept | display name with no tier word                       | `get_tier_from_display_name(...)` still defaults `sonnet` (opus-first), body unchanged in diff                                         | `tests/src/cli/statusline/test_statusline_forge_segments.py`          |
| B1-c three-site parity      | shared model-name inputs                             | one parametrized test asserts the 3 delegating sites agree with the leaf                                                               | `tests/src/cli/statusline/test_statusline_forge_segments.py`          |
| B2-a resolution char.       | explicit-backend + tier-alias + passthrough requests | tier + resolved model + cost decision identical before/after extraction (covers both create_message and count_tokens)                  | new `tests/src/proxy/test_server_model_resolution.py`                 |
| B2-b cost path unchanged    | representative costed request                        | `create_message` cost/metrics decisions unchanged                                                                                      | `tests/src/proxy/test_server_cost.py`                                 |
| B2-c port probe + contracts | port in use; range exhausted                         | shared probe binds `127.0.0.1` (not `''`); `server` raises `RuntimeError`, `orchestrator` raises `ProxyStartError`, messages unchanged | `tests/src/proxy/test_proxy_orchestrator.py` + a server port test     |

---

## Integration verification (proxy runtime -- REQUIRED, not optional)

B2 changes proxy request-path resolution (`create_message`/`count_tokens`) and port allocation. `AGENTS.md` and
`testing_guidelines.md` require integration -- not just unit -- for proxy-runtime changes; do not defer to closeout.
Docker must be up. Existing proxy E2Es post only to `/v1/messages`, so the count_tokens half needs its own smoke (F1):

- [ ] **Add a count-tokens E2E smoke** (post `/v1/messages/count_tokens` through the real proxy; assert a successful
  token-count response for explicit-tier and default-tier cases) beside
  `tests/integration/proxy/test_session_routing_e2e.py`. Do not require resolved-model/tier headers on this endpoint;
  B2.0 unit characterization pins the internal resolved model. (F1)
- [ ] `./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py tests/integration/proxy/test_session_routing_e2e.py`
  -- create_message tier/model resolution.
- [ ] `./scripts/test-integration.sh tests/integration/proxy/test_multi_proxy_workflow_e2e.py` -- port allocation across
  proxies (B2.3).
- [ ] `./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py` -- statusline tier display
  (B1).

## Design-doc / memory sync

- [x] **PR 1 (B1):** add `core/tiers.py` to `design.md` §6 directory structure and cross-check `design.md` §3.7
  tier-selection precedence still describes the now single-sourced tier-word step.
- [ ] **PR 2 (B2):** add `src/forge/proxy/ports.py` to `design.md` §6 directory structure.
- [ ] **impl_notes candidate (human-review gate):** tier-word detection is single-sourced in `core/tiers.py`; the
  statusline `get_tier_from_display_name` divergence (opus-first, defaults `sonnet`) is deliberate and NOT collapsed;
  the port probe lives in `proxy/ports.py` with caller-specific exception translation (RuntimeError vs ProxyStartError).

## Closeout (per PR)

- [x] **PR 1 (B1):** B1-a/b/c green; `make pre-commit` clean; `test_status_line_integration.py` green; `change_log.md`
  entry.
- [ ] **PR 2 (B2):** B2.0 characterization committed green before B2.1; B2-a/b/c green; count-tokens smoke + proxy
  integration green; `server.py` LOC < 2494; `change_log.md` entry.
- [ ] After both merge: design docs synced; move card `doing/ -> done/`.
