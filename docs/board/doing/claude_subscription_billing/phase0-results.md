# T0 Phase 0 results: does `claude -p` ride Max headlessly?

**Status: COMPLETE (run 2026-06-29). Outcome = PROCEED.** Keyless `claude -p` rides a Claude Max subscription
headlessly, and the dependable detection signal is `can_use_bare` (Forge's own key-resolvability predicate), not any run
artifact. Harness: `scripts/experiments/claude-subscription/`. All evidence below is metadata-only; `sanitize.sh` passed
(no secrets) before promotion.

## Run context

- Date: 2026-06-29
- Claude Code version: 2.1.195
- OS: macOS (Darwin)
- Login method (`/status`): **Claude Max account** (`hapali@pm.me`); Max plan
- Keyless proof: stage 00 `[KEYLESS-OK]` with `key_source: "none"` after stripping the env key via
  `env -u ANTHROPIC_API_KEY` (the key lives only in the shell env / `.env`, **not** in `~/.forge/credentials.yaml`; no
  durable state was touched)
- `auth_ignore_env`: false
- OAuth token env var (`CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN`): **absent** -> the turn rode the **Keychain**
  Max session, not a token env var
- Model: `<claude-default>` (opus)

## Findings

| Signal                      | Verdict                     | Evidence (sanitized)                                                          |
| --------------------------- | --------------------------- | ----------------------------------------------------------------------------- |
| (a0) non-TTY OAuth feasible | `[OAUTH-NONTTY-OK]`         | `auth_marker_seen=false`; rode the Keychain Max session non-TTY               |
| (a) keyless turn completes  | yes                         | `rc=0`, `has_result=true`, `is_error=false`, `subtype=success`                |
| (b) billing signal          | `[COST-PRESENT]`            | `total_cost_usd=0.0412665`, usage 2923 in / 4 out                             |
| (b) composite shape         | `[SHAPE-SUBSCRIPTION]`      | keyless + completed => rode the subscription (cost is an estimate, see below) |
| (c) detection signal        | `[SIGNAL-STABLE-PREFLIGHT]` | chosen = `can_use_bare`; all artifact candidates failed (see below)           |
| (d) quota draw              | not run                     | `claude -p` exposes no `anthropic-ratelimit-*` headers; deferred              |

## The load-bearing finding: cost-presence is not a billing signal

A keyless turn with **no API key and no proxy** can only authenticate via the Keychain Max OAuth -- there is nothing to
bill an API per-token. Yet the envelope reported `total_cost_usd = $0.0412665` (for a 4-token reply). That figure is
Claude Code's **API-list-price estimate**, present even on a Max subscription run. So:

- **Cost-presence does not discriminate subscription from API.** This **refutes** the sibling `headless-cost-report`
  harness's expectation that OAuth -> `[COST-ABSENT]`.
- The billing **label** must come from `can_use_bare` (was a key resolvable?), never from the cost field. The cost
  estimate stays `unavailable` for the cost plane (design 3.14) -- it is not the real cost of a subscription run.

## Detection (c): the dependable signal is `can_use_bare`, not an artifact

Every Claude-side artifact candidate failed:

- `claude config get` -- **hangs** non-TTY (bounded to 5s, recorded as timeout); no clean scriptable contract.
- `~/.claude/.credentials.json` / `~/.claude/credentials.json` -- **absent** here (macOS keeps the session in the
  Keychain); unowned schema either way; never read (holds the token).
- OS keychain -- not probed by design (a read would surface the token).
- envelope `total_cost_usd` null -- **does not fire** (cost is present on Max), so even the runtime-only fallback is
  useless.

The dependable signal is **`can_use_bare`** (`core/reactive/env.py:70`): keyless (`can_use_bare` False) + a completing
turn => the run rode OAuth/subscription; keyed => the runner adds `--bare` => api. Preflight, Forge-owned, no unowned
external schema. The auth mode is read from the run's **input**, not its artifacts.

## Probe self-corrections (the run improved the harness)

Running the probe for real exposed two flaws in its own first-cut interpretation, now fixed in the harness + card:

1. **The decision gate mis-resolved cost-present.** It mapped a completed-keyless run with a cost to "per-token / keep
   `api`". Corrected: keyless + completed => subscription regardless of the cost field (the cost is an estimate). The
   `[SHAPE-PER-TOKEN-OR-ESTIMATE]` shape was removed; the gate's "per-token" branch now applies only to a
   metered-console-OAuth account (Q3), which the envelope can't reveal.
2. **The detection candidate list omitted `can_use_bare`.** The first cut enumerated only external artifacts and
   concluded `[SIGNAL-RUNTIME-ONLY]`. Adding `can_use_bare` as the primary candidate yields `[SIGNAL-STABLE-PREFLIGHT]`.

## Decision gate outcome

- [x] **Proceed** -- (a0)/(a) positive **and** (c) `[SIGNAL-STABLE-PREFLIGHT]`. Go to Phase 1: the auth-posture resolver
  keyed off `can_use_bare` (keyless => subscription), threaded through all four `emit_usage_for_session_result` callers;
  cost stays `unavailable`.
- [ ] Full kill (architectural) -- not taken: (a0)/(a) positive.
- [ ] Phase-1 no-go (brittle signal) -- not taken: (c) is stable-preflight.
- [ ] Per-token (labeling) -- refuted: cost-present on a keyless run is an estimate, not per-token billing.

## Q1-Q3 status

- **Q1 (detection-signal risk): RESOLVED.** The signal is `can_use_bare`, not a brittle Claude-side artifact. The kill
  #2 risk did not materialize.
- **Q2 (Phase-2 scope):** unchanged -- still a scope decision (split the `claude-max` `ModelSource` to a follow-on?). If
  credit semantics are chosen, `BillingPosture` needs `subscription_headless_credit` first.
- **Q3 (which `billing_mode`): still open.** (b) did **not** disambiguate -- `total_cost_usd` is an estimate present
  whether the draw is quota- or credit-based, so the cost field can't pick `subscription_quota` vs
  `subscription_headless_credit`. This is a semantics decision; (d) quota-draw evidence would inform it but was not run.
  Resolve before Phase 1 emits a concrete mode.
