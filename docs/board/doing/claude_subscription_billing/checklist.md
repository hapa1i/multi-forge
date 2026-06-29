# T0 execution checklist: claude_subscription_billing

**Card**: [`card.md`](card.md). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**:
`claude_subscription_billing`.

## Current focus

**Phase 0 done (2026-06-29); outcome = PROCEED.** The probe ran on a live Claude Max box: keyless `claude -p` rides Max
headlessly, and the detection signal is `can_use_bare` (see `phase0-results.md`). **Phase 1 (the auth-posture resolver)
is unblocked and is the next implementation step.** Lane **stays `doing/`**. The run corrected two of the probe's own
assumptions: cost-presence is an API-list-price estimate (not a per-token signal), and the stable signal is Forge's
`can_use_bare`, not a brittle Claude-side artifact.

## Phases

### Phase 0 -- Probe: can `claude -p` ride Max, and is the signal stable? (the gate; no `src/` change)

Operator-gated harness under `scripts/experiments/claude-subscription/` (mirrors `scripts/experiments/openrouter/`:
staged `reproduce.sh`, read-only credential reuse, metadata-only records, scan-and-fail `sanitize.sh`).

**Precondition (or the probe self-deceives):** to exercise the keyless path the operator must have **no resolvable
`ANTHROPIC_API_KEY` in env AND none in `~/.forge/credentials.yaml`** (and note that `auth_ignore_env` changes which
sources count). If a key is resolvable, the runner hydrates it and adds `--bare` -- the probe would silently measure the
*key* path and falsely conclude "no subscription." The harness must assert keyless-ness before running.

Produces `phase0-results.md` answering, with verbatim evidence:

- [x] **(a0) Non-TTY OAuth feasible? (gates the rest)** -- **YES** (`[OAUTH-NONTTY-OK]`): a keyless `claude -p`
  authenticated via the Keychain Max session in a non-TTY context (`auth_marker_seen=false`,
  `oauth_token_env_present=false`).
- [x] **(a) Keyless turn completes** -- **YES**: `rc=0`, `subtype=success`, `is_error=false` (no runner change; the
  runner already permits the path -- `session_runner.py:183`).
- [x] **(b) Billing signal** -- `[COST-PRESENT]`, `total_cost_usd=$0.0412665` (2923 in / 4 out). **This is an
  API-list-price ESTIMATE present even on Max -- NOT a billing discriminator** (refutes the `[COST-ABSENT]`-on-OAuth
  expectation; cost stays `unavailable` for the cost plane).
- [x] **(c) Detection signal + stability** -- `[SIGNAL-STABLE-PREFLIGHT]` = **`can_use_bare`** (Forge's own
  key-resolvability predicate; preflight, owned, stable). The artifact candidates failed: `config get` hangs,
  `credentials.json`/keychain unowned, envelope-cost-null doesn't fire (cost is present on Max).
- [ ] **(d) Quota draw** (optional; informs T5/T7) -- **not run** (`claude -p` exposes no `anthropic-ratelimit-*`
  headers; deferred).
- [x] `phase0-results.md` written; `sanitize.sh` clean (no secrets); harness `ruff`/`mypy`/`pyright`/`pre-commit` clean.

### Decision gate (after Phase 0 -- three outcomes, do not conflate)

- [ ] **Full kill (architectural)** -- not taken: (a0)/(a) are positive.
- [ ] **Phase-1 no-go (brittle signal)** -- not taken: (c) is `stable-preflight` (`can_use_bare`).
- [ ] **Per-token (labeling, not kill)** -- **refuted**: cost-present on a keyless run is an estimate, not per-token
  billing (with no key there is nothing to bill an API). Only a metered-console-OAuth account would qualify -- card Q3.
- [x] **Proceed**: (a0)/(a) positive **and** (c) `stable-preflight` -> Phase 1. `billing_mode` keyed off `can_use_bare`
  (keyless => subscription), cost stays `unavailable`. (b) did not pick `subscription_quota` vs
  `subscription_headless_credit` -- a semantics call (card Q3).

### Phase 1 -- Auth-posture resolver + thread it (Option A; gated on Phase 0 "Proceed")

