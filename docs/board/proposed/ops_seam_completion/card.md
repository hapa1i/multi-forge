# ops_seam_completion -- finish the core/ops split for the policy surface and the proxy tier/model resolvers

**Lane**: `proposed/` -- accepted-candidate refactor batch, not yet scheduled. Seam completion that mirrors two
already-blessed in-repo patterns; mostly behavior-preserving, with a **small defect-fix** in Slice A2 (converge the
drifted proxy-id-recovery error posture -- one copy silently swallows, one logs -- to the logged posture per
coding_standards §5). Independently shippable slices.

**When accepted**: this card bundles **two separable seams** (Seam A = the `core/ops` policy surface; Seam B = the proxy
tier/model resolvers). Per `docs/developer/board_contract.md`, promote them as **two member cards** (`ops_policy_seam`
and `proxy_tier_resolvers`) -- or an `epic_ops_seam_completion` coordinator if they need shared sequencing -- rather than
moving the whole batch to `doing/` at once. They share only a theme, not a load-bearing contract, so an epic is
optional.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; areas core-ops, cli-other,
proxy-pkg). The tier-word-detection lockstep edit and the routing-override / proxy-id-recovery twins were adversarially
verified (auto-refuter SURVIVES); the policy `%direct` duplication and the create_message/count_tokens block are auditor
first-pass evidence with strong anchors.

**Type**: **refactor batch card**, deliberately **not an epic**. Two seams (the `core/ops` policy surface and the proxy
tier/model resolvers) share the theme "complete the blessed pattern," not one contract. Splittable into two cards.

**References**: `docs/design.md` §3.12 (command-core ops -- the normative pattern), §3.5 (ownership), §3.7 (tier
selection precedence); `docs/developer/cli_style_guidelines.md` (ops UI-agnostic; CLI owns rendering);
`docs/board/impl_notes.md` (statusline tier-precedence mirror -- the divergence to PRESERVE); archetype
`docs/board/done/session_op_layer_extraction/card.md`.

---

## Why (the thesis)

Two blessed patterns have laggards that never got mirrored to them.

**Seam A -- the `core/ops` split for the supervisor surface.** `design.md` §3.12 makes `core/ops/` the home for logic
shared between `forge ...` and `%...`; `session_op_layer_extraction` proved the pattern. But the `%policy supervisor`
lifecycle (set/off/on/remove/reload) in `cli/hooks/direct_commands.py:842-934,1049-1058` duplicates the same mutations
in `cli/policy.py:1413-1489` instead of both delegating to a `core/ops/policy.py` op -- exactly the anti-pattern §3.12
exists to prevent. Three smaller ops-boundary leaks travel with it:

- **CLI/ops routing twins** (`core/ops/claude_session.py:841/870/905` vs `cli/session.py:121/152/253`): routing-override
  and effective-proxy helpers exist on both sides of the boundary.
- **Proxy-id recovery from base_url copy-pasted 4x** (`claude_session.py:1204/1388`, `session_context.py:476`,
  `session/hooks/session_start.py:335`, `proxy/proxies.py:332`) -- **already drifted on error posture** (one logs, one
  silently swallows -- see Surfaced Defect).
- **Contract asymmetry:** `cli/session_manage.py:437` imports the op's private `_scope_filters` because
  `list_sessions_older_than` lacks the `(ctx, scope)` contract its sibling `list_sessions` has; `core/ops/gc.py:424`
  reaches into `ActiveSessionStore._entry_is_live` across the package boundary.

