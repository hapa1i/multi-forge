# T0 -- Claude subscription billing signal (does `claude -p` ride Max? + honest `billing_mode`)

**Epic**: `docs/board/doing/epic_consumer_lanes/` (member **T0**, the sibling billing cleanup; independent of the first
wave, **load-bearing for a future `claude-max` lane**).

**Type**: Member card. Probe-first investigation + (conditional) billing-signal implementation. T0 answers an empirical
question the epic deferred -- *does a headless `claude -p` actually ride a Claude Max/Pro subscription, and can Forge
detect it locally?* -- and makes Forge's `billing_mode` honest about the answer.

**Status**: Card authored 2026-06-29 on branch `claude_subscription_billing`; revised same day after review (the
detection-signal risk, Phase-1 caller count, keyless precondition, and lane decision). **Awaiting plan review before any
implementation** -- nothing committed; no `src/` change exists; Phase 0 is an operator-gated probe.

**Lane decision (resolved)**: stays in `doing/`. board_contract's todo/-vs-doing/ discriminator is "todo/ means *no
execution branch is active*"; an execution branch exists and the epic coordinates T0 as the active (gated) cursor, so
`doing/` is contract-correct. The status above makes the "no code yet" state explicit so this is not misread as coding
in flight.

---

## Problem

The epic's one-line sketch (epic `card.md`, "T0 -- sibling billing cleanup") reads: *"revisit the `claude -p`
`unknown`/OAuth billing assumption (`billing.py`) against current Anthropic `-p` billing -- likely stale on the Claude
side."* A code-grounded sweep (2026-06-29) refines that framing.

### Framing correction (verified 2026-06-29)

`infer_billing_mode` is **not buggy or stale** -- it is conservative *by design*, and correct for what Forge emits
today:

- `infer_billing_mode(*, direct, has_api_key)` returns `"api"` **iff** `direct and has_api_key`, else `"unknown"`; its
  docstring is explicit that "a guessed billing mode is worse than an honest don't-know" and that it **never guesses
  subscription modes** (`core/usage/billing.py:14-28`).
- A **key-resolvable** headless run (key in env *or* credential file) auto-adds **`--bare`** and authenticates with that
  key (`core/reactive/session_runner.py:123-125,183`; `can_use_bare(env)` checks the *hydrated* env -- test
  `test_session_runner.py:209`), so it is *genuinely* API-billed and `"api"` is the correct label.
- A **keyless** headless run (no key anywhere) intentionally **omits `--bare`** so Claude *can* fall through to
  OAuth/keychain auth (`core/reactive/session_runner.py:183,208-213` -- the missing-key guard fires only for explicit
  `bare=True`; the `bare=None` comment notes the fallthrough "may be intentional"; test `test_session_runner.py:200`).
  But omitting `--bare` only **permits** OAuth -- it is **not proof** that `claude -p` actually performs OAuth in a
  non-TTY context (design_workflows §3.4 says only that `--bare` *disables* OAuth, not that `-p` *enables* it
  headlessly). Today such a run is labeled `"unknown"` (`_anthropic_key_present()` is False) -- **honest but
  unclassified, not a mislabel.** Whether that path can even authenticate, and how to classify it, is the whole of T0.

The real gap is **shape and coverage, not correctness**:

