# Checklist: Sonnet 5 support + default-tier flip

**Branch**: `sonnet-5` · **Card**: `card.md` · **Plan**: `~/.claude/plans/fancy-drifting-fountain.md`

## Current focus

**DONE** (2026-07-02). Shipped and merged to `main` via PR #64 (`75cd28b5`); card closed out and moved
`doing/ -> done/`.

## Phase A — catalog spec

- [x] Added `claude-sonnet-5` spec mirroring Opus 4.8 at the sonnet tier (1M, adaptive-only, `supports_top_p: false`,
  `token_estimate_multiplier: 1.35`, `tags: []`). Verified via live `get_model_spec`.

## Phase B — catalog defaults + stale metadata

- [x] Flipped 4 defaults: sonnet -> `claude-sonnet-5`, opus -> `claude-opus-4-8` (anthropic + openrouter).
- [x] `claude-opus-4-8` `tags: []` (was `[bounded-review, opt-in]`).
- [x] Rewrote Opus 4.8 + Fable spec comments; alias comment `# Opus 4.8 (default opus tier)`.

## Phase C — catalog aliases

- [x] Flipped `opus`/`claude-opus` -> `claude-opus-4-8`; `sonnet` -> `claude-sonnet-5`.
- [x] Added Sonnet 5 alias block (`anthropic/claude-sonnet-5`, `claude-sonnet`, `sonnet-5`).
- [x] Fixed stale Fable alias comment.

## Phase D — templates

- [x] `openrouter-anthropic.yaml` (dot-form), `litellm-anthropic.yaml` + `litellm-anthropic-local.yaml` (hyphen-form,
  incl. "must serve" NOTE), `anthropic-passthrough.yaml`. Verified all four load via `load_config`.

## Phase D2 — passthrough validator exemption

- [x] `_proxy_supports_model_pin`: early `return True` for `wire_shape == "anthropic_passthrough"`.
- [x] Regression test `tests/regression/test_bug_passthrough_model_pin.py` (validation + env application for fable-5 /
  opus-4-6 / sonnet-4-6).

## Phase E — estimator defaults

- [x] `PROXY_CONTEXT_MODEL_DEFAULTS` -> `claude-opus-4-8[1m]` / `claude-sonnet-5[1m]`.

## Phase F — tests

- [x] Updated: `test_loader.py` (3 tests + renames), `test_model_catalog_resolution.py`, `test_direct_model.py`,
  `test_model_catalog_validation.py` (renamed), `test_claude_command.py`, `test_session_commands.py`, and
  `test_data_models.py` (fable->opus-tier mapping, found by full suite).
- [x] Added: `TestClaudeSonnet5` + Sonnet 5 pin tests.

### Acceptance table

| Test                                 | Fixture                     | Assertion                                                           | Test File                                                                    | Status |
| ------------------------------------ | --------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------ |
| Sonnet 5 canonical + aliases resolve | catalog load                | `resolve_model_id(...) == "claude-sonnet-5"`                        | `test_model_catalog_resolution.py`                                           | PASS   |
| Sonnet 5 / Opus 4.8 are the defaults | catalog load                | `get_default_model(...)` both providers                             | `test_model_catalog_resolution.py`                                           | PASS   |
| openrouter-anthropic tiers/alts      | `load_config`               | sonnet=`claude-sonnet-5`, opus=`claude-opus-4.8`, alts restructured | `test_loader.py`                                                             | PASS   |
| Estimator defaults track flip        | proxy-context, no `--model` | opus `...-4-8[1m]`, sonnet `...-5[1m]`                              | `test_direct_model.py`, `test_claude_command.py`, `test_session_commands.py` | PASS   |
| Passthrough accepts displaced pins   | passthrough cfg             | validate None + env populated                                       | `tests/regression/test_bug_passthrough_model_pin.py`                         | PASS   |
| Session start `--model` end-to-end   | Docker mock claude          | pins ANTHROPIC\_\* env                                              | `test_session_commands_integration.py`                                       | PASS   |

## Phase G — docs

- [x] `proxy.md`, `model_selection.md`, `session.md`, QA `4-proxy.md` + index `last-updated`, and the 5
  `claude-opus`-default docs (skills/workflow/cli_reference/session/README).
- [x] Design docs verified: `design_appendix.md`/`design.md` reference the template *name* only, not tier defaults — no
  change needed.

## Phase H — closeout

- [x] `make test-unit` (7231 passed); targeted pytest (470 passed); scoped integration (2 passed); `make pre-commit`
  clean.
- [x] `change_log.md` entry (newest-first).
- [x] Merged to `main` via PR #64 (`75cd28b5`); card moved `doing/ -> done/`.
