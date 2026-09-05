# Claude Fable 5.1 implementation checklist

**Branch**: `codex/add-fable-5-1` · **Base**: `origin/main` · **Card**: `card.md`

## Current focus

Completed 2026-09-06. [PR #250](https://github.com/hapa1i/multi-forge/pull/250) merged as `c3b7aa50` with all five
GitHub checks passing.

## Catalog and direct routing

- [x] Add the canonical Fable 5.1 profile with verified limits and effort support.
- [x] Repoint only the unversioned Fable aliases to 5.1 while retaining explicit Fable 5 resolution.
- [x] Add a direct Claude route for Fable 5.1.

## Proxy and workflow surfaces

- [x] Add Fable 5.1 to all three Anthropic template alternative maps using provider-correct slugs.
- [x] Add an audited required-ZDR fallback for the OpenRouter slug without removing the Fable 5 fallback.
- [x] Make the named `claude-fable` review worker resolve to 5.1 through the stable catalog alias.

## Tests and documentation

- [x] Cover catalog identity, family-default aliases, capabilities, direct pins, route integration, templates, ZDR, and
  review-worker resolution.
- [x] Update end-user model-selection, proxy, workflow/skills, README, and packaged QA guidance where behavior changed.
- [x] Update the normative session and proxy-runtime contracts plus end-user routing/intercept guidance for the changed
  route-boundary and native-effort behavior.

## Acceptance tests

| Test               | Fixture                     | Assertion                                                            | Test File                                                |
| ------------------ | --------------------------- | -------------------------------------------------------------------- | -------------------------------------------------------- |
| Family default     | Bundled catalog             | `fable` and `claude-fable` resolve to 5.1; explicit 5 remains stable | `tests/src/core/models/test_model_catalog_resolution.py` |
| Direct routing     | Model route catalog         | 5.1 starts with the exact direct Claude model ID                     | `tests/src/core/models/test_model_routes.py`             |
| Direct pin         | Claude launch environment   | Fable 5.1 rides the opus tier and pins its exact model ID            | `tests/src/core/models/test_direct_model.py`             |
| Proxy alternatives | Three Anthropic templates   | OpenRouter uses dotted slug; LiteLLM uses hyphenated slug            | `tests/src/config/test_loader.py`                        |
| Local backend      | Generated LiteLLM config    | Every model exposed by the local Anthropic template has a route      | `tests/src/backend/test_creation.py`                     |
| Required ZDR       | Audited OpenRouter fallback | Both Fable versions route to Opus 5 when non-ZDR is disallowed       | `tests/src/proxy/test_model_alternatives.py`             |
| Review worker      | Named `claude-fable` worker | Derived direct route selects Fable 5.1                               | `tests/src/review/test_models.py`                        |

## Verification and PR

- [x] Focused unit and regression tests pass.
- [x] Required targeted integration tests pass.
- [x] Full unit, regression, pre-commit, build, link, size, and wheel-runtime gates pass as applicable.
- [x] Commit, push, and open the PR with verification evidence.

## Verification evidence

- Review-focused model/config/proxy/routing suite: 432 passed; the final direct-model/catalog rerun passed 140 tests,
  and the security-boundary proxy rerun passed 68 tests.
- Targeted Docker integration passed the offline OpenRouter health check, local LiteLLM health check, and both direct
  model launch cases.
- Full unit suite: 10,149 passed and 117 deselected.
- Full regression suite: 1,180 passed.
- The complete pre-commit suite passes, including mypy, pyright, repository file-size limits, Markdown links, and
  mdformat.
- The final `make build` produced the wheel and sdist; an exact-wheel import outside the checkout loaded the packaged
  catalog, route catalog, and OpenRouter template and resolved `fable` to `claude-fable-5-1`.
- The generated LiteLLM backend config exposes every model referenced by `litellm-anthropic-local`; no claim is based on
  the pinned runtime's stale bundled Fable metadata.
- CodeQL's exception-exposure warning is covered by a regression test: detailed validation text remains in server logs
  and the HTTP response contains only stable guidance plus the Forge request ID.
- Pull request: [#250](https://github.com/hapa1i/multi-forge/pull/250).

## Closeout

- [x] Merge the pull request to `main`.
- [x] Move this card to `done/` and record the merged commit.
