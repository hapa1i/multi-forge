# Checklist: proxy_tier_resolvers (Seam B)

Execution plan for the proxy tier/model-resolution seam. See `card.md` for the thesis and target shape.

**Type**: behavior-preserving refactor, **money/wire caution zone**. Two slices; B2 is gated on a characterization test.

**Branch**: `refactor/proxy-tier-resolvers` (cut 2026-07-06 from main `863ea3a3`; independent of Seam A -- no shared
code).

---

## Current focus

**Branch cut; anchors re-verified against current main; awaiting checklist review before implementation.** B1 is
low-risk (tier-word leaf); B2 is the money/wire work (`create_message`/`count_tokens` resolution + the port probe).
Sequenced after Seam A, but the two share no code.

### Recorded review decisions (2026-07-06)

- **Q1 SPLIT** -- this card = Seam B (B1+B2); sibling `ops_policy_seam` = Seam A (shipped, merged #84). No epic.
- **Q2** -- own branch `refactor/proxy-tier-resolvers` (different risk/test burden than A).

---

## Pre-flight findings (RE-VERIFIED 2026-07-06 against main `863ea3a3`, post-#84/#85)

These anchors supersede `card.md` (the card was verified against the older `052a37c0`). Every card *claim* still holds
-- bodies were read, not just located -- but line numbers drifted and #85 moved the statusline tests.

- **`server.py` = 2494 LOC (cap 2500).** Unchanged; B2's LOC relief is load-bearing, not incidental.
- **B1 tier-word leaf is a confirmed 1:1 mirror across three sites** (bodies compared):
  - `proxy/data_models.py:_detect_tier` (`:20`, fable at `:37`) plus the second opus/fable line at `:232`.
  - `proxy/server.py:_tier_from_model_name` (`:764`) -- identical loop, `fable→opus`, `None` default.
  - `cli/status_line.py:explicit_tier_from_model` (**`:353`**, was `:351`) -- identical body; docstring says "1:1
    mirror".
- **Divergent variant to PRESERVE:** `cli/status_line.py:get_tier_from_display_name` (**`:340`**, was `:338`) --
  opus-first precedence, defaults `sonnet`, returns `str` (not `str | None`). Do NOT fold into the leaf.
- **#85 moved the statusline tests.** The parity-TODO home is now
  `tests/src/cli/statusline/test_statusline_forge_segments.py` (was `tests/src/cli/test_statusline_forge_segments.py`).
- **Prefix-vocab home:** `core/llm/detection.py:10-20` -- `LITELLM_REMOTE_PREFIXES` (`:10`, incl. `vertex_ai/`) and
  `LITELLM_LOCAL_PREFIXES` (`:20`, `gemini/`).
- **B2 resolution anchors (drifted; re-pin exact block ranges under B2.0):** `_resolve_model_with_alternatives`
  (`:492`); `create_message` def `:1066`, tier/explicit-backend block ~`:1117-1159` (calls `:1159`); `count_tokens` def
  `:1754`, block ~`:1784-1812` (the hand-sync marker comment "Match the /v1/messages model resolution" is at `:1784`,
  call at `:1812`).
- **Inline litellm prefixes (drifted):** `data_models.py:253` (plus a second prefix check at `:220`),
  `client_factory.py:171`, `server.py:1139` + `:1799`.
- **Port-probe divergence:** `server.py:find_available_port` (`:2288`, public, `max_attempts=10` default) vs
  `proxy_orchestrator.py:_find_available_port` (`:1217`, keyword-only, no default). Consolidation must reconcile the two
  signatures; both must keep the `127.0.0.1` bind (`ba0a83e3`).

---

## Slice B1 -- `core/tiers.py` tier-word leaf

- [ ] **B1.1 Create `core/tiers.py`** with one `detect_tier_word(model: str) -> str | None` (haiku/sonnet/opus, plus the
  `fable → opus` rule). Neutral leaf -- no proxy/CLI imports. New unit test `tests/src/core/test_tiers.py` (archetype:
  the leaf never imports server/CLI). Assertion: passthrough tier detection lives in one function.
- [ ] **B1.2 Repoint the three mirror sites** to `detect_tier_word`:
  - `proxy/data_models.py:_detect_tier` (`:20`) calls the leaf, then keeps its dict fields
    (`has_explicit_tier = tier is not None`); also repoint the `:232` opus/fable line.
  - `proxy/server.py:_tier_from_model_name` (`:764`) delegates.
  - `cli/status_line.py:explicit_tier_from_model` (`:353`) delegates.
  - Assertion: no residual `for tier in (...)` / opus-or-fable tier-word loop remains at these sites.
- [ ] **B1.3 DO NOT TOUCH** `cli/status_line.py:get_tier_from_display_name` (`:340`). Assertion: its body is
  byte-identical in the diff.
- [ ] **B1.4 Drop the parity TODO.** Replace the "Follow-up: extract a shared helper" comment in
  `tests/src/cli/statusline/test_statusline_forge_segments.py` with one parametrized parity test over the three
  delegating sites.

**Exit signal:** one tier-word function (plus the preserved divergent one); the parity test drops its TODO.

## Slice B2 -- shared model resolution + prefixes + one port probe

- [ ] **B2.0 Characterization test FIRST (money/wire gate).** Before touching resolution, pin tier + resolved model +
  cost decision for `create_message` and `count_tokens` across representative inputs (explicit backend, tier alias,
  passthrough), and re-pin the exact current block line ranges. Assertion: characterization test committed and green on
  unchanged code. Home: new `tests/src/proxy/test_server_model_resolution.py`.
- [ ] **B2.1 Extend `server._resolve_model_with_alternatives` (`:492`)** to own the shared tier + explicit-backend
  block; `create_message` (~`:1117-1159`) and `count_tokens` (~`:1784-1812`) both call it. Assertion: the block lives
  once; characterization test unchanged.
- [ ] **B2.2 Import prefix vocab from `core/llm/detection.py`** at the inline sites (`data_models.py:253` and `:220`,
  `client_factory.py:171`, `server.py:1139` + `:1799`). Assertion: no inline prefix tuple literal remains in those
  files.
- [ ] **B2.3 One shared `find_available_port`** for `server.py:2288` + `proxy_orchestrator.py:1217`. Reconcile the
  signature (positional-with-default vs keyword-only) and home it in a neutral leaf so it does not re-introduce a
  server\<->orchestrator import cycle (decide the home at slice start; candidates: `core/net.py` or a shared `proxy`
  util). Assertion: single definition; **both bind `127.0.0.1`, not `''`** (`ba0a83e3` posture) -- test-guarded.
- [ ] **B2.4 `server.py` LOC drops.** Assertion: `wc -l src/forge/proxy/server.py` < 2494.

**Exit signal:** `server.py` LOC drops below cap comfortably; the resolution block lives once.

---

## Acceptance test table

| Test                        | Fixture                                              | Assertion                                                                                       | Test File                                                             |
| --------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| B1-a one tier-word leaf     | model names `…haiku/…sonnet/…opus/…fable`            | `core.tiers.detect_tier_word` returns the right tier (`fable→opus`); the 3 sites delegate to it | `tests/src/core/test_tiers.py`, `tests/src/proxy/test_data_models.py` |
| B1-b divergent variant kept | display name with no tier word                       | `get_tier_from_display_name(...)` still defaults `sonnet` (opus-first), body unchanged in diff  | `tests/src/cli/statusline/test_statusline_forge_segments.py`          |
| B1-c three-site parity      | shared model-name inputs                             | one parametrized test asserts the 3 delegating sites agree with the leaf                        | `tests/src/cli/statusline/test_statusline_forge_segments.py`          |
| B2-a resolution char.       | explicit-backend + tier-alias + passthrough requests | tier + resolved model + cost decision identical before/after extraction                         | new `tests/src/proxy/test_server_model_resolution.py`                 |
| B2-b cost path unchanged    | representative costed request                        | `create_message` cost/metrics decisions unchanged                                               | `tests/src/proxy/test_server_cost.py`                                 |
| B2-c port bind security     | port in use                                          | shared `find_available_port` skips the busy port and binds `127.0.0.1` (not `''`)               | `tests/src/proxy/test_proxy_orchestrator.py`                          |

---

## Integration verification (proxy runtime -- REQUIRED, not optional)

B2 changes proxy request-path resolution (`create_message`/`count_tokens`) and port allocation. `AGENTS.md` and
`testing_guidelines.md` require integration tests -- not just unit -- for proxy-runtime changes; do not defer to
closeout. Docker must be up. Run the relevant files (targeted, not the full suite):

- [ ] `./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py tests/integration/proxy/test_session_routing_e2e.py`
  -- tier/model resolution through the real proxy (B1 + B2.1).
- [ ] `./scripts/test-integration.sh tests/integration/proxy/test_multi_proxy_workflow_e2e.py` -- port allocation across
  multiple proxies (B2.3).
- [ ] `./scripts/test-integration.sh tests/integration/cli/test_status_line_integration.py` -- statusline tier display
  (B1).

## Design-doc / memory sync

- [ ] Add `core/tiers.py` (new neutral leaf) to `design.md` §6 directory structure; if B2.3 adds `core/net.py`, note it
  too. Cross-check `design.md` §3.7 tier-selection precedence still describes the (now single-sourced) tier-word step.
- [ ] **impl_notes candidate (human-review gate):** tier-word detection is single-sourced in `core/tiers.py`; the
  statusline `get_tier_from_display_name` divergence (opus-first, defaults `sonnet`) is deliberate and NOT collapsed.

## Closeout (pending)

- [ ] B1-a/b/c + B2-a/b/c green; B2.0 characterization test committed green before B2.1.
- [ ] Integration verification above green (proxy runtime).
- [ ] `make pre-commit` clean; touched-file `ruff`.
- [ ] `change_log.md` entry (one batch entry or per shipped slice).
- [ ] Move card `doing/ -> done/`.
