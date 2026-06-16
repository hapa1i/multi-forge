# OpenRouter `user` injection for direct `core.llm` callers

**Status**: Todo. Spun out of `openrouter_observability` Phase 5 (2026-06-16), which shipped `user`-field injection on the
**proxied** path only. This card extends the same observability to Forge's **direct** OpenRouter callers.

## Problem

Phase 5 records the Forge session grouping id in OpenRouter's top-level `user` field for **proxied** direct-OpenRouter
traffic (forks, supervisor — the incident path), gated by per-proxy `provider_trace.inject_openrouter_user`. Forge also
makes **direct** `core.llm` calls to OpenRouter that bypass the proxy and so carry no `user`:

- `policy/semantic/plan_check.py` — `DEFAULT_PLAN_CHECK_PROVIDER = "openrouter"`
- `session/transfer.py` (memory curation) — `AI_CURATION_PROVIDER = "openrouter"`

These are not in any OpenRouter `/generation` grouping today. The tagger (`core/reactive/tagger.py`) is **excluded by
design** — it calls `get_client(model)` with no provider and routes via local LiteLLM, so it structurally cannot reach
OpenRouter (changing that is a routing change, not a header change).

## Scope

- **In**: a `with_openrouter_user(hyperparams, user_id)` helper (`core/usage/correlation.py`) mirroring
  `with_forge_request_id` — deep-copy, **no-clobber** (preserve an explicit caller `user`), writes `extra["openai"]["user"]`
  (the verified top-level-`user` channel, proven in Phase 5's `test_openrouter.py`). Wire it into plan-check + curation:
  derive `user_id = derive_provider_session_id(os.environ.get("FORGE_SESSION"), <root_run_id>, role)` (same env keys
  `core/reactive/env.py` reads), gate on the existing `provider == "openrouter"`, behind the opt-in.
- **Out**: the proxied path (shipped); the tagger (routing limitation); remote reconciliation.

## Open question — flag home

Phase 5's flag is per-proxy (`provider_trace.inject_openrouter_user`), which direct callers cannot read (different
process, no proxy binding). The direct-call opt-in needs an in-process source. **Leading candidate**:
`~/.forge/config.yaml` (`forge.runtime_config`, in-process readable, three-layer defaults→file→env) — *not* an env var
(an upstream-visible behavior should not depend on ambient process state). Decide whether one logical toggle should
govern both paths or whether proxied and direct keep separate (documented) homes.

## Constraints

- **Fail-open**: plan-check (-> `needs_review`) and curation (-> structured fallback) must not be altered by any new
  raise. Injection is pure dict ops; derive defensively.
- **Privacy**: hashed `forge_sess_<hash>[_role]` (or `forge_run_<hash>` fallback) only — never the raw session name or a
  filesystem path. Add a "no path leak" test (`test_plan_check.py`).
- **No second opt-in source** without an explicit decision: the whole reason the helper + callers were deferred from
  Phase 5 was to avoid splitting the opt-in across two homes before this question is answered.

## References

- Phase 5 shipped code: `proxy/server.py` (`_openrouter_user_value`), `proxy/client_adapter.py`
  (`extra["openai"]["user"]` forward), `config/schema.py` (`ProviderTraceConfig.inject_openrouter_user`).
- Channel proof: `tests/src/core/llm/test_openrouter.py::TestOpenRouterClientComplete::test_user_from_extra_openai_reaches_create_kwargs`.
- Minter: `core/run_id.py::derive_provider_session_id`; header precedent: `core/reactive/env.py::_apply_correlation_headers`.
