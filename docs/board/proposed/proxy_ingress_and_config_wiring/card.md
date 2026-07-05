# proxy_ingress_and_config_wiring -- server.py passthrough extraction + config/install field wiring (product calls first)

**Lane**: `proposed/` -- accepted-candidate refactor batch, **gated on product decisions** (see Open questions).
Behavior- preserving extraction and shared-field wiring. Independently shippable slices; do not start before the gating
answers.

**When accepted**: this card bundles **two separable seams** (Seam A = `server.py` passthrough-ingress extraction, a
money/wire caution zone; Seam B = config/install field wiring). Per `docs/developer/board_contract.md`, promote them as
**two member cards** (`proxy_passthrough_ingress` and `config_field_wiring`) -- or an `epic_proxy_ingress_config`
coordinator if the wire-shape leaf shared between Seam A and Seam B needs sequencing -- rather than moving the whole
batch to `doing/` at once. The caution-zone Seam A and the durable-state Seam B want independent review anyway.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; areas proxy-pkg,
install-config-backend). The anthropic-passthrough extraction ([37]) and the config/install items are auditor first-pass
evidence in a caution zone; their adversarial refuters were spend-capped. Re-verify before scheduling.

**Type**: **refactor batch card**, deliberately **not an epic**. Two seams (proxy ingress cohesion + config/install
wiring) share the theme "cohesion/placement in cap-pressured or drift-prone modules," not one contract. Splittable.

**References**: `docs/design.md` §3.7 (proxy runtime truth), §7.x (wire shape / intercept), §3.5 (ownership);
`docs/design_appendix.md` §A.11-A.12 (intercept/audit config), §C (install model); `docs/board/impl_notes.md`
("Per-proxy config blocks must be wired through BOTH loader hops"; the `responses_ingress` extraction precedent);
`docs/developer/documentation_guidelines.md` (design docs are normative -- fix stale lines).

---

## Why (the thesis)

Two cohesion/placement problems sit in modules where the cost of a mistake is high (the cap-saturated proxy server; the
durable config loaders). Both mirror a pattern the repo has already blessed elsewhere.

**Seam A -- extract the anthropic-passthrough ingress, mirroring the Responses extraction.** `proxy/server.py` is at
2494/2500 lines. The Codex-facing Responses passthrough was already extracted to `proxy/responses_ingress.py` with an
explicit comment (`server.py:1059-1062`): the handler lives there *"to keep this module's size bounded."* Its structural
twin -- `_handle_anthropic_passthrough` (~220 lines, `server.py:837`) plus `_tier_from_model_name` (`:764`) and
`_apply_passthrough_override` (`:780`) -- is still inline in the saturated module. The blessed move is to mirror the
Responses extraction into `passthrough_ingress.py`.

**Seam B -- shared config fields wired through one place, not six.** impl_notes records a recurring silent-drop bug: a
per-proxy config block reaches the running proxy through **two independent loader hops**
(`load_proxy_instance_config_from_dict` and `_proxy_instance_to_forge_config`, `config/loader.py:459-466`, `:566-579`),
plus **two dataclass field lists** and **two `__post_init__` coercion sequences** in `config/schema.py`
(`:659-664/748-753`, `:670-674/786-795`). A field added to the dataclasses but not both hops loads in unit tests yet is
silently dropped at runtime (this shipped for `provider_trace` and nearly for `logging.requests`). Three lighter items
travel with it:

- **Wire-shape vocabulary scattered as literals across 6 packages** with no owning leaf: `config/schema.py:269`
  (`_VALID_WIRE_SHAPES`), `core/reactive/env.py:62-63` (2 of 3, third missing), `proxy/responses_ingress.py:40`,
  `server.py:619/1994/2079`, `session/model_pin.py:18`, `loader.py:462`.
- **`forge info` -- a global Click/Rich dashboard command -- lives in the installer package** (`install/cli.py:23-48`)
  and re-implements the sibling claude-version parse (`install/version.py:62-84`) that `cli/main.py:416` also touches.
- **`OPENAI_MODELS` allowlist duplicates the catalog** (`config/schema.py:38-90` vs
  `core/data/model_catalog.yaml:79-741`) with no conformance guard (premature -- see Open questions).

---

## Non-goals / must-not-break

- **Do not touch `converters.py`** (Essential wire translation) and do not split the intercept/override machinery --
  Seam A extracts the *passthrough handler*, mirroring the Responses extraction, nothing more.
- **Preserve cost/metrics/provider-trace ordering.** `server.py` records spend + trace on the passthrough path; the
  extraction must keep the exact `on_complete` / `record_provider_trace` ordering (money/telemetry caution zone,
  impl_notes "every real provider call must emit a provider-trace").
- **Preserve the two-posture config validation** (impl_notes backend-identity): template load is strict; runtime
  `proxy.yaml` is warn-and-degrade. Seam B unifies the *field wiring*, not the validation posture.
