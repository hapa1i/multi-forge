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

**Anchors re-verified 2026-07-26** against `main` at `fbc736b5`. One premise expired, one row was already shipped, and
one claim was wrong -- all three are corrected inline and summarized under "What was verified vs. first-pass". The
adversarial pass named below is still owed.

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

**Seam A -- extract the anthropic-passthrough ingress, mirroring the Responses extraction.** The Codex-facing Responses
passthrough was already extracted to `proxy/responses_ingress.py` with an explicit comment (`server.py:1032-1034`): the
handler lives there *"to keep this module's size bounded."* Its structural twin -- `_handle_anthropic_passthrough` (~220
lines, `server.py:810`) plus `_apply_passthrough_override` (`:753`) -- is still inline. The blessed move is to mirror
the Responses extraction into `passthrough_ingress.py`.

> **Premise correction (2026-07-26).** This card was written when `server.py` was at 2494/2500 lines and argued from cap
> saturation. PR #112 has since extracted `proxy/reasoning.py` (168 lines) *"from `server.py` for the size gate"*, so
> the module now sits at **2358/2500 -- roughly 140 lines of headroom, not 6**. Seam A is therefore a **deliberate
> cohesion refactor, not a cap emergency**, and should be prioritized as such. The argument that survives is structural:
> the passthrough handler is the inline twin of an ingress the repo already chose to extract, and it carries the
> money/wire path. The argument that expired is urgency.

**Seam B -- shared config fields wired through one place, not six.** impl_notes records a recurring silent-drop bug: a
per-proxy config block reaches the running proxy through **two independent loader hops**
(`load_proxy_instance_config_from_dict`, `config/loader.py:400` (block fields ~`:463`), and
`_proxy_instance_to_forge_config`, `:525` (~`:555`)), plus **two dataclass field lists** and **two `__post_init__`
coercion sequences** in `config/schema.py` (the `ProxyConfig` / `ProxyInstanceConfig` pair, `wire_shape` at `:664` and
`:753`). A field added to the dataclasses but not both hops loads in unit tests yet is silently dropped at runtime (this
shipped for `provider_trace` and nearly for `logging.requests`). Three lighter items travel with it:

- **Wire-shape vocabulary scattered as literals across 6 packages** with no owning leaf: `config/schema.py:273`
  (`_VALID_WIRE_SHAPES`), `core/reactive/env.py:65-66` (2 of 3, third still missing), `proxy/responses_ingress.py:40`,
  `server.py:599/1864/1885/1949`, `session/model_pin.py:18`, `loader.py:463`.
- **`forge info` -- a global Click/Rich dashboard command -- lives in the installer package** (`install/cli.py:26`,
  `info_cmd`) and re-implements the sibling claude-version parse: `install/cli.py:80-85` runs its own
  `subprocess.run(["claude", "--version"])` and strips `" (Claude Code)"`, duplicating `install/version.py:61-86`
  (`_run_claude_version`). **Corrected 2026-07-26:** this card previously named `cli/main.py:416` as a third site. That
  is wrong -- `main.py` contains no claude-version code at all (`:412` is
  `@click.version_option(package_name="multi-forge")`, the *Forge* version). The real callers of the shared parse are
  `core/runtime/registry.py:98`, `cli/extensions.py:146`, and `cli/session_lifecycle.py:270`. The duplication is a
  genuine 2-site problem, not a 3-site one.
- **`OPENAI_MODELS` allowlist duplicates the catalog** (`config/schema.py:38-94` vs the `models:` section of
  `core/data/model_catalog.yaml:75+`) with no conformance guard (premature -- see Open questions).

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

| Extract                                                                      | Target                                                             | From                |
| ---------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------- |
| `_handle_anthropic_passthrough` (~220 lines) + `_apply_passthrough_override` | new `proxy/passthrough_ingress.py` (mirror `responses_ingress.py`) | server.py:810, :753 |

