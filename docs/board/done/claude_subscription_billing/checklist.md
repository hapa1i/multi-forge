# T0 execution checklist: claude_subscription_billing

**Card**: [`card.md`](card.md). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**:
`claude_subscription_billing`.

## Current focus

**Phase 0 done; Phase 1+2 implemented and verified (2026-06-29).** Keyless `claude -p` rides Max headlessly (Phase 0),
and Forge now emits `billing_mode="subscription_quota"` for a keyless direct run whose bound consumer-lane backend is
`claude-max`. Decisions taken in review: billing wired for **all four** consumers; the label is gated on the **bound
backend's `billing_posture`** (not a magic string); declaration UX is **supervisor-only** this card
(`forge policy supervisor set --backend claude-max`), with the other three consumers getting the read/emit plumbing +
manifest slots (bindable in tests/programmatically). **Done**: merged as PR #58 (`b0614325`); card closed to `done/`
(2026-06-29).

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
  `bearer_env_present=false`).
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
- [x] **Proceed**: (a0)/(a) positive **and** (c) `stable-preflight` -> Phase 1. `can_use_bare` False is the **necessary
  gate** (key wins); the `subscription_*` **label** additionally needs an explicit `claude-max` declaration --
  undeclared keyless stays `unknown` (`can_use_bare` can't see Free/Pro/Max). Cost stays `unavailable`. **Q3 resolved:
  `subscription_quota`** (codex headless precedent -- card Q3).

### Phase 1 -- Auth-posture resolver + thread it (DONE)

- [x] **Resolver**: `resolve_billing_mode(*, direct, has_api_key, backend_id)` in `core/usage/billing.py` (co-located
  with `infer_billing_mode`, which it delegates to -- **not** `core/runtime/` as the card sketched; cohesion + a
  cycle-free `billing -> backend.sources` import). Upgrades only a keyless direct run on a `subscription_quota`-posture
  backend; fail-open `None` on a drifted backend.
- [x] **Precedence + label gate**: a resolvable key wins (`api`, mirroring codex stored-key-before-tokens); the
  subscription label needs the **bound backend's `subscription_quota` posture** (the Phase 2 `claude-max` source), not
  just keyless. Undeclared keyless / per_token / drifted => `unknown`.
- [x] **All four consumers thread it**: `emit_usage_for_session_result` gained `backend_id`; each consumer reads its
  bound backend via `read_bound_backend_id(state, consumer)` and threads it -- supervisor (`lane.backend_id`),
  memory-writer + shadow-curation (CLI entry), team-supervisor (hook -> both handlers -> `_run_supervisor`). New
  `Consumer` defs + 6 manifest slots on `ConsumerLane{Intent,Confirmed}`.
- [x] `infer_billing_mode` unchanged (the resolver delegates to it for the api/unknown base).
- [x] No local cost inference (design §3.14): subscription runs keep `cost_micros=null` / `confidence="unavailable"`;
  only the `billing_mode` label changes.
- [x] **Declaration UX (supervisor-only)**: `lane_record_for(consumer, *, runtime, backend)` +
  `forge policy supervisor set --backend claude-max`. The other three consumers' operator CLI + binding freeze is a
  follow-on (bindable in tests/programmatically now).

### Phase 2 -- `claude-max` ModelSource (in T0; card Q2 resolved) (DONE)

- [x] **Prereq resolved**: Q3 = `subscription_quota`, already carried by `BillingPosture` -- no type extension.
- [x] Added `claude-max` to `BUILTIN_MODEL_SOURCES`: `runtime_native`, `provider="anthropic"`, no credential,
  `billing_posture="subscription_quota"`, `reachable_via=("claude_code",)` (mirrors `chatgpt`).
- [x] `forge model backend list/test-auth` treat it runtime-owned via the existing generic branch; the runtime-native
  probe hint is now derived from `reachable_via` (one `_runtime_native_probe_detail` helper, both sites) so `claude-max`
  points at the Claude login, not codex preflight.
- [x] **Decision recorded** (card Q2): the `claude-max` source ships **in T0** (the user chose all-four billing).

## Acceptance tests (fixture-grounded; Phase 1+, authored once the probe sets the signal)

| Test                                                           | Fixture                                                                                                           | Assertion                                                                                                 | Test File                                                                                                                      |
| -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Declared `claude-max` + keyless run emits a subscription mode  | `can_use_bare` False **and** a `claude-max` declaration in scope                                                  | `billing_mode == "subscription_quota"` (not `unknown`/`api`)                                              | `tests/src/core/usage/test_emit.py`                                                                                            |
| **Undeclared keyless OAuth stays `unknown`**                   | `can_use_bare` False, **no** `claude-max` declaration                                                             | `billing_mode == "unknown"` (label needs a declaration, not just keyless)                                 | `tests/src/core/usage/test_billing.py`                                                                                         |
| **Precedence: key + Max coexist -> `api`, never subscription** | key resolvable (`can_use_bare` True) *and* a Max session present                                                  | `billing_mode == "api"`; resolver does **not** yield `subscription_*`                                     | `tests/src/core/usage/test_billing.py`                                                                                         |
| Key-authed run stays `api` (byte-identical)                    | direct run, key present, no subscription signal                                                                   | `billing_mode == "api"`; emission unchanged from today                                                    | `tests/src/core/usage/test_emit.py`                                                                                            |
| Proxied run stays `unknown`                                    | `base_url` set                                                                                                    | `billing_mode == "unknown"` (conservatism preserved)                                                      | `tests/src/core/usage/test_billing.py`                                                                                         |
| **All four callers thread the posture**                        | a `claude-max` binding in scope; each caller invoked (supervisor via `command`; the other three via their run-fn) | each caller's run-fn threads `backend_id` so its `UsageEvent.billing_mode == "subscription_quota"`        | `test_emit.py` (emit+supervisor) + per-consumer `test_claude_max_binding_emits_subscription_quota` (memory-writer/shadow/team) |
| Resolver maps signal -> mode                                   | the (c) signal present/absent                                                                                     | resolver returns the subscription mode / falls back honestly                                              | `tests/src/core/usage/test_billing.py`                                                                                         |
| `claude-max` source validates (Phase 2)                        | catalog load                                                                                                      | `runtime_native`, `billing_posture="subscription_quota"`, no credential, `reachable_via=("claude_code",)` | `tests/src/backend/test_sources.py`                                                                                            |

## Blockers / deferred

- **Phase 0 done (2026-06-29)** on a live Max box (key stripped via `env -u` to satisfy the keyless precondition; no
  durable state touched). Results in `phase0-results.md`.
- **Q1 resolved** (`can_use_bare`); **Q3 resolved** (`subscription_quota`); **Q2 resolved** -- the `claude-max` source
  ships **in T0**.
- T6 (placing a consumer on the lane) and T7 (exhaustion fail-open) stay out of scope.

## Closeout

- [x] Phase 0 `phase0-results.md` landed; decision-gate outcome recorded in the epic.
- [x] Phase 1 acceptance tests green (resolver precedence, drift fail-open, `read_bound_backend_id` for all four, emit
  `subscription_quota` + key-precedence, per-caller `backend_id` forwarding for memory-writer/shadow/team via
  `test_claude_max_binding_emits_subscription_quota`); `make pre-commit` clean; design §3.14 / appendix §A.13 + source
  catalog + `cli_reference` + end-user `policy.md` synced.
- [x] Phase 2 `claude-max` source + docs (no `BillingPosture` extension -- Q3 = `subscription_quota`, already carried).
- [x] `change_log.md` entry (Goal / Key changes / Verification) -- landed in PR #58.
- [x] Durable lessons folded into the epic closeout (T1a-T5 pattern; no per-member `impl_notes.md` entry). The
  `billing_mode` != key-presence invariant is already in `impl_notes.md`; promote the `can_use_bare`
  necessary-but-not-sufficient refinement at epic closeout.
- [x] Epic roster row updated (T0 -> done) and `git mv doing/ -> done/` (PR #58 merged, 2026-06-29).