1. **`has_api_key` is a capability, not a payer.** `infer_billing_mode`'s only subscription-relevant input is "is a key
   resolvable," which cannot distinguish key-billed from subscription-billed when both exist. The status line already
   encodes this exact rule -- it refuses to infer an API payer from `ANTHROPIC_API_KEY` presence
   (`cli/statusline/context.py:139-151`; design_appendix **§A.8** "Billing-aware cost": billing mode is "an explicit
   declaration, never inferred from a key"). So the inference function is the **wrong shape** for subscription
   detection.
2. **No Claude subscription signal exists at all.** A `src/`-wide search finds **no** Anthropic OAuth/subscription
   detection (`sk-ant-oat`, keychain, `claude setup-token`, `claude config get`, `credentials.json`) -- only the generic
   `_anthropic_key_present()` (`core/usage/emit.py:549-556`). Forge has no way to know a `claude -p` run is
   subscription-authed.
3. **The reserved modes are empty on the Claude side.** `BillingMode` already declares
   `subscription_interactive | subscription_headless_credit | subscription_quota` (`core/usage/ledger.py:66-72`,
   design_appendix §A.13), but only **Codex** emits a subscription mode today.

So T0 is not "fix `billing.py`." It is: **prove whether the already-allowed keyless OAuth path actually rides the Max
subscription, and if so add a preflight-resolved subscription signal** (mirroring the codex sibling) so the `claude-max`
lane the epic wants can claim `subscription_quota`/`subscription_headless_credit` honestly. No runner change is needed
to *reach* the keyless path -- the gap is classification, not plumbing.

## The proven sibling (the pattern to mirror -- and where the analogy breaks)

Codex already does this for the ChatGPT subscription, and it is the template:

- `_resolve_codex_auth()` reads `codex doctor --json` presence booleans and maps the auth **method** to a billing mode
  **at preflight** (statically declarable, not per-invocation), **key first**: `stored API key` -> `api` *before*
  `stored ChatGPT tokens` -> `subscription_quota` (`core/runtime/codex_preflight.py:365-403`).
- The `chatgpt` `ModelSource` then declares `billing_posture="subscription_quota"`, `endpoint=runtime_native()`,
  `reachable_via=("codex",)` (`backend/sources.py`).

The architectural lesson ports: **resolve billing where the auth method is known (preflight), not re-derived from
`has_api_key` at emit time** -- so T0 is a Claude auth-posture resolver, not a new branch in `infer_billing_mode`.

**Caveat -- the analogy has a hole (this is the MEDIUM risk).** Codex works because `codex doctor --json` is a
*first-class, structured* auth-diagnostic contract. Claude Code has **no known equivalent** (a `src/`-wide search
confirms Forge reads no `claude doctor`/`config get`/`credentials.json` today). So the *pattern* ports, but the *signal
it reads does not* -- T0's hardest question is whether a **stable** Claude-side signal even exists (Open question Q1).

## The empirical question (Phase 0 -- the gate)

Everything downstream depends on facts nobody has verified. Workweave/Avengers-Pro corroborates the **economic shape**
is real -- consumer subscriptions *can* be billed for headless work -- but it does so by **forwarding** a token
(`sk-ant-oat`) through a proxy *it owns*, which is a **different problem** from Forge **reading** a subscription signal
it does **not** own. So workweave validates that the lane is worth wanting; it does **not** validate that Forge can
detect the lane locally. Phase 0 is an operator-gated probe harness (mirroring `scripts/experiments/openrouter/` + the
codex probes) that establishes, in order:

- **(a0) Feasibility (gates everything else)**: can `claude -p` perform OAuth/subscription auth **at all** in a non-TTY
  headless context? "Omits `--bare`" only *permits* it; OAuth classically needs a browser/TTY. If a pre-authenticated
  Max session is **not** usable by headless `-p`, the subscription lane is architecturally impossible (kill #1).
- **(a) Auth**: given (a0), does a **keyless** `claude -p` actually complete a turn via the Max/Pro session? (The runner
  already produces the keyless path; **no runner change is in scope** -- `session_runner.py:183`, test
  `test_session_runner.py:200`.)
- **(b) Billing**: when it does, does the `--output-format json` envelope report a dollar `cost` (API-equivalent) or
  usage-but-no-cost (subscription/quota)? (Phase 5 already records the no-cost envelope as
  `provider_usage_exact`/`unavailable` -- design §3.14 -- so the *cost* honesty exists; only the `billing_mode` label is
  missing.)
- **(c) Detection signal + stability (the soft spot)**: what *local*, *programmatic*, *stable* signal distinguishes a
  subscription-authed `claude` from a key-authed one? Enumerate each candidate **with its failure mode**:
  `claude config get` (no documented stable JSON contract), reading `~/.claude/credentials.json` / OS keychain
  (OS-specific, a schema Forge does not own and Anthropic can change), or an **envelope-cost-null runtime probe**
  (works, but it is a *runtime* signal, not a *preflight* one -- it can only classify *after* a billed turn, unlike
  codex's pre-dispatch `doctor`). Report which (if any) is stable enough to depend on.
- **(d) Quota draw** (optional, informs T5/T7): does the run draw down Max quota / surface rate-limit headroom?

### Kill criterion (three distinct outcomes -- do not conflate)

1. **Architectural blocker (full kill).** (a0)/(a) show headless `claude -p` **cannot** authenticate via a Max session
   at all (always needs an API key; no non-TTY OAuth). The `claude-max` *subscription* lane is impossible; T0 narrows to
   documenting the finding and closing the question in the epic.
2. **Brittle-signal no-go (Phase-1 kill).** (a)/(b) positive, but (c) yields **only** unstable signals (no stable
   preflight signal; only an after-the-fact runtime probe or an unowned-schema read). *Labeling* is then too unreliable
   to ship: record the finding, do **not** emit a guessed `subscription_*` (that violates the module's honest-don't-know
   contract). A runtime-only `unavailable`-cost note may be documented as future work.
3. **Per-token-billed (labeling decision, not a kill).** Keyless auth *succeeds* but (b) shows it is still
   per-token/API-equivalent billed. The *path* works but offers no billing arbitrage -- keep `api`/`unknown`; the lane
   may still have non-billing value (fidelity/decorrelation), tracked separately.

## Proposed approach (phases; 1+ gated on Phase 0)

| Phase                                                                      | Scope                                                                                                                                                                                                                                     | Gated on         |
| -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| **0 -- Probe**                                                             | Operator-gated harness under `scripts/experiments/`; `phase0-results.md` answers (a0)-(d). No `src/` change.                                                                                                                              | --               |
| **1 -- Auth-posture resolver + thread it**                                 | Preflight-style resolver classifies a run's auth method from the Phase 0 (c) signal (mirrors `_resolve_codex_auth`), **only when `can_use_bare` is False** (key wins). Thread the posture through all four emit callers (Option A below). | Phase 0 positive |
| **2 -- `claude-max` ModelSource** *(scope decision -- may be a follow-on)* | Add the `claude-max` source (`runtime_native`, `reachable_via=("claude_code",)`). **Prereq:** extend `BillingPosture` if credit semantics are chosen (it lacks `subscription_headless_credit` today).                                     | Phase 1          |

Phase 0 ships no `src/` change (like the openrouter Phase 0). Phases 1-2 are sketched for review, **not** committed-to
until the probe lands.

**Phase 1 integration (Option A -- resolve once, thread it).** The card's own architecture ("resolve billing where the
auth method is known, at preflight") means: resolve the auth posture **once at session start** (where `can_use_bare` is
known) and thread it as a new `resolved_billing_mode` argument through **all four** `emit_usage_for_session_result`
callers -- `supervisor.py:578`, `memory_writer.py:526`, `shadow_curation.py:306`, `team/handlers.py:249` -- *not*
re-derived inside `emit`. Each caller computes its own `direct`/`base_url` today, so the posture must ride alongside.
**Precedence (codex-style):** yield a `subscription_*` mode **only when `can_use_bare` is False**, so a machine with
both an API key and a Max session is never mislabeled subscription (the key wins, exactly as codex checks
`stored API key` before `stored ChatGPT tokens`). **Omitting any of the four callers** silently leaves that consumer
labeling subscription runs `unknown` -- an acceptance test must cover all four.

## Scope

**In**: the Phase 0 probe + findings doc; (conditional on a positive probe) the Claude auth-posture resolver + honest
`billing_mode` emission threaded through all four emit callers.

**Out (this card)**: placing any *consumer* on the `claude-max` lane (T6-style wiring); the subscription-exhaustion
fail-open (T7); changing interactive-session billing *display* (status-line `cost_mode` stays a user declaration); any
local price/cost inference (forbidden -- design §3.14). The `claude-max` `ModelSource` (Phase 2) is **in scope only if**
review agrees; otherwise it is the unblocked follow-on.

## Open questions (for review)

1. **Detection-signal stability (the MEDIUM soft spot -- biggest risk).** The card leans on the codex
   `_resolve_codex_auth` analogy, but codex has a first-class `codex doctor --json` contract and **Claude has no known
   equivalent**. Two compounding unknowns: **(i)** can `claude -p` even do **non-TTY OAuth** (Phase 0 a0)? -- omitting
   `--bare` only *permits* OAuth, and §3.4 only says `--bare` *disables* it; **(ii)** every candidate **local** signal
   is brittle (`config get` = no stable JSON; `credentials.json`/keychain = unowned, OS-specific schema; cost-null =
   runtime-only, not preflight). **"Only brittle signals exist" is itself a Phase-1 no-go** (kill #2). Resolve the
   tolerance for a runtime-only (non-preflight) signal before Phase 1.
2. **Phase 2 (`claude-max` `ModelSource`) -- in T0 or a follow-on?** The epic says T0 "gates" (= *unblocks*) it.
   Recommendation: keep T0 = probe + billing signal; split the source to a thin follow-on. **Prerequisite either way:**
   `BillingPosture` (`backend/sources.py:24`) is `Literal["per_token","subscription_quota","free"]` -- it has **no**
   `subscription_headless_credit`, so credit semantics require extending that type before a `claude-max` source can
   carry it.
3. **Which `billing_mode` value?** Leaning **`subscription_headless_credit`** -- the `BillingMode` enum literal is
   *named* for exactly this (headless work on subscription credit) and keeps it distinct from codex's
   `subscription_quota`. Still probe-decided by (b); flagged because it affects both `BillingMode` (invocation)
   semantics and the `BillingPosture` gap above.

## Verified touchpoints (file:line, 2026-06-29)

| Concern                                     | Location                                                                                                                             | Current behavior                                                                                                                                      |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Inference function (the "stale" claim)      | `core/usage/billing.py:14-28`                                                                                                        | `"api"` iff `direct and has_api_key`, else `"unknown"`; never subscription                                                                            |
| Sole inference caller                       | `core/usage/emit.py:137` (`emit_usage_for_session_result`)                                                                           | `infer_billing_mode(direct=direct and not base_url, has_api_key=_anthropic_key_present())`                                                            |
| Emit callers to thread (Phase 1, Option A)  | `policy/semantic/supervisor.py:578`, `session/memory_writer.py:526`, `session/shadow_curation.py:306`, `policy/team/handlers.py:249` | four independent call sites, each computes `direct`/`base_url` itself -- **all** must thread `resolved_billing_mode`                                  |
| Key-presence check                          | `core/usage/emit.py:549-556` (`_anthropic_key_present`)                                                                              | `resolve_env_or_credential("ANTHROPIC_API_KEY")` -- capability, not payer                                                                             |
| Headless `--bare`/auth decision             | `core/reactive/session_runner.py:123-125,183,208-213`; tests `test_session_runner.py:200,209`                                        | `--bare` auto-added **only when a key is resolvable** (`can_use_bare(env)`); keyless runs omit `--bare`, *permitting* (not proving) OAuth fallthrough |
| `BillingMode` enum                          | `core/usage/ledger.py:66-72`                                                                                                         | `subscription_*` declared; only `subscription_quota` emitted (codex)                                                                                  |
| `BillingPosture` gap (Phase 2 prereq)       | `backend/sources.py:24`                                                                                                              | `Literal["per_token","subscription_quota","free"]` -- **no `subscription_headless_credit`**                                                           |
| Proven codex sibling (key-first precedence) | `core/runtime/codex_preflight.py:365-403` (`_resolve_codex_auth`)                                                                    | `stored API key` -> `api` **before** `stored ChatGPT tokens` -> `subscription_quota`, at **preflight**                                                |
| Headless key hydration                      | `core/reactive/env.py` (`_hydrate_credentials`, `build_claude_env`)                                                                  | injects a credential-file key when resolvable (so `can_use_bare` sees it); no key anywhere -> keyless OAuth path                                      |
| Status-line billing rule                    | `cli/statusline/context.py:139-151`; design_appendix **§A.8**                                                                        | declarative `cost_mode`; never infers payer from key presence                                                                                         |
| Reserved subscription modes                 | design_appendix **§A.13**                                                                                                            | lists `subscription_*` `BillingMode` values (enum doc, not the key-presence rule)                                                                     |
| No structured claude auth diagnostic        | (`src/`-wide: no `claude doctor`/`config get`/`credentials.json`)                                                                    | Forge has no codex-`doctor` equivalent to read -- the MEDIUM detection risk                                                                           |
