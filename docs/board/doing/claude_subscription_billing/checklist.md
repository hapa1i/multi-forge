# T0 execution checklist: claude_subscription_billing

**Card**: [`card.md`](card.md). **Epic**: `docs/board/doing/epic_consumer_lanes/`.
**Branch**: `claude_subscription_billing`.

## Current focus

**Awaiting plan review before implementation.** Card + checklist scaffolded; nothing committed, no `src/` change. Lane
**decided: `doing/`** (an execution branch exists; board_contract's discriminator is "todo/ = no active branch"). Phase 0
is an operator-gated probe and the gate for everything below; Phases 1-2 are **conditional on a positive Phase 0**.
Review targets: the framing correction (incomplete, not buggy), the **detection-signal risk** (card Q1 -- the real soft
spot), and the three-way kill criterion.

## Phases

### Phase 0 -- Probe: can `claude -p` ride Max, and is the signal stable? (the gate; no `src/` change)

Operator-gated harness under `scripts/experiments/claude-subscription/` (mirrors `scripts/experiments/openrouter/`:
staged `reproduce.sh`, read-only credential reuse, metadata-only records, scan-and-fail `sanitize.sh`).

**Precondition (or the probe self-deceives):** to exercise the keyless path the operator must have **no resolvable
`ANTHROPIC_API_KEY` in env AND none in `~/.forge/credentials.yaml`** (and note that `auth_ignore_env` changes which
sources count). If a key is resolvable, the runner hydrates it and adds `--bare` -- the probe would silently measure the
*key* path and falsely conclude "no subscription." The harness must assert keyless-ness before running.

Produces `phase0-results.md` answering, with verbatim evidence:

- [ ] **(a0) Non-TTY OAuth feasible at all? (gates the rest)**: can `claude -p` use a pre-authenticated Max/Pro session
  in a non-TTY context? Omitting `--bare` only *permits* OAuth; OAuth usually needs a TTY/browser. Assertion: a
  documented keyless turn that authenticates via the subscription, **or** a documented confirmation it cannot (kill #1).
- [ ] **(a) Keyless turn completes**: given (a0), a keyless `claude -p` completes a real turn via the Max session.
  (Runner already allows the path -- `session_runner.py:183`, test `test_session_runner.py:200`; **no runner change in
  scope**.)
- [ ] **(b) Billing signal**: the `--output-format json` envelope reports a dollar `cost` (API-equivalent) or
  usage-but-no-cost (subscription/quota). Assertion: the captured cost field, tagged `[COST-PRESENT]`/`[COST-ABSENT]`.
- [ ] **(c) Detection signal + stability**: enumerate each candidate **with its failure mode** and pick the most stable
  (or report none qualifies): `claude config get` (no stable JSON contract), `~/.claude/credentials.json` / OS keychain
  (OS-specific, unowned schema), envelope-cost-null (runtime-only, not preflight). Assertion: a named signal + a
  stability verdict (`stable-preflight` / `runtime-only` / `none`).
- [ ] **(d) Quota draw** (optional; informs T5/T7): does the run draw down Max quota / surface rate-limit headroom?
- [ ] `phase0-results.md` written; `sanitize.sh` clean (no secrets); `make pre-commit` clean on the harness.

### Decision gate (after Phase 0 -- three outcomes, do not conflate)

- [ ] **Full kill (architectural)**: (a0)/(a) negative -> the subscription lane is impossible; document + close the
  `claude-max`-as-subscription question in the epic. **Stop.**
- [ ] **Phase-1 no-go (brittle signal)**: (a)/(b) positive but (c) = `none`/`runtime-only` below the bar -> do **not**
  emit a guessed `subscription_*`; record the finding (optionally as future runtime-only work). **Stop.**
- [ ] **Per-token (labeling, not kill)**: keyless auth succeeds but (b) = cost-present -> keep `api`/`unknown`; note the
  path's non-billing value (fidelity/decorrelation) separately. **Stop the billing work.**
- [ ] **Proceed**: (a0)/(a)/(b) positive **and** (c) `stable-preflight` -> Phase 1; record the `billing_mode` value (b)
  implies (`subscription_quota` vs `subscription_headless_credit` -- card Q3).

### Phase 1 -- Auth-posture resolver + thread it (Option A; gated on Phase 0 "Proceed")

- [ ] Preflight-style resolver classifies a run's auth method (key vs subscription) from the Phase 0 (c) signal --
  structural analogue of `_resolve_codex_auth` (`core/runtime/codex_preflight.py:365-403`). New path; **not** a branch in
  `infer_billing_mode` (its `(direct, has_api_key)` shape can't see auth method).
- [ ] **Precedence**: the resolver yields a `subscription_*` mode **only when `can_use_bare` is False** (no resolvable
  key), so a machine with both a key and a Max session is never mislabeled subscription -- key wins, mirroring codex's
  `stored API key` before `stored ChatGPT tokens`.
- [ ] **Option A -- resolve once, thread it**: resolve the posture at session start and pass a new `resolved_billing_mode`
  through **all four** `emit_usage_for_session_result` callers -- `supervisor.py:578`, `memory_writer.py:526`,
  `shadow_curation.py:306`, `team/handlers.py:249` -- *not* re-derived inside `emit`. Omitting any caller leaves that
  consumer labeling subscription runs `unknown`.
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

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Subscription-authed run emits a subscription mode | resolver sees the (c) signal, `can_use_bare` False, no cost | `billing_mode` is the chosen `subscription_*` (not `unknown`/`api`) | `tests/src/core/usage/test_emit.py` |
| **Precedence: key + Max coexist -> `api`, never subscription** | key resolvable (`can_use_bare` True) *and* a Max session present | `billing_mode == "api"`; resolver does **not** yield `subscription_*` | `tests/src/core/runtime/test_claude_billing_preflight.py` (new) |
| Key-authed run stays `api` (byte-identical) | direct run, key present, no subscription signal | `billing_mode == "api"`; emission unchanged from today | `tests/src/core/usage/test_emit.py` |
| Proxied run stays `unknown` | `base_url` set | `billing_mode == "unknown"` (conservatism preserved) | `tests/src/core/usage/test_billing.py` |
| **All four callers thread the posture** | each of supervisor/memory-writer/shadow-curation/team handler emits under a subscription posture | every consumer records the `subscription_*` mode (no caller left at `unknown`) | `tests/src/core/usage/test_emit.py` + per-consumer suites |
| Resolver maps signal -> mode | the (c) signal present/absent | resolver returns the subscription mode / falls back honestly | `tests/src/core/runtime/test_claude_billing_preflight.py` (new) |
| `claude-max` source validates (Phase 2) | catalog load | `runtime_native`, declares no credential, `reachable_via=("claude_code",)` | `tests/src/backend/test_sources.py` |

## Blockers / deferred

- **Phase 0 is operator-gated**: needs a real Claude Max/Pro session on the operator's machine (the test env likely
  lacks one) **with no resolvable API key** (see precondition). Results land in `phase0-results.md`.
- **Card open questions Q1-Q3** are review inputs -- resolve before Phase 1 (especially Q1, the detection-signal
  tolerance).
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
