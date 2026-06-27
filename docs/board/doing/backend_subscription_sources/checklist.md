# Checklist: T2 -- Backend: runtime-native subscription sources

**Card**: `card.md` (this dir). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**:
`backend_subscription_sources` (off `main` @ `82076324`, the T3 closeout).

## Current focus

Phases 1-4 (Option (c)) + two review findings (see "Review fixes") + a follow-up nit pass (`is_implemented("openai")`
test, `codex-responses-local` appendix row) are **committed and pushed**; **PR #54** is open against `main`
(`make pre-commit` green, 4638-test ripple clean). Remaining: review/merge PR #54, then the `doing/ -> done/` lane move
\+ epic roster T2 -> done. Touchpoints were **verified against `main` @ `82076324`** (sweep below); all three design
decisions resolved (A = Option (c), user 2026-06-26; B/C below).

## Verified touchpoints (2026-06-25 sweep -- corrections to the card noted)

- `EndpointKind` (`backend/sources.py:19`) = `Literal["literal_url", "connection_value", "local_backend"]` -- all
  endpoint-shaped; `_validate_endpoint` (`:190`) enforces each kind's exact fields. Confirmed.
- `_validate_source` (`:162`) requires `>=1 credential_id` (`:169`) and rejects an unknown provider (`:167`, via
  `_VALID_PROVIDERS = frozenset(get_args(ProviderType))`). So `provider="openai"` fails at **import** until
  `ProviderType` gains `openai`. Confirmed.
- `source_bearer_auth_env_var` (`:405`) demands **exactly one** secret non-connection env var -- but its **only** caller
  is `proxy/responses_ingress.py` (the proxy Responses route). A `chatgpt` source is `runtime_native`/codex-routed and
  never hits that path, so its zero-secret auth never trips this. Confirmed (grep: 1 caller).
- `Credential` (`core/credential_registry.py:24`) allows `env_vars=()` (empty default) -- a no-secret credential **is**
  constructible. `codex-api` already documents the ChatGPT-subscription login in `not_needed_for`. Confirmed.
- `RUNTIMES` (`core/runtime/registry.py:148`) has `claude_code`, `codex`, `gemini` -- so the `chatgpt -> codex` pin is a
  real `runtime_id`. Confirmed.
- `lanes._reachable` (`core/lanes.py:153`) is a stub `return True` whose comment literally names `chatgpt -> codex` as
  the T2 pin. This is the resolver contract T2 fills. Confirmed.
- `codex_preflight.py:403` returns `_Auth("chatgpt_tokens", "codex_store", "subscription_quota", None)` -- so
  `chatgpt -> subscription_quota` is real, and `BillingMode` (`core/usage/ledger`) already contains that exact spelling.
  Confirmed.
- **Card correction (ProviderType ripple is smaller than stated).** The card says update `detect_provider` /
  `is_implemented`. Verified **not required for T2**: no `assert_never`/exhaustive `match` on `ProviderType` exists
  anywhere (grep clean); every consumer is an `if/elif` fall-through; `detect_provider("openai/…")` already returns
  `litellm_remote` (never `openai`); and the `chatgpt` source is `runtime_native`/codex-routed, so `provider="openai"`
  lives **only** as a catalog attribute and never enters `core.llm` client routing. The single sharp edge --
  `_fetch_credentials`'s `else: raise ValueError` (`core/llm/credentials.py:319`) -- is unreachable with `openai` in T2.
  Leave `detect_provider`/`is_implemented` unchanged; document why. Flag for reviewer.
- **Card correction (probe is skip, not a new branch).** `_resolved_endpoint_url` (`cli/backend.py:399`) returns `None`
  for any non-endpoint kind, so `_probe_model_source` (`:414`) reports `runtime_native` as
  `failed: endpoint is not configured` (`:424`). Fix = a one-line early `status="skipped"` for `runtime_native`
  **before** the base_url check; no new auth-header branch. `_source_record` (`:318`) passes `provider` through as a
  display string (no branching), so `openai` renders in `backend list` for free.

## Design decisions (resolve before code)

- [x] **Decision A -- runtime-native credential shape. Decided: Option (c)** (user, 2026-06-26). Relax the credential
  rule as a **first-class semantic of `runtime_native`**, not an exception. A `runtime_native` source declares
  `credential_ids=()`: "Forge names the backend and reasons about its billing/reachability, but endpoint **and auth**
  are owned by the runtime." Three concrete consequences:
  - **Validator symmetry** (`_validate_source`): the credential rule becomes a positive either/or tied to the endpoint
    family -- `runtime_native` => `credential_ids` MUST be empty (auth is runtime-owned; declaring a Forge credential is
    an **error**); every other kind => `>=1` credential (today's rule, unchanged -- the existing
    `match="at least one credential"` test stays green). Not a `!= "runtime_native"` carve-out bolted onto the generic
    check.
  - **Display language** (`cli/backend.py`): a `runtime_native` source renders `auth_status="runtime_native"` (not the
    misleading `configured` it would otherwise fall into via the empty-credential loop) and health **`runtime-owned`**
    (not `missing`/`unprobed`); the probe + `test-auth` skip with detail pointing at `forge runtime preflight codex`.
    `Credential` stays pure (no keyless marker credential).
  - **Guidance home**: codex-login help (`codex login --device-auth`) lives in Codex preflight / runtime readiness, not
    Forge credential storage. T2 adds none to the credential registry.