- **No new user-facing behavior for `forge info`** -- Seam B moves the command's home, it does not change output.

---

## Target shape

**Seam A:**

| Extract                                                                      | Target                                                                | From                |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------- |
| `_handle_anthropic_passthrough` (~220 lines) + `_apply_passthrough_override` | new `proxy/passthrough_ingress.py` (mirror `responses_ingress.py`)    | server.py:837, :780 |
| `_tier_from_model_name`                                                      | shared with the `core/tiers.py` leaf (see ops_seam_completion Seam B) | server.py:764       |

**Seam B:**

| Concern                      | Target                                                                | Copies                                                                                                     |
| ---------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| Per-proxy block field wiring | one field registry driving both loader hops + both coercion sequences | loader.py:459/566; schema.py:659/748/670/786                                                               |
| Wire-shape vocabulary        | new `config/wire_shapes.py` leaf (all 3 shapes)                       | schema.py:269; env.py:62; responses_ingress.py:40; server.py:619/1994/2079; model_pin.py:18; loader.py:462 |
| `forge info` command         | `cli/` (its home per the command surface)                             | install/cli.py:23; reuse `install/version.py` parse                                                        |
| `OPENAI_MODELS` \<-> catalog | conformance test (or single source) -- gated                          | schema.py:38; model_catalog.yaml:79                                                                        |

---

## Phased plan (gated -- do not start before Open questions answered)

| Slice | Scope                                                                                                          | Exit signal                                                                                                    |
| ----- | -------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| B1    | `config/wire_shapes.py` leaf; repoint the 6 literal sites (env.py gains the missing 3rd shape).                | one wire-shape vocabulary; `rg` for the string literals returns the leaf + intentional matches                 |
| B2    | Field registry for the per-proxy blocks: one declaration drives both loader hops + both coercion sequences.    | a new block reaches `config.proxy` through one wiring point; a live-read test (not schema-only) proves it      |
| B3    | Move `forge info` to `cli/`; reuse `install/version.py` parse; fix the stale `InstallProfile` docstring.       | `forge info` lives in `cli/`; output byte-identical                                                            |
| A1    | Extract `passthrough_ingress.py` mirroring `responses_ingress.py`. **Gated on the caution-zone product call.** | `server.py` LOC drops well below cap; a passthrough characterization test (cost + trace + wire bytes) is green |

Order B first (lower risk); A1 only after the cap/caution decision.

## Blast radius

- **Seam A is the money/wire caution zone** on the cap-saturated `server.py`. The extraction must be provably
  behavior-preserving: identical wire bytes, identical cost/trace/metrics ordering. Characterization test first.
- **Seam B2 is durable-state wiring** -- the failure mode is a silently-dropped config block. The regression must cover
  the **live-read path** (`config.proxy.<block>.*`), not just schema coercion (impl_notes: "a schema-only test passes
  while the runtime drops it").
- `forge info` move: 1 command registration in `cli/main.py`; low.

## What was verified vs. first-pass

- **First-pass, re-verify before scheduling (Medium, caution zone):** all items ([37],[43],[46],[69],[45]). The
  Responses-extraction precedent and the impl_notes "BOTH loader hops" note make the batch credible, but the caution
  zone demands the adversarial pass + characterization tests before code moves.

## Adversarial verification (to run before scheduling)

Resume the audit workflow (`resumeFromRunId: wf_dfc2d14a-03c`) once spend resets. Briefs: (1) is the
anthropic-passthrough handler load-bearing-inline for a reason the Responses twin was not (shared closure state with the
request path)? (2) does the field-registry indirection obscure the two-posture validation the backend-identity card
protects? (3) is `forge info` in `install/` deliberate (it reads install state)?

## Risks

- **Caution zone dominates.** Seam A on money/wire; Seam B2 on durable config. Neither is a drive-by -- each needs a
  characterization/live-read test before the move.
- **`forge info` reads install state**, so the move must keep its data access intact even as the command home changes.
- **`OPENAI_MODELS` (B/[45]) is premature** -- a conformance test is cheap, but converging to a single source is a
  config decision; keep it behind the Open question.

## Metric / falsifiable prediction

Prediction: adding a per-proxy config block reaches the running proxy through **one wiring point** (the silent-drop
class is closed); a wire-shape change touches **1 leaf, not 6**; `server.py` drops comfortably below the cap after A1.
Confirm on the next per-proxy-config PR and the next wire-shape addition.

## Acceptance (per-slice)

Tick only when: (a) the collapsed vocabulary/wiring lives in one home; (b) B2 has a live-read (not schema-only) test;
(c) A1 has a passthrough characterization test asserting identical wire bytes + cost/trace ordering; (d) the gating Open
questions are answered.

## Closeout

(pending)
