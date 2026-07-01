# T0 -- Claude subscription billing signal (does `claude -p` ride Max? + honest `billing_mode`)

**Epic**: `docs/board/done/epic_consumer_lanes/` (member **T0**, the sibling billing cleanup; independent of the first
wave, **load-bearing for a future `claude-max` lane**).

**Type**: Member card. Probe-first investigation + (conditional) billing-signal implementation. T0 answers an empirical
question the epic deferred -- *does a headless `claude -p` actually ride a Claude Max/Pro subscription, and can Forge
detect it locally?* -- and makes Forge's `billing_mode` honest about the answer.

**Status**: **Done** -- shipped in PR #58 (`b0614325`, 2026-06-29) and closed out to `done/`. **Phase 0 probe built and
run on a live Claude Max box (2026-06-29); outcome = PROCEED** (see `phase0-results.md`): keyless `claude -p` rides Max
headlessly, and the dependable detection signal is `can_use_bare` (Forge's own key-resolvability predicate), not any run
artifact. Phases 1+2 (auth-posture resolver + `claude-max` `ModelSource`) shipped: a keyless direct run bound to
`claude-max` now emits `billing_mode="subscription_quota"`, threaded through all four emit callers.

**Lane decision (resolved)**: closed to `done/` at completion (PR #58). While active it stayed in `doing/` --
board_contract's todo/-vs-doing/ discriminator is "todo/ means *no execution branch is active*"; an execution branch
existed and the epic coordinated T0 as the active cursor, so `doing/` was contract-correct.

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
  unclassified, not a mislabel.** **Phase 0 (2026-06-29) now answers this: the keyless path DOES authenticate via the
  Max session headlessly, so the honest label is a subscription mode, not `"unknown"`** -- that relabel is Phase 1.

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
lane the epic wants can claim `subscription_quota` honestly (Q3, resolved). No runner change is needed to *reach* the
keyless path -- the gap is classification, not plumbing.

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
  subscription-authed `claude` from a key-authed one? Candidates enumerated **with failure modes**: `claude config get`
  (no documented stable JSON contract -- and the live run showed it *hangs* non-TTY), `~/.claude/credentials.json` / OS
  keychain (OS-specific, unowned schema), and an envelope-cost-null runtime probe (*does not even fire* -- the live run
  showed cost is **present** on Max). **Resolved (2026-06-29): the dependable signal is `can_use_bare` itself** --
  Forge's own key-resolvability predicate (keyless => rides OAuth/subscription; keyed => `--bare` => api). It is
  preflight, Forge-owned, and needs no unowned external schema. The (c) question is detected from the run's *input*, not
  its artifacts.
- **(d) Quota draw** (optional, informs T5/T7): does the run draw down Max quota / surface rate-limit headroom?

### Kill criterion (three distinct outcomes -- do not conflate)

1. **Architectural blocker (full kill).** (a0)/(a) show headless `claude -p` **cannot** authenticate via a Max session
   at all (always needs an API key; no non-TTY OAuth). The `claude-max` *subscription* lane is impossible; T0 narrows to
   documenting the finding and closing the question in the epic.
2. **Brittle-signal no-go (Phase-1 kill).** (a)/(b) positive, but (c) yields **only** unstable signals (no stable
   preflight signal; only an after-the-fact runtime probe or an unowned-schema read). *Labeling* is then too unreliable
   to ship: record the finding, do **not** emit a guessed `subscription_*` (that violates the module's honest-don't-know
   contract). A runtime-only `unavailable`-cost note may be documented as future work.
3. **Per-token-billed (labeling decision, not a kill).** Originally framed as "keyless succeeds but (b) shows per-token
   billing." **The live run refutes the (b) test:** `total_cost_usd` is present even on Max ($0.04, an estimate), so
   cost-presence is **not** evidence of per-token billing on a keyless run -- with no key there is nothing to bill an
   API. This outcome therefore only applies to a metered-console-OAuth account (not Max/Pro), which the envelope cannot
   reveal; it needs out-of-band proof (Q3). For a **declared** Max lane, keyless + completed => subscription; an
   **undeclared** keyless run stays `unknown` -- `can_use_bare` can't see the account's plan (see Phase 1).

## Proposed approach (phases; 1+ gated on Phase 0)

| Phase                                                        | Scope                                                                                                                                                                                                                                                                                                     | Gated on         |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| **0 -- Probe**                                               | Operator-gated harness under `scripts/experiments/`; `phase0-results.md` answers (a0)-(d). No `src/` change.                                                                                                                                                                                              | --               |
| **1 -- Auth-posture resolver + thread it**                   | Preflight-style resolver (mirrors `_resolve_codex_auth`). `can_use_bare` False is a **necessary gate** (key wins) but **not sufficient**: emit `subscription_*` only when a `claude-max` declaration is in scope, else `unknown`. Thread the posture through all four emit callers (Option A below).      | Phase 0 positive |
| **2 -- `claude-max` ModelSource** *(now coupled to Phase 1)* | Add the `claude-max` source (`runtime_native`, `reachable_via=("claude_code",)`, `billing_posture="subscription_quota"`); this declaration **is** what Phase 1 needs, so Phase 1 emits `unknown` until it exists. No `BillingPosture` change needed (Q3 = `subscription_quota`, already a valid posture). | Phase 1          |

Phase 0 ships no `src/` change (like the openrouter Phase 0). Phases 1-2 are sketched for review, **not** committed-to
until the probe lands.

**Phase 1 integration (Option A -- resolve once, thread it).** The card's own architecture ("resolve billing where the
auth method is known, at preflight") means: resolve the auth posture **once at session start** (where `can_use_bare` is
known) and thread it as a new `resolved_billing_mode` argument through **all four** `emit_usage_for_session_result`
callers -- `supervisor.py:578`, `memory_writer.py:526`, `shadow_curation.py:306`, `team/handlers.py:249` -- *not*
re-derived inside `emit`. Each caller computes its own `direct`/`base_url` today, so the posture must ride alongside.
**Precedence + the label gate (reframed 2026-06-29).** `can_use_bare` False is **necessary but not sufficient**. It is
the *gate* -- a resolvable key wins (key present => `api`, exactly as codex checks `stored API key` before
`stored ChatGPT tokens`) -- but it only proves the run takes the OAuth *path*, **not** that the account is a paid
subscription: it cannot see Free/Pro/Max, and (unlike codex's `stored ChatGPT tokens` credential-*type* signal) Claude
exposes no equivalent. So the durable `subscription_*` **label** requires an explicit declaration -- the `claude-max`
lane / operator-declared `billing_posture` (Phase 2) -- consistent with §A.8 ("an explicit declaration, never
inferred"). Absent a declaration, keyless OAuth stays **`unknown`** (the module's honest-don't-know contract).
Consequence: **Phase 1 alone can only emit `unknown`; the `claude-max` declaration (Phase 2) is what lights up the
label**, so the two couple. **Omitting any of the four callers** (`supervisor.py:578`, `memory_writer.py:526`,
`shadow_curation.py:306`, `team/handlers.py:249`) silently leaves that consumer at `unknown` -- an acceptance test must
cover all four.

## Scope

**In**: the Phase 0 probe + findings doc; the Claude auth-posture resolver + honest `billing_mode` emission threaded
through all four emit callers; the `claude-max` `ModelSource` (Phase 2, Q2 resolved at plan review -- all-four billing
chosen, so the source ships in T0); and the **supervisor** billing-declaration UX
(`forge policy supervisor set --backend claude-max`) -- backend selection, since `--runtime` cannot pick `claude-max`
(it shares the `claude_code` runtime).

**Out (this card)**: T6-style *dispatch* wiring (routing a consumer's *execution* through a non-default lane transport
-- `claude-max` shares the `claude_code` runtime, so dispatch is byte-identical; only the billing *label* moves); the
operator declaration CLI + binding freeze for the three non-supervisor consumers (their billing *mechanism* ships now;
the declaration UX is a follow-on -- bindable programmatically/in tests); the subscription-exhaustion fail-open (T7);
changing interactive-session billing *display* (status-line `cost_mode` stays a user declaration); any local price/cost
inference (forbidden -- design §3.14).

## Open questions (for review)

1. **Detection-signal stability (was the MEDIUM soft spot) -- RESOLVED 2026-06-29.** The fear was that Claude has no
   `codex doctor` equivalent and every Claude-side artifact signal is brittle (`config get` = no stable JSON / hangs;
   `credentials.json`/keychain = unowned schema; cost-null = doesn't fire, cost is present on Max). **Resolution: don't
   read a Claude-side artifact at all** -- the discriminator is `can_use_bare` (Forge's own predicate): keyless +
   completing turn => the stored OAuth *path* (a subscription **candidate**; the durable label needs a declared
   `claude-max`); keyed => api. Preflight, Forge-owned, stable. **(i)** non-TTY OAuth works (a0 confirmed); **(ii)** the
   signal is the *input* (is a key resolvable?), not a brittle artifact. The kill #2 risk did not materialize.
2. **Phase 2 (`claude-max` `ModelSource`) -- in T0 or a follow-on? RESOLVED 2026-06-29: in T0.** At plan review the user
   chose all-four-consumer billing, so the source ships in this card (not a follow-on). No `BillingPosture` change (Q3 =
   `subscription_quota`, `backend/sources.py:24` already carries it) -- the `claude-max` source declares
   `billing_posture="subscription_quota"`, exactly like `chatgpt`.
3. **Which `billing_mode` value? RESOLVED 2026-06-29: `subscription_quota`** (reverses the earlier
   `subscription_headless_credit` lean). Decisive evidence: the existing headless consumer-subscription case --
   `codex exec` -- already maps to `subscription_quota`, with the comment *"Consumer ChatGPT is provably
   quota/credit-billed"* (`codex_preflight.py:401-403`). The codebase already folds "credit" semantics **into**
   `subscription_quota`; Claude Max headless is the exact analog. Reinforcing: the epic anticipated it ("a claude-max
   source must not claim `subscription_quota` until T0 proves it" -- now proven); `subscription_quota` is the only
   subscription mode with a defined consumer (the other two literals carry no docstring/semantics); `BillingPosture`
   already carries `subscription_quota` so the Phase 2 "extend `BillingPosture`" prereq **evaporates**; and Claude Max
   is a usage-quota subscription (headless `-p` draws the same Max limits, not a separate credit pool). The lean was
   purely nominal -- "credit" implies a pool that does not exist. **Caveat:** (d) quota-draw was not measured; if
   Anthropic ever exposes a *distinct* headless-credit meter, revisit. **Follow-on:** `subscription_headless_credit` now
   has no consumer -- a removal candidate (`subscription_interactive` stays reserved for possible interactive-Max
   labeling).

## Verified touchpoints (file:line, 2026-06-29)

> **Pre-implementation snapshot** -- the code state that *motivated* Phase 1, not shipped behavior. Phase 1 has since
> landed: the inference caller now calls `resolve_billing_mode(..., backend_id=...)` (row updated below). For shipped
> behavior see the change log and design §3.14 / appendix §A.13.

| Concern                                     | Location                                                                                                                             | Current behavior                                                                                                                                                                                                                                            |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Inference function (the "stale" claim)      | `core/usage/billing.py:14-28`                                                                                                        | `"api"` iff `direct and has_api_key`, else `"unknown"`; never subscription                                                                                                                                                                                  |
| Inference caller (resolver, shipped)        | `core/usage/emit.py` (`emit_usage_for_session_result`)                                                                               | **shipped Phase 1:** `resolve_billing_mode(direct=direct and not base_url, has_api_key=_anthropic_key_present(), backend_id=backend_id)` (was `infer_billing_mode(...)`)                                                                                    |
| Emit callers to thread (Phase 1, Option A)  | `policy/semantic/supervisor.py:578`, `session/memory_writer.py:526`, `session/shadow_curation.py:306`, `policy/team/handlers.py:249` | four independent call sites, each computes `direct`/`base_url` itself -- **all** must thread `resolved_billing_mode`                                                                                                                                        |
| Key-presence check                          | `core/usage/emit.py:549-556` (`_anthropic_key_present`)                                                                              | `resolve_env_or_credential("ANTHROPIC_API_KEY")` -- capability, not payer                                                                                                                                                                                   |
| Headless `--bare`/auth decision             | `core/reactive/session_runner.py:123-125,183,208-213`; tests `test_session_runner.py:200,209`                                        | `--bare` auto-added **only when a key is resolvable** (`can_use_bare(env)`); keyless runs omit `--bare`, *permitting* (not proving) OAuth fallthrough                                                                                                       |
| `BillingMode` enum                          | `core/usage/ledger.py:66-72`                                                                                                         | `subscription_*` declared; only `subscription_quota` emitted (codex)                                                                                                                                                                                        |
| `BillingPosture` (Q3 resolved -> no gap)    | `backend/sources.py:24`                                                                                                              | `Literal["per_token","subscription_quota","free"]` already carries `subscription_quota`; Q3 = quota, so no extension needed                                                                                                                                 |
| Proven codex sibling (key-first precedence) | `core/runtime/codex_preflight.py:365-403` (`_resolve_codex_auth`)                                                                    | `stored API key` -> `api` **before** `stored ChatGPT tokens` -> `subscription_quota`, at **preflight**                                                                                                                                                      |
| Headless key hydration                      | `core/reactive/env.py` (`_hydrate_credentials`, `build_claude_env`)                                                                  | injects a credential-file key when resolvable (so `can_use_bare` sees it); no key anywhere -> keyless OAuth path                                                                                                                                            |
| Status-line billing rule                    | `cli/statusline/context.py:139-151`; design_appendix **§A.8**                                                                        | declarative `cost_mode`; never infers payer from key presence                                                                                                                                                                                               |
| Reserved subscription modes                 | design_appendix **§A.13**                                                                                                            | lists `subscription_*` `BillingMode` values (enum doc, not the key-presence rule)                                                                                                                                                                           |
| Detection signal (Phase 0 resolved)         | `core/reactive/env.py:70` (`can_use_bare`)                                                                                           | no codex-`doctor` equivalent exists, but none is needed: keyless (`can_use_bare` False) + completing turn => the stored OAuth *path* (subscription **candidate**; durable label needs a declared `claude-max`) -- a dependable *gate*, not sufficient proof |