> **Already shipped -- row removed (2026-07-26).** This table previously carried a third row asking to share
> `_tier_from_model_name` with the `core/tiers.py` leaf. `proxy_tier_resolvers` B1 (shipped 2026-07-06,
> `done/proxy_tier_resolvers/`) already did it: `server.py:744` is now a four-line docstring wrapper returning
> `detect_tier_word(model or "")`. Nothing is owed here. Carry the wrapper along with the extraction unchanged -- do not
> re-derive it, and note that `get_tier_from_display_name` is a *deliberate* non-unification (different fallback), per
> impl_notes.

**Seam B:**

| Concern                      | Target                                                                | Copies                                                                                                          |
| ---------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Per-proxy block field wiring | one field registry driving both loader hops + both coercion sequences | loader.py:400/525; schema.py `ProxyConfig` + `ProxyInstanceConfig` (:664/:753)                                  |
| Wire-shape vocabulary        | new `config/wire_shapes.py` leaf (all 3 shapes)                       | schema.py:273; env.py:65; responses_ingress.py:40; server.py:599/1864/1885/1949; model_pin.py:18; loader.py:463 |
| `forge info` command         | `cli/` (its home per the command surface)                             | install/cli.py:26; drop its inline parse (:80-85) for `install/version.py:61`                                   |
| `OPENAI_MODELS` \<-> catalog | conformance test (or single source) -- gated                          | schema.py:38-94; model_catalog.yaml:75+                                                                         |

---

## Phased plan (gated -- do not start before Open questions answered)

| Slice | Scope                                                                                                          | Exit signal                                                                                                                                                                                                                    |
| ----- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| B1    | `config/wire_shapes.py` leaf; repoint the 6 literal sites (env.py gains the missing 3rd shape).                | one wire-shape vocabulary; `rg` for the string literals returns the leaf + intentional matches                                                                                                                                 |
| B2    | Field registry for the per-proxy blocks: one declaration drives both loader hops + both coercion sequences.    | a new block reaches `config.proxy` through one wiring point; a live-read test (not schema-only) proves it                                                                                                                      |
| B3    | Move `forge info` to `cli/`; reuse `install/version.py` parse; fix the stale `InstallProfile` docstring.       | `forge info` lives in `cli/`; output byte-identical                                                                                                                                                                            |
| A1    | Extract `passthrough_ingress.py` mirroring `responses_ingress.py`. **Gated on the caution-zone product call.** | a passthrough characterization test (cost + trace + wire bytes) is green; the passthrough path reads as the structural peer of `responses_ingress.py`. LOC is a side effect, not the exit signal -- see the premise correction |

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

**Anchor re-verification, 2026-07-26** (`main` @ `fbc736b5`). Every code anchor was re-checked; three findings are
material, the rest were line drift now restamped inline:

| Finding                                                                                                                                                        | Effect on the card                                                       |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| **Premise expired.** `server.py` is 2358/2500, not 2494/2500 -- PR #112 extracted `proxy/reasoning.py` for the size gate.                                      | Seam A is a cohesion refactor, not a cap emergency. Priority drops.      |
| **Row already shipped.** `_tier_from_model_name` was single-sourced onto `core/tiers.py` by `proxy_tier_resolvers` B1 (2026-07-06); `server.py:744` delegates. | Seam A table row removed. Nothing owed.                                  |
| **Claim wrong, not stale.** `cli/main.py:416` does not touch the claude-version parse; `main.py` has no claude-version code at all.                            | `forge info` duplication is a 2-site problem. Real callers listed above. |

Claims that survived re-verification unchanged: both loader hops still exist and are still independent; the wire-shape
literal set is still spread across the same 6 packages; `core/reactive/env.py` still defines only 2 of the 3 shapes;
`install/cli.py` still runs its own `claude --version` parse; `OPENAI_MODELS` still has no conformance guard.

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
class is closed); a wire-shape change touches **1 leaf, not 6**; after A1 both passthrough ingresses live in peer
modules, so the next wire-shape or ingress change touches a leaf rather than the request-path module. Confirm on the
next per-proxy-config PR and the next wire-shape addition.

## Acceptance (per-slice)

Tick only when: (a) the collapsed vocabulary/wiring lives in one home; (b) B2 has a live-read (not schema-only) test;
(c) A1 has a passthrough characterization test asserting identical wire bytes + cost/trace ordering; (d) the gating Open
questions are answered.

## Closeout

(pending)
