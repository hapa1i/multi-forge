# Execution checklist

Base: `2ec4a22a`. Branch: `codex/gemini-4-argon`. Scope: Gemini Argon catalog/default adoption.

- [x] Create a separate worktree from freshly fetched main.
- [x] Verify public model identity, context/output limits, thinking and sampling controls.
- [x] Add catalog aliases, model routes and workflow selection while retaining explicit older models.
- [x] Promote fresh Gemini Sonnet/Opus templates and verify native adapter support.
- [x] Preserve saved proxy/backend snapshots and document opt-in migration.
- [x] Run focused model/routing/accounting checks and targeted Docker integration.
- [x] Build wheel/sdist and verify packaged resources from an isolated install.
- [x] Run full pre-commit and applicable aggregate checks; resolve review findings.
- [ ] Review/merge and record closeout before moving to done.

## Evidence

Initial dependency setup failed with `No space left on device`; it succeeded after the user freed disk space. Docker
verification also resumed after Docker Desktop restarted.

- Catalog, model routes, workflow selection and configuration checks: 536 passed.
- Session snapshot preservation and QA checklist contract: 87 passed.
- Targeted integration runner passed all 16 backend CLI, proxy/backend and hermetic OpenAI routing tests. No provider
  inference was performed; `GEMINI_API_KEY` was absent.
- Review fixes cover Vertex's narrower non-streaming limit, provider-specific migration instructions, and current
  workflow documentation. Real SDK regression checks cover token overrides, streaming, and unaffected provider routes.
- Native thinking conversion and Vertex limits: 303 focused tests passed. Metadata, actual LiteLLM 1.102 request
  conversion, and packaged dependency-floor checks: 29 passed.
- `make build` passed. An isolated wheel install verified Argon catalog, aliases, routes, backend and template
  resources; the packaged LiteLLM backend started, returned healthy, stopped, and released its endpoint. Dependencies
  remain unchanged.
- Independent review exercised Forge through the actual LiteLLM 1.102 API and Router with synthetic upstream HTTP,
  confirming native thinking levels, tool preservation, and provider-specific output limits without provider inference.
- `forge workflow list-models --json` lists Argon, explicit Gemini 3.1 Pro, and Flash with their provider routes. No
  compatible active proxy was available for live inference.
- `make test-unit`: 10,804 passed, 117 integration tests deselected.
- `make test-regression`: 1,670 passed. After the final native token-override fix, 250 focused regression/core-client
  tests passed, including the two newly added override cases.
- `make pre-commit`: passed. The final independent review found no remaining actionable issues; its complete offline
  HTTP pipeline covered 18 alias/effort/streaming combinations and both native token-limit spellings.

Implementation is ready for review in the worktree. Merge and shipped closeout remain pending.
