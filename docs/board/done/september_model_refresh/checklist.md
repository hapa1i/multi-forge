# September model refresh checklist

Completed 2026-09-23. [PR #255](https://github.com/hapa1i/multi-forge/pull/255) merged as `e107dd13` with all five
GitHub checks passing. Its tree matches the verified branch head `6258db15`; design and end-user docs are synchronized.

- [x] Verify releases and exact provider IDs against official sources and OpenRouter.
- [x] Add intrinsic capabilities, aliases, routes, alternatives, and named workers for all eleven new entries.
- [x] Promote Opus 5.5 defaults while preserving explicit Opus 5 selection.
- [x] Verify LiteLLM 1.102 packaging, pricing, Gemini 3.8, and GPT-6/Opus request compatibility.
- [x] Update live defaults, design docs, end-user migration guidance, and QA expectations.
- [x] Run focused tests, required targeted integration, full unit/regression checks, and pre-commit.
- [x] Build and smoke-test a clean wheel; verify new realization and existing snapshot preservation.
- [x] Review integrated diff and record verification.
- [x] Open one PR: [#255](https://github.com/hapa1i/multi-forge/pull/255).
- [x] Reject invalid Sol/Luna tier temperatures at config load while preserving model-alternative filtering.
- [x] Spell the LiteLLM pin explicitly and document Opus 5.5's intentional cache-read discount.
- [x] Merge, synchronize documentation, record closeout, and move the card to `done/`.

| Test                  | Fixture                                     | Assertion                                                              |
| --------------------- | ------------------------------------------- | ---------------------------------------------------------------------- |
| Catalog routes        | Packaged catalogs                           | All new IDs resolve and have valid source-owned candidates             |
| Saved configuration   | Existing proxy/backend files                | Package refresh leaves user choices and bytes unchanged                |
| Native metadata       | Local-only LiteLLM map                      | Correct costs and supported reasoning survive without network metadata |
| Request compatibility | Tools plus reasoning, streamed/non-streamed | Sol/Luna use Responses; Opus uses adaptive effort                      |
| Gemini support        | Local LiteLLM Google route                  | Gemini 3.8 completion reports thinking usage and cost                  |
| Packaging             | Clean wheel environment                     | Packaged backend starts, reports healthy, and stops                    |

## Verification

- Catalog, routes, configuration, provider requests, and workflow focused checks pass. Mixed-family workers resolve
  through a selected OpenRouter proxy; sampling on Sol/Luna is preserved only at effective effort `none`.
- Review coverage: 369 focused config/request checks and 10 pricing/metadata checks passed. Regression cases cover
  template and instance loading, unset and active reasoning, zero temperatures, explicit `none`, and model alternatives.
  Seven live GPT-6 reasoning/tool/cost checks passed; the rebuilt wheel declares `litellm==1.102.0`.
- Targeted integration: 34 checks passed on the initial run; all eight Opus checks passed after correcting test
  fixtures. Coverage includes native Anthropic, local LiteLLM, OpenRouter, streamed responses, and Docker session
  routing.
- `make test-unit`: 10,368 passed, 117 deselected by the unit target. `make test-regression`: 1,266 passed. Both full
  suites report the existing Starlette deprecation warning. `make pre-commit` passed, including type, file-size, and
  Markdown-link checks.
- Native Codex and mixed `claude-opus,codex` blind panels passed; the latter resolved Opus to `claude-opus-5-5`.
- Fresh Anthropic/OpenRouter/Gemini proxy realization uses new defaults. Reloading saved Opus 5/Gemini 3.7 selections
  leaves bytes and selections unchanged; an older materialized backend is reported as outdated without being rewritten.
- `make build` and two clean-wheel start/health/stop runs passed with LiteLLM 1.102 on Python 3.12.3, including the
  default port. An initial startup failure could not be reproduced with the same dependencies; its original log was
  removed by cleanup. The smoke script now prints failed-start logs before cleanup, covered by a passing regression.

LiteLLM 1.102's Batch cost calculator omits the above-272K premium. Standard, Flex, and Priority Responses pricing is
covered by isolated cost tests; this change does not add Batch transport variants.

## 1.0.1 release verification

The maintainer explicitly waived fresh manual QA for 1.0.1 and authorized publication using the completed PR and
exact-wheel checks. This disposition applies only to 1.0.1; no new manual QA pass or reuse of an older artifact identity
is claimed.

The release candidate is `dist/multi_forge-1.0.1-py3-none-any.whl`, SHA-256
`9a8a6da9b533badf64cd93792ad37299df72c9607130bc75608e03a8e4005e72`. Its product source matches the verified merged tree;
only the version, lockfile project version, and board closeout changed afterward.

- `make build` and the full `make pre-commit` suite passed; 39 release metadata, catalog, and QA-contract tests passed.
- This exact wheel installed into a fresh Python 3.13.11 environment, resolving 86 packages outside `uv.lock`.
  Dependency compatibility and `forge --version` passed.
- Packaged checks loaded all 88 catalog models, 86 route entries, and 20 templates, and verified new defaults, retained
  alternatives, eight Sol/Luna pricing cases, and Opus adaptive effort translation.
- The isolated LiteLLM backend passed create/start/health/stop on port 49178. Its materialized config and the wheel's
  SHA-256 were unchanged afterward.