- [x] **Decision B -- reachability-pin storage. Decided: `reachable_via: tuple[str, ...] = ()` on `ModelSource`** (empty
  = any runtime, preserving every existing source). `chatgpt` sets `("codex",)`.
  `lanes._reachable(runtime_id, backend_id)` becomes a pure lookup:
  `src = get_model_source(backend_id); return not src.reachable_via or runtime_id in src.reachable_via`. Chosen over
  "endpoint carries the runtime" because the card pins the `runtime_native` endpoint to **no value** (like
  `local_backend`), and a source-level pin generalizes to `claude-max -> claude` later. *Flag for user; will revisit if
  they prefer the runtime on the endpoint.*
- [x] **Decision C -- `BillingPosture` home + vocab. Decided: define in `backend/sources.py`**
  (`BillingPosture = Literal["per_token", "subscription_quota", "free"]`, exported), a `ModelSource.billing_posture`
  field defaulting `"per_token"`. It is an intrinsic source property; T5 (telemetry/status) imports it from there (no
  cycle -- backend is below telemetry). Reuses the **exact** `"subscription_quota"` string shared with `BillingMode`. It
  is a **separate** enum from `BillingMode` (the epic chose this -- posture is coarse/source-level; mode is
  invocation-level), but "one spelling" for the shared member.

## Phases (ordered so the catalog stays importable at every step)

### Phase 1 -- `BillingPosture` + `ModelSource.billing_posture` (additive)

- [x] Add `BillingPosture = Literal["per_token", "subscription_quota", "free"]` to `backend/sources.py` + `__all__`.
- [x] Add `ModelSource.billing_posture: BillingPosture = "per_token"`. Assertion: every existing source keeps
  `billing_posture == "per_token"` (no behavior change); `mypy`/`pyright` clean. Verified:
  `test_billing_posture_defaults_to_per_token` (all built-ins except `chatgpt`); mypy clean.

### Phase 2 -- `runtime_native` access shape

- [x] `EndpointKind` += `"runtime_native"` (kept **one** enum; "endpoint" still reads fine as the access-shape axis).
- [x] `SourceEndpoint.runtime_native()` factory (`kind="runtime_native"`, no `value`, no `default_url`) +
  `_validate_endpoint` arm rejecting any `value`/`default_url` (mirrors `local_backend`).
- [x] `_validate_source`: a `kind="remote"` source may use a `runtime_native` endpoint with **no** `local_lifecycle`.
  Assertion: constructing a `runtime_native` source with a `literal_url` (or any `value`) is rejected. Verified:
  `test_runtime_native_endpoint_rejects_url_or_default`, `test_chatgpt_subscription_source_is_runtime_native`.

### Phase 3 -- provider vocabulary + display/probe

- [x] `ProviderType` (`core/provider_types.py:7`) += `"openai"`. Assertion: `get_args(ProviderType)` includes `openai`;
  full unit suite + `mypy`/`pyright` stay green (no exhaustiveness break -- verified none exists). Verified: 1073 ripple
  tests (`core/llm`, `proxy`, `backend`, `core/usage`) pass; mypy clean.
- [x] `cli/backend.py::_probe_model_source`: early skip for `endpoint.kind == "runtime_native"` (detail points at
  `forge runtime preflight codex`), before the base_url check.
- [x] `_auth_record` returns `status="runtime_native"` (empty credentials, no missing-env-var noise) instead of falling
  into the misleading `configured` the empty-credential loop would yield; `_source_health` reports `runtime-owned`.
  Assertion: `forge model backend list --json` shows `provider="openai"`, health `runtime-owned`, auth `runtime_native`.
  Verified: `test_list_json_renders_runtime_native_source_as_runtime_owned`.
- [x] Left `detect_provider`/`is_implemented` **unchanged**; added a comment at the `ProviderType` def noting `openai`
  is catalog-only (never a `core.llm` routing provider; `detect_provider` maps `openai/<model>` to `litellm_remote`).

### Phase 4 -- `chatgpt` source + reachability pin (depends on Decision A)

- [x] `reachable_via: tuple[str, ...] = ()` on `ModelSource` (Decision B). Default empty preserves all sources.
- [x] `lanes._reachable` reads it (pure `get_model_source` lookup; `backend_id` is already canonical from
  `Lane.__post_init__`). Assertion: `(codex, chatgpt)` reachable; `(claude_code, chatgpt)` not; every existing
  `(runtime, backend)` still reachable. Verified: `test_subscription_backend_reachable_only_via_pinned_runtime`,
  `test_subscription_backend_cannot_default_for_unpinned_runtime`, `test_unpinned_backend_reachable_by_any_runtime`.
- [x] Credential per Decision A: validator symmetry in `_validate_source` -- `runtime_native` MUST be credential-free,
  every other kind keeps `>=1`. Verified: `test_runtime_native_source_must_not_declare_credentials`,
  `test_non_runtime_native_source_still_requires_a_credential`.