- [ ] Preflight-style resolver classifies a run's auth method (key vs subscription) from the Phase 0 (c) signal --
  structural analogue of `_resolve_codex_auth` (`core/runtime/codex_preflight.py:365-403`). New path; **not** a branch
  in `infer_billing_mode` (its `(direct, has_api_key)` shape can't see auth method).
- [ ] **Precedence**: the resolver yields a `subscription_*` mode **only when `can_use_bare` is False** (no resolvable
  key), so a machine with both a key and a Max session is never mislabeled subscription -- key wins, mirroring codex's
  `stored API key` before `stored ChatGPT tokens`.
- [ ] **Option A -- resolve once, thread it**: resolve the posture at session start and pass a new
  `resolved_billing_mode` through **all four** `emit_usage_for_session_result` callers -- `supervisor.py:578`,
  `memory_writer.py:526`, `shadow_curation.py:306`, `team/handlers.py:249` -- *not* re-derived inside `emit`. Omitting
  any caller leaves that consumer labeling subscription runs `unknown`.
- [ ] `infer_billing_mode` unchanged for the key-authed/proxied cases (its conservatism is correct); the subscription
  path is resolved upstream and passed in.
- [ ] No local cost inference (design §3.14): subscription runs keep `cost_micros=null` / `confidence="unavailable"`
  (Phase-5 cost honesty already in place); T0 fixes only the `billing_mode` *label*.

### Phase 2 -- `claude-max` ModelSource (scope decision per card Q2; gated on Phase 1)

- [ ] **Prereq**: if (b) chose credit semantics, extend `BillingPosture` (`backend/sources.py:24`) with
  `subscription_headless_credit` before the source can carry it (it has only `per_token`/`subscription_quota`/`free`
  today).
- [ ] Add `claude-max` to `BUILTIN_MODEL_SOURCES`: `runtime_native` endpoint (no Forge credential), `billing_posture`
  per (b), `reachable_via=("claude_code",)` -- mirroring `chatgpt`.
- [ ] Catalog validation + `forge model backend list/test-auth` treat it runtime-owned (auth `runtime_native`, health
  `runtime-owned`), like `chatgpt`.
- [ ] **Decision recorded** (card Q2): confirmed in T0, or split to a follow-on.

## Acceptance tests (fixture-grounded; Phase 1+, authored once the probe sets the signal)

| Test                                                           | Fixture                                                                                          | Assertion                                                                      | Test File                                                       |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| Subscription-authed run emits a subscription mode              | resolver sees the (c) signal, `can_use_bare` False, no cost                                      | `billing_mode` is the chosen `subscription_*` (not `unknown`/`api`)            | `tests/src/core/usage/test_emit.py`                             |
| **Precedence: key + Max coexist -> `api`, never subscription** | key resolvable (`can_use_bare` True) *and* a Max session present                                 | `billing_mode == "api"`; resolver does **not** yield `subscription_*`          | `tests/src/core/runtime/test_claude_billing_preflight.py` (new) |
| Key-authed run stays `api` (byte-identical)                    | direct run, key present, no subscription signal                                                  | `billing_mode == "api"`; emission unchanged from today                         | `tests/src/core/usage/test_emit.py`                             |
| Proxied run stays `unknown`                                    | `base_url` set                                                                                   | `billing_mode == "unknown"` (conservatism preserved)                           | `tests/src/core/usage/test_billing.py`                          |
| **All four callers thread the posture**                        | each of supervisor/memory-writer/shadow-curation/team handler emits under a subscription posture | every consumer records the `subscription_*` mode (no caller left at `unknown`) | `tests/src/core/usage/test_emit.py` + per-consumer suites       |
| Resolver maps signal -> mode                                   | the (c) signal present/absent                                                                    | resolver returns the subscription mode / falls back honestly                   | `tests/src/core/runtime/test_claude_billing_preflight.py` (new) |
| `claude-max` source validates (Phase 2)                        | catalog load                                                                                     | `runtime_native`, declares no credential, `reachable_via=("claude_code",)`     | `tests/src/backend/test_sources.py`                             |

## Blockers / deferred

- **Phase 0 done (2026-06-29)** on a live Max box (key stripped via `env -u` to satisfy the keyless precondition; no
  durable state touched). Results in `phase0-results.md`.
- **Q1 resolved** (detection signal = `can_use_bare`). **Q2** (Phase-2 scope) and **Q3** (`subscription_quota` vs
  `subscription_headless_credit`) remain -- resolve Q3 before Phase 1 emits a concrete mode.
- T6 (placing a consumer on the lane) and T7 (exhaustion fail-open) stay out of scope.

## Closeout

- [ ] Phase 0 `phase0-results.md` landed; decision-gate outcome recorded in the epic.
- [ ] (If "Proceed") Phase 1 acceptance tests green (incl. precedence + all-four-callers); `make pre-commit` clean;
  design §3.14 / appendix §A.8 + §A.13 synced for the new Claude subscription `billing_mode`.
- [ ] (If "Proceed" + in-scope) Phase 2 `claude-max` source + `BillingPosture` extension + docs.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Promote durable lessons to `impl_notes.md` after human review (or fold into the epic closeout, per the T1a-T5
  pattern).
- [ ] Update epic roster row (T0 -> done) and `git mv doing/ -> done/` after merge.
