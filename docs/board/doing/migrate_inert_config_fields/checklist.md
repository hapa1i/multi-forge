# Retire inert configuration fields checklist

Current focus: Wave 7 order 12 is active from `c99be7a3`; keep orders 13--35 parked.

## Activation and evidence

- [x] Close order 11 on pushed `main` at `c99be7a3`, branch from that exact closeout, and move only order 12 to
  `doing/`.
- [x] Recheck `ProviderConfig.enable_preamble`: it remains declaration-only with no template, loader, runtime, resource,
  extension, or documentation consumer.
- [x] Recheck `ProviderConfig.openai_api_mode`: four shipped templates emit it and the loader/orchestrator preserve it,
  but no request, provider, backend, or wire-shape path consumes it.
- [x] Recheck `SessionConfig.manifest_filename`: it remains declaration-only while `MANIFEST_FILENAME` constructs every
  durable session path.
- [x] Keep all three fields accepted in the 0.9.4 schema; this member warns on explicit raw keys and stops new emission
  but does not delete or reject them.
- [x] Run unchanged config schema, loader, template, proxy-creation, and session-path characterization before editing
  (`434 passed`).

## Implementation

- [x] Detect deprecated keys at raw user-owned config boundaries so omission is distinguishable from an explicit
  default-valued key.
- [x] Emit actionable, one-time warnings for explicit template/session keys and proxy-instance
  `provider_settings.openai_api_mode`; keep old values readable and behaviorally inert.
- [x] Remove all three keys from new serialization and remove `openai_api_mode` from shipped templates and proxy
  creation/runtime handoff.
- [x] Preserve backend/wire-shape routing, all nondeprecated provider settings, strict unknown-key validation, and
  `MANIFEST_FILENAME` path ownership.
- [x] Document the warning window, removal action, and fixed manifest path in the end-user proxy/configuration guide.
- [x] Correct review-found release provenance: the window protects config authored by Forge 0.9.4 or earlier; it is not
  behavior shipped in the already released 0.9.4.
- [x] Guard `PROVIDER_CONFIG_NAMES` against drift from the `ProviderConfig` fields on `ProxyConfig`.

## Acceptance tests

| Boundary                | Fixture                                      | Assertion                                                   |
| ----------------------- | -------------------------------------------- | ----------------------------------------------------------- |
| Raw template config     | omitted and explicit deprecated provider key | omission is silent; explicit key warns and remains readable |
| Raw session config      | explicit `session.manifest_filename`         | warning names removal and fixed manifest path authority     |
| Existing `proxy.yaml`   | `provider_settings.openai_api_mode`          | loads with one warning and no runtime transport effect      |
| New config generation   | shipped templates and proxy writer           | deprecated keys are absent                                  |
| Unrelated configuration | provider settings, blocks, tier overrides    | validation, copying, and runtime behavior remain unchanged  |

## Verification and closeout

- [x] Run focused schema/loader/template/proxy-creation tests (`438 passed`) and the named O049 regression suite
  (`6 passed`).
- [x] Build the 0.9.4 wheel/sdist, pass the clean-wheel LiteLLM runtime smoke, and verify the exact wheel's packaged
  `litellm-openai` template plus no-start proxy output omit deprecated keys while retaining `error_hints`.
- [x] Run `make test-unit` (`9,197 passed`, `1 skipped`, `122 deselected`), `make test-regression` (`913 passed`), and
  `make pre-commit`.
- [x] Run board link/lane/size and diff checks: all 885 local links across 345 Markdown files resolve, the Wave 7 graph
  is 11 `done` / 1 `doing` / 23 `todo`, no stale order-12/13 lane target remains, living docs stay below 30k tokens, and
  `git diff --check` passes.
- [x] Open draft PR #191 for order 12.
- [ ] After merge, close this member before selecting order 13.