- [x] New catalog entry `chatgpt`: `provider="openai"`, `endpoint=runtime_native`,
  `billing_posture="subscription_quota"`, `reachable_via=("codex",)`, `kind="remote"`, no `local_lifecycle`. Assertion:
  `validate_model_sources` passes at import; `get_model_source("chatgpt")` resolves. Verified:
  `test_chatgpt_subscription_source_is_runtime_native`, `test_builtin_catalog_validates`.

### Phase 5 -- tests + docs + closeout

- [x] Acceptance tests (table below) -- all rows covered in `test_sources.py`, `test_lanes.py`,
  `test_backend_commands.py` (61 focused tests pass).
- [x] Design-doc sync: `design_appendix.md` §A.2.1 (`ModelSource` gains `billing_posture` + `runtime_native` access +
  `reachable_via`; `chatgpt` added to the shipped-catalog table; operator-view paragraph documents the runtime-owned
  read surface). Epic checklist §A.2.1 design-doc-sync item ticked.
- [x] `change_log.md` entry (newest-first) added. mypy clean.
- [x] `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks). Verified: all hooks pass.
- [ ] After PR merges to `main`: move `doing/backend_subscription_sources/` -> `done/`; epic roster T2 -> done; epic
  "Current focus" -> next cursor (T4).

## Review fixes (2026-06-26)

Two findings from review, both verified real against the code before fixing:

- [x] **Medium -- `runtime_native` could back a proxy template.** `_apply_template_source` (`config/loader.py`) handled
  `literal_url`/`connection_value`/`local_backend` with no `else`, so a custom template `proxy.source: chatgpt` resolved
  and fell through with no `base_url` -- minting a proxy for an undialable backend (violates the "no proxy support for
  subscriptions" non-goal). Fix: reject `runtime_native` right after source resolution, before mutating the proxy block.
  Verified: `test_runtime_native_source_cannot_back_a_proxy` (`tests/src/config/test_loader.py`).
- [x] **Low -- `reachable_via` only rejected empty strings, not unknown runtimes.** A typo like `("codx",)` passed
  catalog validation, then read as silently unreachable in `lanes._reachable`. Fix: validate each pin against the lane
  runtime axis. The naive fix (import `RUNTIMES` into `sources`) creates a cycle -- importing `core.runtime.registry`
  runs the package `__init__`, which pulls `codex_preflight -> core.auth -> template_secrets -> backend.sources`. Solved
  with a new dependency-light `core/runtime_vocab.py` (`LANE_RUNTIME_IDS = {core_llm} | agent RUNTIMES`), mirroring the
  `core.provider_types` pattern; `sources` validates against it, `lanes` sources `CORE_LLM_RUNTIME` from it, and a drift
  test (`test_lane_runtime_vocab_matches_registry`) locks the vocab to `RUNTIMES`. Verified:
  `test_reachable_via_rejects_unknown_runtime`, `test_reachable_via_accepts_lane_runtime_vocabulary`, plus the drift
  test.
- [x] Design-doc + change-log sync for both fixes; `make pre-commit` clean; 4638-test ripple green.

## Acceptance (definition of done -- extends the card's table)

| Test                             | Fixture                 | Assertion                                                                                    | Test File                                                                     |
| -------------------------------- | ----------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Subscription source, no endpoint | `chatgpt` catalog entry | validates with a `runtime_native` endpoint -- no URL, no lifecycle                           | `tests/src/backend/test_sources.py`                                           |
| Billing posture is stored        | `chatgpt`               | `billing_posture == "subscription_quota"` as a field, not inferred                           | `tests/src/backend/test_sources.py`                                           |
| Per-token default preserved      | every existing source   | `billing_posture == "per_token"` by default (no behavior change)                             | `tests/src/backend/test_sources.py`                                           |
| Provider vocabulary expanded     | `chatgpt`               | `provider="openai"` validates; `backend list` shows it; the probe **skips** it (no endpoint) | `tests/src/backend/test_sources.py`, `tests/src/cli/test_backend_commands.py` |
| Reachability pins runtime        | resolver input          | `chatgpt` reachable only via `codex`; existing `(runtime, backend)` pairs unchanged          | `tests/src/core/test_lanes.py`                                                |
| No faked endpoint                | `chatgpt`               | constructing it with a `literal_url` is rejected; `runtime_native` has no `value`            | `tests/src/backend/test_sources.py`                                           |
| `reachable_via` default-empty    | every existing source   | empty `reachable_via` -> reachable by any lane runtime (T1a behavior preserved)              | `tests/src/core/test_lanes.py`                                                |

## Non-goals (from card)

- **No `claude-max` source** -- deferred until T0 proves `claude -p` subscription billing; do not assert
  `subscription_quota` for `claude-max` on faith.
- No proxy support for subscriptions (a proxy authenticates with a key -> cannot carry a subscription; transport stays
  derived).
- No supervisor wiring (T4); no manifest persistence (T1b); no fallback between backends.

## Depends on

T1a (consumes the resolver's reachability contract). `claude-max` (future) additionally depends on T0.
