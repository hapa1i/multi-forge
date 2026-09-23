# September model refresh checklist

Current focus: review [PR #255](https://github.com/hapa1i/multi-forge/pull/255). Merge and shipped closeout remain
pending.

- [x] Verify releases and exact provider IDs against official sources and OpenRouter.
- [x] Add intrinsic capabilities, aliases, routes, alternatives, and named workers for all eleven new entries.
- [x] Promote Opus 5.5 defaults while preserving explicit Opus 5 selection.
- [x] Verify LiteLLM 1.102 packaging, pricing, Gemini 3.8, and GPT-6/Opus request compatibility.
- [x] Update live defaults, design docs, end-user migration guidance, and QA expectations.
- [x] Run focused tests, required targeted integration, full unit/regression checks, and pre-commit.
- [x] Build and smoke-test a clean wheel; verify new realization and existing snapshot preservation.
- [x] Review integrated diff and record verification.
- [x] Open one PR: [#255](https://github.com/hapa1i/multi-forge/pull/255).
- [ ] Merge and record shipped closeout.

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
- Targeted integration: 34 checks passed on the initial run; all eight Opus checks passed after correcting test
  fixtures. Coverage includes native Anthropic, local LiteLLM, OpenRouter, streamed responses, and Docker session
  routing.
- `make test-unit`: 10,368 passed, 117 deselected by the unit target. `make test-regression`: 1,229 passed; the
  subsequently added smoke-log regression also passed. Both full suites report the existing Starlette deprecation
  warning. `make pre-commit` passed, including type, file-size, and Markdown-link checks.
- Native Codex and mixed `claude-opus,codex` blind panels passed; the latter resolved Opus to `claude-opus-5-5`.
- Fresh Anthropic/OpenRouter/Gemini proxy realization uses new defaults. Reloading saved Opus 5/Gemini 3.7 selections
  leaves bytes and selections unchanged; an older materialized backend is reported as outdated without being rewritten.
- `make build` and two clean-wheel start/health/stop runs passed with LiteLLM 1.102 on Python 3.12.3, including the
  default port. An initial startup failure could not be reproduced with the same dependencies; its original log was
  removed by cleanup. The smoke script now prints failed-start logs before cleanup, covered by a passing regression.

LiteLLM 1.102's Batch cost calculator omits the above-272K premium. Standard, Flex, and Priority Responses pricing is
covered by isolated cost tests; this change does not add Batch transport variants.
