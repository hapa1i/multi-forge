# Checklist: proxy_tier_resolvers (Seam B)

Execution plan for the proxy tier/model-resolution seam. See `card.md` for the thesis and target shape.

**Type**: behavior-preserving refactor, **money/wire caution zone**. Two slices; B2 is gated on a characterization test.

**Branch**: `refactor/proxy-tier-resolvers` (cut when B1 starts; independent of Seam A — no shared code).

---

## Current focus

**Board split under review; implementation not started.** Sequenced after Seam A so it does not block A, but the two
share no code and could run in parallel. B1 is low-risk; B2 is the money/wire work.

### Recorded review decisions (2026-07-06)

- **Q1 SPLIT** — this card = Seam B (B1+B2); sibling `ops_policy_seam` = Seam A. No epic. Splitting lets Seam A ship
  without waiting on B2's characterization work.
- **Q2** — own branch `refactor/proxy-tier-resolvers` (different risk/test burden than A).

---

## Pre-flight findings (verified 2026-07-06 against `main` @ `052a37c0`)

- **`server.py` = 2494 LOC (cap 2500).** B2's LOC relief is load-bearing, not incidental.
- **B1 parity TODO home confirmed:** `tests/src/cli/test_statusline_forge_segments.py` carries the "…deliberate mirror
  of the proxy's … Follow-up: extract a shared helper." comment.
- **Divergent variant to preserve:** `cli/status_line.py:get_tier_from_display_name` (`:338`) — opus-first, defaults
  `sonnet`. Only the three sites at `data_models.py:20/232`, `server.py:764`, `status_line.py:351` share the leaf.
- **Prefix-vocab home exists:** `core/llm/detection.py:10-20` names the LiteLLM provider prefixes (`vertex_ai/`, …).

---

## Slice B1 — `core/tiers.py` tier-word leaf

- [ ] **B1.1 Create `core/tiers.py`** with one `detect_tier_word(model: str) -> str | None` (opus/sonnet/haiku, with the
  `fable → opus` rule). Neutral leaf — no proxy/CLI imports (archetype: the passthrough neutral-leaf test that asserts
  "the helper lives in the neutral leaf → passthrough never imports server").
- [ ] **B1.2 Repoint the three mirror sites:** `proxy/data_models.py:_detect_tier` (`:20`, and the `:232` opus/fable
  line), `proxy/server.py:_tier_from_model_name` (`:764`), `cli/status_line.py:explicit_tier_from_model` (`:351`).
- [ ] **B1.3 DO NOT TOUCH** `cli/status_line.py:get_tier_from_display_name` (`:338`). Assertion: that function's body is
  byte-identical in the diff.
- [ ] **B1.4 Drop the parity TODO.** Replace the "Follow-up: extract a shared helper" comment in
  `test_statusline_forge_segments.py` with a single parametrized parity test over the 3 delegating sites.

**Exit signal:** one tier-word function (+ the preserved divergent one); parity test drops its TODO.

## Slice B2 — shared model resolution + prefixes + one port probe

- [ ] **B2.0 Characterization test FIRST.** Pin tier + resolved model + cost decision for `create_message`
  (`server.py:1097-1163`) and `count_tokens` (`:1767-1813`) across representative inputs (explicit backend, tier alias,
  passthrough) **before** touching resolution. Assertion: characterization test committed and green on unchanged code.
- [ ] **B2.1 Extend `server._resolve_model_with_alternatives` (`:492`)** to own the ~50-line tier+explicit-backend
  block; `create_message` and `count_tokens` both call it. Assertion: the block lives once; characterization test
  unchanged.
- [ ] **B2.2 Import LiteLLM provider-prefix vocab from `core/llm/detection.py`** at the inline sites
  (`data_models.py:250`, `client_factory.py:170`, `server.py:1131/1791`). Assertion: no inline prefix tuple literal
  remains in those files.
- [ ] **B2.3 One `find_available_port`** shared by `server.py:2288` + `proxy_orchestrator.py:1217`. Assertion: single
  definition; **both bind `127.0.0.1`, not `''`** (`ba0a83e3` posture) — test-guarded.
- [ ] **B2.4 `server.py` LOC drops.** Assertion: `wc -l src/forge/proxy/server.py` < 2494.

**Exit signal:** `server.py` LOC drops below cap comfortably; the ~50-line block lives once.

---

## Acceptance test table

| Test                              | Fixture                                              | Assertion                                                                                            | Test File                                                                                |
| --------------------------------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| B1-a: one tier-word helper        | model names `…haiku…/…sonnet…/…opus…/…fable…`        | `core.tiers.detect_tier_word` returns the right tier (fable→opus); the 3 mirror sites delegate to it | `tests/src/proxy/test_data_models.py`, `tests/src/cli/test_statusline_forge_segments.py` |
| B1-b: divergent variant preserved | display name with no tier word                       | `get_tier_from_display_name(...)` still defaults `sonnet` (opus-first), body unchanged in diff       | `tests/src/cli/test_statusline_forge_segments.py`                                        |
| B2-a: resolution characterization | explicit-backend + tier-alias + passthrough requests | tier + resolved model + cost decision identical before/after extraction                              | new `tests/src/proxy/test_server_model_resolution.py`                                    |
| B2-b: cost path unchanged         | representative costed request                        | `create_message` cost/metrics decisions unchanged                                                    | `tests/src/proxy/test_server_cost.py`                                                    |
| B2-c: port bind security          | port in use                                          | `find_available_port` skips the busy port and binds `127.0.0.1` (not `''`)                           | `tests/src/proxy/test_proxy_orchestrator.py`                                             |

---

## Design-doc / memory sync

- [ ] Add `core/tiers.py` (new neutral leaf) to `design.md` §6 directory structure; cross-check §3.7 tier-selection
  precedence still describes the (now single-sourced) tier-word step accurately.
- [ ] **impl_notes candidate (human-review gate):** tier-word detection is single-sourced in `core/tiers.py`; the
  statusline `get_tier_from_display_name` divergence is deliberate and NOT collapsed.

## Closeout (pending)

- [ ] B1-a/b + B2-a/b/c green; characterization test passes.
- [ ] `make pre-commit` clean; touched-file `ruff`.
- [ ] `change_log.md` entry per shipped slice.
- [ ] Move card `doing/ → done/`.
