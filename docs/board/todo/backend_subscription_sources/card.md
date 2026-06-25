# T2 -- Backend: runtime-native subscription sources

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the shared lane contract (backend =
`ModelSource`; billing is a property of the backend).

**Lane**: `todo/` (accepted, first wave). No execution branch open yet.

**Proves**: billing-as-a-property-of-the-backend, honestly shaped -- a subscription is representable without faking an
endpoint.

## Goal

Make a subscription backend a first-class `ModelSource`: add a `runtime_native` access shape (auth via the runtime's
native login, no URL), a first-class billing posture, and the `(runtime, backend)` reachability the resolver reads.
**Explicit access/billing vocabulary; no faked endpoints.**

**Scope the first source to the proven path.** Ship **`chatgpt`** only (reached via `codex`, where
`chatgpt_tokens -> subscription_quota` is verified in `codex_preflight.py`). **`claude-max` is deferred** -- it asserts
`claude -p` rides a Max subscription, which the epic flags as a likely-stale assumption (`billing.py`); gate it on the
sibling billing proof (T0), do not ship it on faith. See Non-goals.

## Not durable state (verified)

The catalog is **code-defined**: `BUILTIN_MODEL_SOURCES` is a `tuple[ModelSource, ...]` validated at import
(`src/forge/backend/sources.py:269,440`) -- no on-disk schema, no deserializer. So this is an **internal-surface clean
break** (coding_standards §5 "Internal surface"): extend the enums + dataclass and update all callers atomically. **No**
schema version / strict-deser / reset path -- those belong to T1b's session manifest.

## Scope (concrete changes)

- `EndpointKind` (`sources.py:19`): add `runtime_native`. Keep **one** enum. If "endpoint" becomes a misnomer, rename
  the type in the same change -- do not add a second parallel access enum.
- `SourceEndpoint` (`sources.py:37`): add a `runtime_native()` factory + a `_validate_endpoint` arm (no `value`, no
  `default_url`, like `local_backend`).
- `_validate_source` (`sources.py:162`): allow a `kind="remote"` source to use a `runtime_native` endpoint with no
  `local_lifecycle`.
- `ModelSource` (`sources.py:103`): add `billing_posture: BillingPosture = "per_token"`, where
  `BillingPosture = Literal["per_token", "subscription_quota", "free"]`. One spelling, shared with T5 (epic
  `checklist.md`).
- **Provider vocabulary (required -- verified gap).** `ProviderType` (`core/provider_types.py:7`) is
  `{litellm_remote, litellm_local, anthropic, openrouter}` -- no `openai`, so a `chatgpt` source fails
  `_validate_source` at import. Add `openai`. `provider_types.py` is the single source of truth
  (`core/llm/detection.py:7` re-imports it), but the closed set is **branched on** downstream -- update:
  `detect_provider` / `is_implemented` (`core/llm/detection.py`) and the provider branches in `cli/backend.py`
  (list/display `:318`; health-probe auth `:426,448,452`). A `runtime_native` source has no endpoint, so the probe at
  `cli/backend.py:423` returns "endpoint is not configured" -- runtime-native sources are probe-**skipped**, not given a
  new probe branch.
- New catalog entry: **`chatgpt`** (provider `openai`, endpoint `runtime_native`, billing `subscription_quota`).
- Reachability: encode that `chatgpt` is reachable only via the `codex` runtime (consumed by the T1a resolver).

## Open design decisions (resolve in this ticket)

- **Runtime-native credentials.** `_validate_source` (`sources.py:169`) requires >=1 `credential_id`, and
  `source_bearer_auth_env_var` (`sources.py:405`) assumes a secret bearer env var. A subscription source's auth is the
  runtime's native login (codex `chatgpt_tokens`), not an env secret. Decide how a `runtime_native` source expresses
  auth without inventing a fake env var -- e.g. a credential entry with no required env var, or relax the ">=1
  credential" rule for `runtime_native`. Coordinate with `codex_preflight.py` (resolves
  `chatgpt_tokens -> subscription_quota`).
- **`claude-max` billing (deferred, gated on T0).** Adding `claude-max` requires proving `claude -p` actually rides the
  Max subscription. Today `infer_billing_mode` "never guesses subscription modes" and the epic flags the `claude -p`
  OAuth/subscription assumption as likely stale. Resolve via T0 (sibling billing cleanup) **before** a `claude-max`
  source claims `subscription_quota`.

## Acceptance (definition of done)

| Test                             | Fixture                 | Assertion                                                                                         | Test File                                                            |
| -------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| Subscription source, no endpoint | `chatgpt` catalog entry | validates with a `runtime_native` endpoint -- no URL, no lifecycle                                | `tests/src/backend/test_sources.py`                                  |
| Billing posture is stored        | `chatgpt`               | `billing_posture == "subscription_quota"` as a field, not inferred                                | `tests/src/backend/test_sources.py`                                  |
| Per-token default preserved      | every existing source   | `billing_posture == "per_token"` by default (no behavior change)                                  | `tests/src/backend/test_sources.py`                                  |
| Provider vocabulary expanded     | `chatgpt`               | `provider="openai"` validates; `cli/backend.py` list handles it; the probe skips it (no endpoint) | `tests/src/backend/test_sources.py`, `tests/src/cli/test_backend.py` |
| Reachability pins runtime        | resolver input          | `chatgpt` reachable only via `codex`                                                              | `tests/src/core/test_lanes.py`                                       |
| No faked endpoint                | `chatgpt`               | constructing it with a `literal_url` is rejected; `runtime_native` has no `value`                 | `tests/src/backend/test_sources.py`                                  |

## Non-goals

- **No `claude-max` source in T2** -- deferred until T0 proves `claude -p` subscription billing; do not assert
  `subscription_quota` for `claude-max` on faith.
- No proxy support for subscriptions (a proxy authenticates with a key -> it cannot carry a subscription; transport
  stays derived).
- No supervisor wiring (T4); no manifest persistence (T1b).
- No fallback between backends.

## Depends on

T1a (consumes the resolver's reachability contract). `claude-max` (future) additionally depends on T0.
