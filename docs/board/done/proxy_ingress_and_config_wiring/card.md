# proxy_ingress_and_config_wiring -- server.py passthrough extraction + config/install field wiring

**Lane**: `done/` (2026-08-02) -- single-card execution (decision 2026-08-02: no member-card split; all verified-valid
slices shipped from this card on branch `refactor/proxy-ingress-config-wiring`). Behavior-preserving extraction and
shared-field wiring.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; areas proxy-pkg,
install-config-backend). Anchors re-verified 2026-07-26 (`fbc736b5`) and again 2026-08-02 (`34362ce2`); the previously
owed adversarial pass is resolved -- see "Open questions (resolved)".

**Type**: refactor batch card, deliberately not an epic. Two seams share the theme "cohesion/placement in drift-prone
modules," not one contract.

**References**: `docs/design.md` §3.7 (proxy runtime truth), §7.x (wire shape / intercept), §3.5 (ownership);
`docs/design_appendix.md` §A.11-A.12 (intercept/audit config), §C (install model); `docs/board/impl_notes.md`
("Per-proxy config blocks must be wired through BOTH loader hops"; "Shared cost/usage vocabulary Literals live in a
telemetry leaf" -- the eager-`__init__` trap; the `responses_ingress` extraction precedent).

---

## Why (the thesis)

Two cohesion/placement problems sit in modules where the cost of a mistake is high (the proxy server's money/wire path;
the durable config loaders). Both mirror a pattern the repo has already blessed elsewhere, and both accrued fresh drift
evidence between audits.

**Seam A -- extract the anthropic-passthrough ingress, mirroring the Responses extraction.** The Codex-facing Responses
passthrough was extracted to `proxy/responses_ingress.py` with an explicit size-bounding comment (`server.py:1033`). Its
structural twin -- `_handle_anthropic_passthrough` (~226 lines, `server.py:810`) plus `_apply_passthrough_override`
(`:753`) -- is still inline. `server.py` sits at 2358/2500 (post-PR #112 headroom), so this is a **deliberate cohesion
refactor, not a cap emergency**; the surviving argument is structural (the inline twin of an ingress the repo already
chose to extract, on the money/wire path).

**Seam B -- shared config/install duplication, now with live drift evidence:**

- **Wire-shape vocabulary scattered as code literals with no owning leaf** -- and the scatter **grew** between the
  2026-07-26 and 2026-08-02 verifications: `proxy_orchestrator.py:1033/1046/1114-1115` (the Responses-capability gate)
  and `core/runtime/codex_preflight.py:515` are new hardcoded sites the original audit never saw. Full current set:
  `config/schema.py:273` (`_VALID_WIRE_SHAPES`), `config/loader.py:463`, `core/reactive/env.py:65-66` (a half-started
  centralization -- 2 of 3 shapes as constants), `proxy/responses_ingress.py:36/40/57/99/102/111`,
  `proxy/server.py:599/1864/1949`, `session/model_pin.py:18`, plus the two new files. The card's own falsifiable
  prediction confirmed itself in the negative: every new consumer re-types the strings.
- **Per-proxy block field wiring enumerated in 4 places.** impl_notes records the silent-drop bug class (shipped for
  `provider_trace`, nearly for `logging.requests`). 2026-08-02 narrowing: the `_coerce_*` helpers are **already
  single-sourced** and both `__post_init__` sequences call the same ones -- the duplication is only the **field
  enumeration**: hop 1 `load_proxy_instance_config_from_dict` (`loader.py:455-470`), hop 2
  `_proxy_instance_to_forge_config` (`:547-560`), and the two coercion loops in `schema.py` (`ProxyConfig.__post_init__`
  ~`:670`, `ProxyInstanceConfig.__post_init__` ~`:790`).
- **`forge info`'s inline claude-version parse has already drifted from its twin.** `install/cli.py:80-85` re-implements
  `install/version.py::_run_claude_version` -- and no longer identically: version.py takes `raw.split()[0]`; cli.py
  keeps the whole stripped string. The dedup is no longer hypothetical hygiene; the copies have diverged. The command's
  registration already lives in `cli/main.py:449`; only its implementation is homed in `install/`.
- **`OPENAI_MODELS` allowlist** (`config/schema.py:38-94`) duplicates the catalog with no conformance guard -- the only
  test (`tests/src/config/test_schema.py:25-26`) iterates the allowlist against itself (circular). Scope here is a
  conformance test only; single-sourcing stays out (a config decision this card does not take).

---

## Open questions (resolved 2026-08-02)

The original card gated on an "Open questions" section that was never written; the three adversarial briefs under
"Adversarial verification" were the real gate. All three are now answered by direct code reading (the owed workflow
resume `wf_dfc2d14a-03c` is same-session-only and dead):

1. **Is the anthropic-passthrough handler load-bearing-inline for a reason the Responses twin was not?** No. The handler
   uses the same class of server-module singletons/helpers the Responses ingress already reads via documented lazy
   import (`import forge.proxy.server as server` -- `config`, `cost_tracker`, `audit_logger`, `proxy_metrics`,
   `_forge_run_ids`, `_forge_session_command`, `_backend_instance_id`, `record_provider_trace`). The lazy-import pattern
   also avoids the server\<->ingress cycle (server imports the ingress at load to register routes). The extraction
   mirrors an existing, shipped dependency shape.
2. **Does field-registry indirection obscure the two-posture validation?** No, because the registry scope is narrower
   than the original card assumed: the strict `_coerce_*` helpers are already shared, and the strict-vs-warn-degrade
   posture split lives in field-specific semantics (template load vs `proxy.yaml` runtime reads), not in the field
   enumeration. The genuinely different per-dataclass validations (provider/port/tiers/endpoint checks vs per-provider
   tier-override constraints) are **not** twins and stay explicit and untouched. B2 shares only the block-field list.
3. **Is `forge info` in `install/` deliberate?** No evidence of it. It is a global dashboard (Forge version, Claude
   version, sessions, proxies, installations); registration already sits in `cli/main.py`. The move is mechanical.

**Target correction (2026-08-02):** the vocabulary leaf moves to **`core/wire_shapes.py`**, not the originally proposed
`config/wire_shapes.py`. `forge/config/__init__.py` eagerly imports the loader, so a config-homed leaf would drag the
loader into `core/reactive/env.py` and `session/model_pin.py` -- the exact eager-`__init__` trap impl_notes records for
`core/telemetry/vocabulary.py`. `core/__init__.py` imports only `paths`; the leaf matches the `core/tiers.py` /
`core/effort.py` / `core/provider_types.py` precedent.

---

## Non-goals / must-not-break

- **Do not touch `converters.py`** (essential wire translation) and do not split the intercept/override machinery --
  Seam A extracts the *passthrough handler*, mirroring the Responses extraction, nothing more.
- **Preserve cost/metrics/provider-trace ordering.** `server.py` records spend + trace on the passthrough path; the
  extraction must keep the exact `on_complete` / `record_provider_trace` ordering (impl_notes: "every real provider call
  must emit a provider-trace").
- **Preserve the two-posture config validation** (impl_notes backend-identity): template load is strict; runtime
  `proxy.yaml` reads warn-and-degrade where designed. Seam B unifies the *field enumeration*, not validation posture,
  and never merges the per-dataclass unique validations.
- **No new user-facing behavior for `forge info`** -- the move changes the command's home, not its output. `--json`
  shape and human output stay byte-identical (modulo the version-parse fix below).
- **The version-parse dedup is allowed to change `forge info`'s parsed value** where the copies drifted: adopting
  `_run_claude_version` means `forge info` now reports the first token (e.g. `2.1.197`) like every other caller, instead
  of the whole stripped string. This is a bug fix (the drift), not a compatibility break to preserve.
- **`get_tier_from_display_name` stays a deliberate non-unification** (different fallback); carry the existing
  `detect_tier_word` wrapper along with the A1 extraction unchanged.

---

## Target shape

| Slice | Concern                      | Target                                                                            | Copies today                                                                                                                                         |
| ----- | ---------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1    | Wire-shape vocabulary        | `core/wire_shapes.py` leaf (all 3 shapes + validity tuple)                        | schema.py:273; loader.py:463; env.py:65-66; responses_ingress.py x6; server.py x3; model_pin.py:18; proxy_orchestrator.py x4; codex_preflight.py:515 |
| B3    | `forge info` home + parse    | command implementation in `cli/`; parse via `install/version.py`                  | install/cli.py:26 (home), :80-85 (drifted parse copy)                                                                                                |
| B2    | Per-proxy block field wiring | one shared block-field declaration driving both loader hops + both coercion loops | loader.py:455-470/:547-560; schema.py two `__post_init__` coercion sequences                                                                         |
| B4    | `OPENAI_MODELS` conformance  | conformance test against `model_catalog.yaml` (no single-sourcing)                | schema.py:38-94 vs core/data/model_catalog.yaml                                                                                                      |
| A1    | Passthrough ingress          | new `proxy/passthrough_ingress.py` mirroring `responses_ingress.py`               | server.py:753 + :810 (~226 lines)                                                                                                                    |

## Phased plan

| Slice | Scope                                                                                                | Exit signal                                                                                                                                                                |
| ----- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1    | `core/wire_shapes.py` leaf; repoint every code-literal site (env.py's half-centralization folds in). | one wire-shape vocabulary; `rg` for the string literals returns the leaf + docstrings/error-text only                                                                      |
| B3    | Move `forge info` implementation to `cli/`; drop the inline parse for `install/version.py`.          | `forge info` implementation lives in `cli/`; output identical except the version token fix; one claude-version parse in src/                                               |
| B2    | Shared block-field declaration drives both loader hops + both coercion loops.                        | a new block reaches `config.proxy` through one wiring point; a live-read test (not schema-only) proves it; per-dataclass unique validations untouched                      |
| B4    | Conformance test: `OPENAI_MODELS` entries cross-checked against the catalog.                         | drift between allowlist and catalog fails a test instead of passing silently                                                                                               |
| A1    | Extract `passthrough_ingress.py` mirroring `responses_ingress.py`. Characterization test **first**.  | passthrough characterization (wire bytes + cost/trace/metrics ordering) green before and after the move; the module reads as the structural peer of `responses_ingress.py` |

Order: B1 -> B3 -> B2 -> B4 -> A1 (lowest risk first; the money/wire caution zone last, behind its characterization
test).

## Blast radius

- **A1 is the money/wire caution zone.** The extraction must be provably behavior-preserving: identical wire bytes,
  identical cost/trace/metrics ordering. Characterization test first; proxy integration tests before closing.
- **B2 is durable-state wiring** -- the failure mode is a silently-dropped config block. The regression must cover the
  **live-read path** (`config.proxy.<block>.*`), not just schema coercion.
- **B1 touches 8 files** but is a mechanical constant repoint; the leaf has no imports beyond `typing`.
- **B3** is 1 command registration + 1 implementation move + 1 parse dedup; low, but the drifted parse means output can
  change (documented above as a fix).

## Metric / falsifiable prediction

Adding a per-proxy config block reaches the running proxy through **one wiring point** (the silent-drop class is
closed); a wire-shape change touches **1 leaf, not 8+ files**; after A1 both passthrough ingresses live in peer modules,
so the next wire-shape or ingress change touches a leaf rather than the request-path module. Confirm on the next
per-proxy-config PR and the next wire-shape addition.

## Acceptance (per-slice)

Tick only when: (a) the collapsed vocabulary/wiring lives in one home; (b) B2 has a live-read (not schema-only) test;
(c) A1 has a passthrough characterization test asserting identical wire bytes + cost/trace ordering, green before and
after the move; (d) `make test-unit` green per slice, relevant proxy integration tests green before closeout.

## Verification history

- **2026-07-26** (`fbc736b5`): premise expired (`server.py` 2358/2500, not 2494 -- PR #112), `_tier_from_model_name` row
  already shipped (`proxy_tier_resolvers` B1), `cli/main.py:416` claim wrong (no claude-version code there).
- **2026-08-02** (`34362ce2`): all surviving anchors re-confirmed. New findings: wire-shape scatter grew by two files
  (`proxy_orchestrator.py`, `codex_preflight.py`); `server.py` literal sites now 3 (`:1885` gone); the `forge info`
  parse copy has **drifted** from `_run_claude_version` (`split()[0]` vs whole string); the `_coerce_*` helpers are
  already shared, narrowing B2 to field enumeration only; the three adversarial briefs answered by code reading (see
  Open questions); leaf target corrected `config/` -> `core/` (eager-`__init__` trap).

## Closeout

Completed 2026-08-02 on `refactor/proxy-ingress-config-wiring`. All five slices shipped (B1 `core/wire_shapes.py` leaf,
B3 `forge info` -> `cli/info.py` + version-parse dedup, B2 `PROXY_BLOCK_COERCERS` registry, B4 `OPENAI_MODELS`
conformance test, A1 `proxy/passthrough_ingress.py` extraction). Three bugs surfaced by the card's own guards:
template-`costs` drop in `create_proxy_file`, `gpt-5.5-pro` allowlist drift, and a pre-existing
`proxy_server_local_openai` fixture that never routed `litellm_local`. Post-review hardening added the bidirectional
shared-field drift guard and the streaming accounting-order characterization (see `checklist.md`). Verification: full
unit suite green, proxy integration gate 12/12, `make pre-commit` clean. Change-log entry recorded; design.md §6 map
updated with `core/wire_shapes.py`.
