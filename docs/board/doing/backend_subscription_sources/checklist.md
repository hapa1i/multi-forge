# Checklist: T2 -- Backend: runtime-native subscription sources

**Card**: `card.md` (this dir). **Epic**: `docs/board/doing/epic_consumer_lanes/`. **Branch**:
`backend_subscription_sources` (off `main` @ `82076324`, the T3 closeout).

## Current focus

Board set up (branch + lane move). Touchpoints **verified against `main` @ `82076324`** (sweep below). **One design
decision needs sign-off before any source change** (Decision A -- runtime-native credential shape); Decisions B/C are
resolved below. No `src/` changed yet.

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

- [ ] **Decision A -- runtime-native credential shape.** A `chatgpt` source's auth is codex's native
  `chatgpt_tokens`/device-auth login -- no env secret -- but `_validate_source:169` requires `>=1 credential_id`.
  - **(a) [recommended] a real `Credential("chatgpt", env_vars=())`** with rich `note`/`signup_url`/`not_needed_for`
    (e.g. "ChatGPT subscription via `codex login --device-auth`; no key to store"). Source
    `credential_ids=("chatgpt",)`. Preserves the `>=1` invariant; gives a home for the login guidance Forge's credential
    surface already provides (`format_missing_credential_error`, `forge auth status`), consistent with
    `codex-api`/`anthropic-api`. `required_env_vars` -> `()`; `source_bearer_auth_env_var` is never called on it. Cost:
    confirm `_auth_record` (`backend list`) and `forge auth login -c chatgpt` render a no-env credential sanely (no
    crash, no misleading "missing").
  - **(b) relax the `>=1 credential` rule for `runtime_native`** -- source `credential_ids=()`; `_validate_source`
    allows empty creds when `endpoint.kind == "runtime_native"`. Most literally honest ("no Forge-managed credential");
    but no guidance home and weakens the invariant.
  - *Pending user sign-off.*
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

- [ ] Add `BillingPosture = Literal["per_token", "subscription_quota", "free"]` to `backend/sources.py` + `__all__`.
- [ ] Add `ModelSource.billing_posture: BillingPosture = "per_token"`. Assertion: every existing source keeps
  `billing_posture == "per_token"` (no behavior change); `mypy`/`pyright` clean.

### Phase 2 -- `runtime_native` access shape

- [ ] `EndpointKind` += `"runtime_native"` (keep **one** enum; rename the type only if "endpoint" becomes a clear
  misnomer -- do not add a second).
- [ ] `SourceEndpoint.runtime_native()` factory (`kind="runtime_native"`, no `value`, no `default_url`) +
  `_validate_endpoint` arm rejecting any `value`/`default_url` (mirrors `local_backend`).
- [ ] `_validate_source`: a `kind="remote"` source may use a `runtime_native` endpoint with **no** `local_lifecycle`.
  Assertion: constructing a `runtime_native` source with a `literal_url` (or any `value`) is rejected.

### Phase 3 -- provider vocabulary + display/probe

- [ ] `ProviderType` (`core/provider_types.py:7`) += `"openai"`. Assertion: `get_args(ProviderType)` includes `openai`;
  full unit suite + `mypy`/`pyright` stay green (no exhaustiveness break -- verified none exists).
- [ ] `cli/backend.py::_probe_model_source`: early
  `return _ProbeResult(status="skipped", detail="runtime-native auth; no endpoint to probe")` for
  `endpoint.kind == "runtime_native"`, before the base_url check.
- [ ] Verify `_auth_record` renders a `runtime_native` / no-env-credential source without a misleading status (adjust if
  it asserts `>=1` env var). Assertion: `forge model backend list --json` shows the source with `provider="openai"`,
  `health` skipped, and an honest auth label.
- [ ] Leave `detect_provider`/`is_implemented` **unchanged**; add a one-line comment at the `ProviderType` def noting
  `openai` is catalog-only (never a `core.llm` routing provider). (Card-correction, flagged for reviewer.)

### Phase 4 -- `chatgpt` source + reachability pin (depends on Decision A)

- [ ] `reachable_via: tuple[str, ...] = ()` on `ModelSource` (Decision B). Default empty preserves all sources.
- [ ] `lanes._reachable` reads it (pure `get_model_source` lookup; `backend_id` is already canonical from
  `Lane.__post_init__`). Assertion: `(codex, chatgpt)` reachable; `(claude_code, chatgpt)` not; every existing
  `(runtime, backend)` still reachable.
- [ ] Credential per Decision A.
- [ ] New catalog entry `chatgpt`: `provider="openai"`, `endpoint=runtime_native`,
  `billing_posture="subscription_quota"`, `reachable_via=("codex",)`, `kind="remote"`, no `local_lifecycle`. Assertion:
  `validate_model_sources` passes at import; `get_model_source("chatgpt")` resolves.

### Phase 5 -- tests + docs + closeout

- [ ] Acceptance tests (table below).
- [ ] Design-doc sync: `design_appendix.md` §A.2.1 (`ModelSource` gains `billing_posture` + `runtime_native` access +
  `reachable_via`; add `chatgpt` to the shipped-catalog table). Tick the epic checklist's §A.2.1 design-doc-sync item.
- [ ] `change_log.md` entry (newest-first). `make pre-commit` clean. mypy + pyright clean.
- [ ] After PR merges to `main`: move `doing/backend_subscription_sources/` -> `done/`; epic roster T2 -> done; epic
  "Current focus" -> next cursor (T4).

## Acceptance (definition of done -- extends the card's table)

| Test                             | Fixture                 | Assertion                                                                                    | Test File                                                            |
| -------------------------------- | ----------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Subscription source, no endpoint | `chatgpt` catalog entry | validates with a `runtime_native` endpoint -- no URL, no lifecycle                           | `tests/src/backend/test_sources.py`                                  |
| Billing posture is stored        | `chatgpt`               | `billing_posture == "subscription_quota"` as a field, not inferred                           | `tests/src/backend/test_sources.py`                                  |
| Per-token default preserved      | every existing source   | `billing_posture == "per_token"` by default (no behavior change)                             | `tests/src/backend/test_sources.py`                                  |
| Provider vocabulary expanded     | `chatgpt`               | `provider="openai"` validates; `backend list` shows it; the probe **skips** it (no endpoint) | `tests/src/backend/test_sources.py`, `tests/src/cli/test_backend.py` |
| Reachability pins runtime        | resolver input          | `chatgpt` reachable only via `codex`; existing `(runtime, backend)` pairs unchanged          | `tests/src/core/test_lanes.py`                                       |
| No faked endpoint                | `chatgpt`               | constructing it with a `literal_url` is rejected; `runtime_native` has no `value`            | `tests/src/backend/test_sources.py`                                  |
| `reachable_via` default-empty    | every existing source   | empty `reachable_via` -> reachable by any lane runtime (T1a behavior preserved)              | `tests/src/core/test_lanes.py`                                       |

## Non-goals (from card)

- **No `claude-max` source** -- deferred until T0 proves `claude -p` subscription billing; do not assert
  `subscription_quota` for `claude-max` on faith.
- No proxy support for subscriptions (a proxy authenticates with a key -> cannot carry a subscription; transport stays
  derived).
- No supervisor wiring (T4); no manifest persistence (T1b); no fallback between backends.

## Depends on

T1a (consumes the resolver's reachability contract). `claude-max` (future) additionally depends on T0.
