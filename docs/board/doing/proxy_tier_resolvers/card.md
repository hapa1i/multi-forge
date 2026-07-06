# proxy_tier_resolvers -- one tier/model-resolution authority in the proxy

**Lane**: `doing/` -- split from the `ops_seam_completion` batch (2026-07-06) per its own acceptance guidance (two
member cards, no epic). Sibling: [`ops_policy_seam`](../ops_policy_seam/card.md) (Seam A). Independent -- **money/wire
caution zone** (see Risks), decoupled from Seam A so A can ship without waiting on B2's characterization work.

**Type**: behavior-preserving refactor. No wire/cost decision changes -- only extraction of named resolvers, which
incidentally relieves `server.py` cap pressure.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`, area proxy-pkg). Tier-word
lockstep adversarially verified (auto-refuter SURVIVES); the create_message/count_tokens block, litellm prefix vocab,
and port probe are auditor first-pass evidence with strong anchors (re-verify at slice start).

**References**: `docs/design.md` §3.7 (tier selection precedence); `docs/board/impl_notes.md` (statusline
tier-precedence mirror -- the divergence to PRESERVE); `src/forge/core/llm/detection.py:10-20` (existing prefix-vocab
home).

**Anchors**: the line numbers below are illustrative and from `052a37c0`. `checklist.md` carries anchors RE-VERIFIED
against current main (post-#84/#85, 2026-07-06) -- trust the checklist for exact lines.

---

## Why

Tier/model resolution is hand-synced in lockstep across the proxy with no single authority:

- **Tier-word detection** (`… "fable" → opus`) is duplicated across `proxy/data_models.py:_detect_tier` (`:20`, plus the
  `:232` opus/fable line), `proxy/server.py:_tier_from_model_name` (`:764`, docstring "Mirrors
  data_models.\_detect_tier"), and `cli/status_line.py:explicit_tier_from_model` (`:351`, docstring "1:1 mirror of the
  proxy's \_tier_from_model_name"). When Fable shipped, all three needed the `fable → opus` line by hand; the parity
  test already says *"Follow-up: extract a shared helper"* (`tests/src/cli/test_statusline_forge_segments.py`).
- **create_message vs count_tokens** hand-sync a ~50-line tier + explicit-backend resolution block
  (`server.py:1097-1163` vs `:1767-1813`, the second's comment "Match the /v1/messages model resolution").
- The **LiteLLM provider-prefix vocabulary** is inlined 5× while `core/llm/detection.py:10-20` names it.
- The **port-availability probe** is duplicated `server.py:2288` / `proxy_orchestrator.py:1217` -- a
  `bind('') → bind('127.0.0.1')` security fix had to be hand-applied to both (`ba0a83e3`).

## Target shape

| Resolver                                 | Target home                                        | Copies                                                                  |
| ---------------------------------------- | -------------------------------------------------- | ----------------------------------------------------------------------- |
| Tier-word detection (`fable→opus`)       | `core/tiers.py` (new neutral leaf)                 | data_models.py:20/232; server.py:764; status_line.py:351 (**NOT :338**) |
| Tier + explicit-backend model resolution | `server._resolve_model_with_alternatives` (`:492`) | server.py:1097-1163, :1767-1813                                         |
| LiteLLM provider-prefix vocabulary       | `core/llm/detection.py:10-20` (existing home)      | data_models.py:250; client_factory.py:170; server.py:1131/1791          |
| `find_available_port`                    | one shared home                                    | orchestrator.py:1217; server.py:2288                                    |

## Non-goals / must-not-break

- **No behavior change.** Same tier decisions, same wire output, same cost decisions.
- **PRESERVE the deliberate tier divergence.** `cli/status_line.py:get_tier_from_display_name` (`:338`) checks
  opus-first and defaults `sonnet` on purpose (impl_notes: statusline mirrors proxy routing precedence). Only the three
  "1:1 mirror" sites share the leaf; `get_tier_from_display_name` keeps its distinct precedence.
- **Preserve the `127.0.0.1` bind** (`ba0a83e3` security posture) in the shared port probe.
- **Do not touch `converters.py`** (essential wire translation) and **do not split `server.py`** here (separate card) --
  Seam B only extracts named resolvers out of it. `server.py` is 2494 LOC (cap 2500).

## Phased plan

| Slice | Scope                                                                                                                      | Exit signal                                                                                                  |
| ----- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| B1    | `core/tiers.py` tier-word leaf; repoint the three 1:1-mirror sites; keep `get_tier_from_display_name`.                     | one tier-word function (+ the preserved divergent one); parity test drops its "extract a shared helper" TODO |
| B2    | Shared model-resolution helper for create_message/count_tokens; import `detection.py` prefixes; one `find_available_port`. | `server.py` LOC drops below cap comfortably; the ~50-line block lives once                                   |

## Blast radius / risks

- `server.py` (2494 LOC, at cap) -- **money/wire caution zone**. Pin cost/metrics/tier decisions with a characterization
  test (B2.0) **before** B2.1. Never eyeball `server.py` resolution.
- `find_available_port` has a *security* history -- keep the `127.0.0.1` bind.
- The divergent statusline tier precedence and the port bind are both easy to erase in a naive "unify."

## Metric / falsifiable prediction

The next new tier (post-Fable) touches **1 leaf, not 3**. Confirm on the next model that rides an existing tier.

## Closeout

(pending)
