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

| Signal                      | Verdict                          | Evidence (sanitized)                                                                                  |
| --------------------------- | -------------------------------- | ----------------------------------------------------------------------------------------------------- |
| (a0) non-TTY OAuth feasible | `[OAUTH-NONTTY-OK]`              | `auth_marker_seen=false`; rode the Keychain Max session non-TTY                                       |
| (a) keyless turn completes  | yes                              | `rc=0`, `has_result=true`, `is_error=false`, `subtype=success`                                        |
| (b) billing signal          | `[COST-PRESENT]`                 | `total_cost_usd=0.0412665`, usage 2923 in / 4 out                                                     |
| (b) composite shape         | `[SHAPE-SUBSCRIPTION-CANDIDATE]` | keyless + completed => rode the stored OAuth session (a candidate; durable label needs a declaration) |
| (c) detection signal        | `[SIGNAL-STABLE-PREFLIGHT]`      | chosen = `can_use_bare`; all artifact candidates failed (see below)                                   |
| (d) quota draw              | not run                          | `claude -p` exposes no `anthropic-ratelimit-*` headers; deferred                                      |

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
turn => the run rode the OAuth *path*; keyed => the runner adds `--bare` => api. Preflight, Forge-owned, no unowned
external schema; read from the run's **input**, not its artifacts. **It is a necessary gate, not sufficient proof of a
subscription:** it cannot see the account's plan (Free/Pro/Max), so the durable `subscription_*` label needs an explicit
`claude-max` declaration on top of it (see card Phase 1).

## Probe self-corrections (the run improved the harness)

Running the probe for real (items 1-2) plus review (item 3) surfaced three corrections to its first-cut interpretation,
now fixed in the harness + card:

1. **The decision gate mis-resolved cost-present.** It mapped a completed-keyless run with a cost to "per-token / keep
   `api`". Corrected: keyless + completed => the stored OAuth *path* -- a subscription **candidate** regardless of the cost field (the cost is an estimate; the durable label still needs a declared `claude-max`). The
   `[SHAPE-PER-TOKEN-OR-ESTIMATE]` shape was removed; the gate's "per-token" branch now applies only to a
   metered-console-OAuth account (Q3), which the envelope can't reveal.
2. **The detection candidate list omitted `can_use_bare`.** The first cut enumerated only external artifacts and
   concluded `[SIGNAL-RUNTIME-ONLY]`. Adding `can_use_bare` as the primary candidate yields `[SIGNAL-STABLE-PREFLIGHT]`.
3. **The token-env path could read as clean subscription.** A keyless run with `CLAUDE_CODE_OAUTH_TOKEN` /
   `ANTHROPIC_AUTH_TOKEN` set rides an *injected token* (any account), but the first cut still stamped the clean
   subscription verdict with only a soft note. Fixed: stage 00 now emits `[KEYLESS-BUT-TOKEN-ENV]` and the turn emits
   `[SHAPE-SUBSCRIPTION-UNVERIFIED]`. This run had **no** token env (`oauth_token_env_present=false`), so the result
   stands.

## Decision gate outcome

- [x] **Proceed** -- (a0)/(a) positive **and** (c) `[SIGNAL-STABLE-PREFLIGHT]`. Go to Phase 1: the auth-posture resolver
  uses `can_use_bare` as the **necessary gate** (key wins) and emits `subscription_quota` only with an explicit
  `claude-max` declaration (undeclared keyless => `unknown`), threaded through all four `emit_usage_for_session_result`
  callers; cost stays `unavailable`.
- [ ] Full kill (architectural) -- not taken: (a0)/(a) positive.
- [ ] Phase-1 no-go (brittle signal) -- not taken: (c) is stable-preflight.
- [ ] Per-token (labeling) -- refuted: cost-present on a keyless run is an estimate, not per-token billing.

## Q1-Q3 status

- **Q1 (detection-signal risk): stability RESOLVED.** A *stable* signal exists -- `can_use_bare`, not a brittle
  Claude-side artifact (kill #2 did not materialize). Caveat: it is a **necessary gate, not sufficient** -- it proves
  the OAuth path, not the account's plan -- so the durable label still needs a `claude-max` declaration (see Phase 1 /
  Q3).
- **Q2 (Phase-2 scope):** still a scope decision (split the `claude-max` `ModelSource` to a follow-on?), but **no longer
  blocked on a `BillingPosture` change** -- Q3 = `subscription_quota`, already a valid posture.
- **Q3 (which `billing_mode`): RESOLVED -- `subscription_quota`.** (b) couldn't disambiguate from cost (an estimate
  either way), so this was settled on semantics: the existing headless consumer-subscription case (`codex exec`) already
  maps to `subscription_quota` (`codex_preflight.py:401-403`, comment "Consumer ChatGPT is provably
  quota/credit-billed"), and `subscription_headless_credit` has no defined consumer. Claude Max headless is the exact
  analog. Caveat: (d) was not run; if a *distinct* headless-credit meter ever appears, revisit. (Separately, whether a
  keyless run is a *paid* subscription at all -- vs Free/metered -- still needs the `claude-max` declaration, not just
  `can_use_bare`.)