**Seam B -- one tier/model-resolution authority in the proxy.** Tier-word detection is hand-edited in lockstep across
`proxy/data_models.py:_detect_tier`, `proxy/server.py:_tier_from_model_name` (docstring: "Mirrors
data_models._detect_tier"), and `cli/status_line.py:explicit_tier_from_model` (docstring: "1:1 mirror of the proxy's
_tier_from_model_name"). When Fable shipped, all three needed the `fable -> opus` line by hand; a parity test comment
already says *"Follow-up: extract a shared helper."* Alongside it: `create_message` and `count_tokens` hand-sync a
~50-line tier + explicit-backend resolution block (`server.py:1097-1163` vs `:1767-1813`, the second's comment: "Match
the /v1/messages model resolution"); the LiteLLM provider-prefix vocabulary is inlined 5x while `core/llm/detection.py`
names it; and the port-availability probe is duplicated `server`/`orchestrator` (a `bind('') -> bind('127.0.0.1')`
security fix had to be hand-applied to both in commit `ba0a83e3`).

---

## Non-goals / must-not-break

- **No behavior change.** Same decisions, same wire output, same `%direct` block/allow JSON.
- **PRESERVE the deliberate tier divergence.** `cli/status_line.py:get_tier_from_display_name` (`:339`) checks
  opus-first and defaults to `sonnet` on purpose (impl_notes: statusline mirrors proxy routing precedence). Only the
  three sites that claim "1:1 mirror" share a leaf; `get_tier_from_display_name` keeps its distinct precedence.
- **Do not touch `converters.py`** (Essential wire translation) and do not split `server.py` here (that is a separate
  card) -- Seam B only *extracts named resolvers* out of it, which incidentally relieves cap pressure.
- **Rendering stays in the CLI.** `core/ops/policy.py` returns structured results + typed errors; `cli/policy.py` and
  the `%` responder own all printing / hook JSON.

---

## Target shape

**Seam A:**

| Op (new/changed) | Replaces |
| --- | --- |
| `core/ops/policy.py::supervisor_{set,off,on,remove,reload}` | direct_commands.py:842-934,1049 + cli/policy.py:1413-1489 |
| `resolve_effective_proxy` / routing-override in ops only | claude_session.py:841/870/905 + cli/session.py:121/152/253 |
| `recover_proxy_id_from_base_url(...)` (one helper, one error posture) | claude_session.py:1204/1388; session_context.py:476; session_start.py:335; proxy/proxies.py:332 |
| `list_sessions_older_than(ctx, scope)` (match sibling contract) | cli/session_manage.py:437 importing `_scope_filters` |
| `ActiveSessionStore.is_live` (public) | gc.py:424 reaching `_entry_is_live` |

**Seam B:**

| Resolver | Target home | Copies |
| --- | --- | --- |
| Tier-word detection (`fable->opus`) | `core/tiers.py` leaf | data_models.py:20/226; server.py:764; status_line.py:351 (NOT :339) |
| Tier + explicit-backend model resolution | `server._resolve_model_with_alternatives` extended (`:492`) | server.py:1097-1163, :1767-1813 |
| LiteLLM provider-prefix vocabulary | `core/llm/detection.py:10-20` (existing home) | data_models.py:250; client_factory.py:170; server.py:1131/1791 |
| `find_available_port` | one home shared by server + orchestrator | orchestrator.py:1217; server.py:2288 |

---

## Phased plan

| Slice | Scope | Exit signal |
| --- | --- | --- |
| A1 | `core/ops/policy.py` supervisor lifecycle; repoint `cli/policy.py` + `%direct`. | a supervisor mutation lives once; both surfaces delegate; no Click/print in the op |
| A2 | Routing-override + `recover_proxy_id_from_base_url` (single error posture) + `_scope_filters`/`is_live` contract fixes. | CLI imports no op-private symbol; proxy-id recovery has one logging posture |
| B1 | `core/tiers.py` tier-word leaf; repoint the three 1:1-mirror sites; keep `get_tier_from_display_name`. | one tier-word function (+ the preserved divergent one); parity test drops its "extract a shared helper" TODO |
| B2 | Shared model-resolution helper for create_message/count_tokens; import `detection.py` prefixes; one `find_available_port`. | `server.py` LOC drops below cap comfortably; the ~50-line block lives once |

## Blast radius

- Seam A: `core/ops/policy.py` is new; `cli/policy.py` (1795 LOC) + `direct_commands.py` (1547 LOC) repoint. Count
  `patch("forge.cli.policy.*")` and `patch("forge.cli.hooks.direct_commands.*")` before A1.
- Seam B: `server.py` (2494 LOC, at cap) -- money/wire caution zone. Pin cost/metrics/tier decisions with a
  characterization test before B2. `find_available_port` had a *security* history -- keep the `127.0.0.1` bind.

## What was verified vs. first-pass

- **Adversarially verified SURVIVES:** tier-word lockstep ([38]); routing-override twins ([17]); proxy-id recovery
  ([12]); `_scope_filters` contract ([15]); `gc._entry_is_live` ([16]).
- **First-pass, re-verify (Medium):** policy `%direct` <-> `cli/policy.py` supervisor duplication ([27]/[03]);
  create_message/count_tokens block ([39]); litellm prefix vocab ([41]); port probe ([40]).

## Adversarial verification (survived where run)

`design.md` §3.12 reinforces Seam A (ops avoid duplicating logic between terminal and in-session). The statusline
tier-precedence adjudication (impl_notes #12) is about *which tier source wins*, not about duplicating the
tier-word-*function*; the finding preserves the one deliberately-divergent variant, so the adjudication does not refute.

## Risks

- **Seam B is money/wire caution zone.** `server.py` resolution feeds cost + routing; extract behind a characterization
  test, never eyeball.
- **Preserve the port-bind security posture** and the divergent statusline tier precedence -- both are easy to erase in
  a naive "unify."
- Seam A ops must return structured data (no Click) or they violate §3.12 -- grep the new module.

## Metric / falsifiable prediction

Prediction: a supervisor-lifecycle change touches **1 op, not 2 command surfaces**; the next new tier (post-Fable)
touches **1 leaf, not 3**; a proxy-id-recovery fix lands once. Confirm on the next supervisor-UX PR and the next model
that rides an existing tier.

## Acceptance (per-slice)

Tick only when: (a) the collapsed logic lives in one home and callers delegate; (b) the new op imports no
`click`/`rich`/`sys.exit`; (c) the divergent statusline tier variant and the `127.0.0.1` bind are intact; (d) focused
tests + (Seam B) a cost/tier characterization test pass.

## Closeout

(pending)
