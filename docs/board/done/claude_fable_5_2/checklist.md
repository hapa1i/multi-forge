# Claude Fable 5.2 implementation checklist

**Branch**: `codex/add-fable-5-2` · **Base**: `main` (`e8540e25`) · **Card**: [card.md](card.md)

## Current focus

Merged through [PR #296](https://github.com/hapa1i/multi-forge/pull/296) on 2026-11-10 as `bdd963b0`. Its tree matches
verified head `e79d805c`. Stable Fable selections use 5.2, and Claude defaults remain unchanged.

## Implementation

- [x] Verify native/OpenRouter IDs, limits, effort, caching, pricing, and ZDR availability.
- [x] Add the model, aliases, direct route, three proxy alternatives, and required-ZDR fallback.
- [x] Supply and verify pinned LiteLLM capability/pricing metadata where needed.
- [x] Preserve explicit older Fable selections, Claude defaults, and saved configuration ownership.
- [x] Update runtime design, model/proxy/workflow guidance, and packaged QA expectations.

## Acceptance

| Check           | Fixture                               | Assertion                                                                             | Test                                  |
| --------------- | ------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------- |
| Selection       | Packaged catalog and routes           | Stable Fable names select 5.2; explicit versions and Claude defaults stay stable      | Catalog, direct-model, workflow tests |
| Proxy ownership | Fresh templates and saved 5/5.1 proxy | Fresh alternatives serve 5.2; old snapshots refuse the alias and retain explicit pins | Config and session-routing tests      |
| Gateway         | Isolated LiteLLM registration         | Native adaptive effort and standard/cache pricing match the provider contract         | Backend metadata tests                |
| Wire behavior   | Local fake upstreams                  | Sampling is filtered, forced tools are rejected, signed passthrough history survives  | Proxy integration tests               |
| Package/launch  | Clean wheel and Docker CLI            | Installed resources resolve the model and launch with the exact native pin            | Session integration and wheel smoke   |

## Verification

- [x] Focused unit and regression checks.
- [x] Targeted proxy and Docker session integrations.
- [x] Aggregate unit/regression suites and full pre-commit, links, size, and diff checks.
- [x] Wheel/sdist build and isolated installed-wheel resource verification.

## Verification evidence

- Focused catalog, routing, templates, worker, backend metadata, and passthrough regressions: 768 passed. The initial
  expectations failed before implementation; a route-schema typo found during implementation was corrected.
- `./scripts/test-integration.sh` targeting `test_fable_52_e2e.py`, installed route resources, direct model launch, and
  OpenRouter health: 18 passed. Tests exercise local LiteLLM/OpenRouter request shapes, streaming, forced-tool
  rejection, ZDR substitution, and signed-prefix passthrough with synthetic upstreams; no live inference ran.
- Final `make test-unit`: 11,624 passed; `make test-regression`: 2,470 passed.
- `make pre-commit`: passed, including type checks, secret scans, Markdown links, formatting, and file-size policy.
  Initial formatting/cache failures were corrected. Runtime design and proxy counts were refreshed; the refresh tool
  removed the model-selection guide's obsolete below-threshold cache entry. Its exact-content unit check then passed.
- `make build`: wheel and sdist built successfully. A temporary installation of that wheel resolved the stable and
  explicit Fable aliases, retained Opus 5.5 as the default, and exposed the native deployment and proxy alternative.
  Loading a saved proxy without the 5.2 alternative preserved its bytes and old Opus selection.
- `./scripts/test-wheel-runtime.sh`: clean locked-dependency install, backend start/health, and process-group teardown
  passed with final exit status zero.
- `forge workflow list-models --available --json` reports `claude-fable` ready on `claude-fable-5-2`. Comparison against
  the branch base confirms unchanged catalog/template defaults and existing model profiles/alternatives; only the
  existing `fable` and `claude-fable` aliases move to 5.2.

## Review fixes

- [x] Add the provider's 1.1x US-only inference multiplier to the Fable 5.2 LiteLLM deployment; the
  [pricing page](https://platform.claude.com/docs/en/about-claude/pricing#data-residency-pricing) applies it to Claude
  4.6+. Fast mode's documented $16/$80 confirms the existing 2x entry.
- [x] Declare Fable 5.1's existing `auto`/`none` tool-choice restriction in the catalog and restore its user guidance.
- [x] Withhold real provider keys from the Fable proxy integration fixture.
- [x] Document the direct-LiteLLM forced-tool limitation and pin offline request conversion with `drop_params` both on
  and off. The deployment keeps `supports_forced_tool_use: false`, but shared registration drops it and the adapter
  forwards forced choices. Forge proxy routes refuse them from the catalog first. A separate offline probe confirms that
  adding `supports_speed: true` also fails to enable fast mode through shared registration; no fast-mode support is
  claimed for this offline backend.
- [x] Keep this verification offline and retain the synthetic proxy gate; native provider inference remains unverified.

Evidence: the new US-multiplier metadata test and `test_bug_fable_51_forced_tools.py` each failed with their fix
reverted. Afterwards, `make test-unit` passed 11,621 tests with one expected token-cache failure, whose 49-test file
passed after refreshing the runtime-design count. `make test-regression` passed 2,470, the targeted Fable integration
passed 13 cases, and `make pre-commit` passed.

The forced-tool follow-up passed 142 focused metadata, catalog, and regression tests, including offline conversion with
both `drop_params` settings. The isolated Fable proxy integration gate passed all 13 cases again. The user guide now
records the direct-LiteLLM limitation and uses the current migration page for Fable 5.1's matching restriction.

## Closeout

- [x] Record verification and any remaining limitations.
- [x] Review/merge and move to `done/`; add the completed-work changelog entry when shipped.
