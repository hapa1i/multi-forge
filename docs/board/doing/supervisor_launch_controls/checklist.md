# Checklist: supervisor_launch_controls

Branch: `supervisor_launch_controls` · Plan: `~/.claude/plans/stateful-zooming-pancake.md` (approved after 2 review
rounds). Grounded by a 4-agent understand workflow + 2 plan agents + claim-verification sweeps.

Decouple two things and ship both: (1) launch-time **cascade parity** for `forge session fork/start --supervise`, and
(2) **reasoning effort across every Forge `claude -p` subprocess**, per-caller (no global knob). User decisions baked
in: all three knobs in scope; per-caller config; two effort vocabularies; fail-loud on unsupported `--effort`.

**Current focus:** Closeout (all phases implemented + verified; `make pre-commit` clean; integration green).

## Decisions resolved by you

- **Scope:** all three knobs (cascade parity + `--checker-effort` + `--supervisor-effort`), generalized to ALL `-p`
  callers.
- **Config model:** per-caller effort fields/flags; **no** global `RuntimeConfig` default.
- **Two vocabularies (verified from `claude --help`):** Claude `--effort` = `{low,medium,high,xhigh,max}` (no `none`);
  core.llm `ReasoningEffort` = `{none,low,medium,high,xhigh}` (no `max`). `max` Claude-only; `none` checker-only.
- **Unsupported `--effort` → fail loud** (effort changes behavior; unlike the `--output-format` telemetry retry).
- **One-shot `policy supervisor`:** only `--supervisor-effort` now; one-shot `--cascade --plan-file` deferred (so
  `--checker-effort` there would be inert).
- **Validator homes:** `validate_claude_effort` in a top-level typing-only leaf `core/effort.py` (corrected from the
  planned `core/reactive/effort.py` — that package's `__init__` eagerly imports the heavy session runner, which would
  re-introduce a cycle into the foundational `session/models.py`); `validate_reasoning_effort` in `core/llm/types.py`.

## Phase 1 — Cascade parity + shared checker-helper extraction

- [x] Extracted into `src/forge/policy/semantic/supervisor.py` (no Click): `CHECKER_PROVIDER_CHOICES` tuple,
  `normalize_checker_provider_arg`, `validate_checker_model` (raises `ValueError` w/ verbatim "prefixed model id"),
  `apply_checker_options(sup, *, checker_model, checker_provider, checker_effort=None)`.
  - Verified: `cli/policy.py` imports the shared helpers; `test_supervisor.py::TestSupervisorEffort` covers them.
- [x] Consolidated `plan_check._normalize_checker_provider` to call the shared `normalize_checker_provider_arg`.
  - Verified: single normalization source; `test_plan_check.py` provider tests pass.
- [x] Refactored `supervise_cmd` to call the extracted helpers; "prefixed model id" error preserved.
  - Verified: `test_policy_supervisor.py::test_checker_model_must_be_prefixed` still exits 1 "prefixed model id".
- [x] Added `--cascade`/`--checker-model`/`--checker-provider` (+`--checker-effort`/`--supervisor-effort`) to fork and
  start, requiring `--supervise`; attached at the supervisor seams. Cascade-at-launch sets `cascade=True` only.
  - Verified: unit `test_session_commands.py::TestSupervisorLaunchControls` (persist cascade+checker+effort, no plan
    resolution, require-`--supervise`) + integration `test_fork_supervise_cascade_effort_persists`.

## Phase 2 — General `--effort` capability

- [x] `core/effort.py` (top-level typing-only leaf — NOT `core/reactive/effort.py`, whose `__init__` is heavy):
  `CLAUDE_EFFORT_LEVELS` + `validate_claude_effort` (from `get_args`); `validate_reasoning_effort` +
  `REASONING_EFFORT_LEVELS` in `core/llm/types.py`. `session/models.py` keeps an inline `_CHECKER_EFFORT_LEVELS` mirror
  (drift-guarded by a test) to stay import-light.
  - Verified: `import forge.session.models` clean; `test_effort.py` (vocab boundaries + validators + drift guard).
- [x] `run_claude_session` (`session_runner.py`): `reasoning_effort` param → `--effort` after `--model`; **fail loud**
  on unsupported (`_is_effort_flag_rejection`, no silent rerun-at-default).
  - Verified: `test_session_runner.py::test_reasoning_effort_adds_flag_after_model` +
    `test_reasoning_effort_fails_loud_when_unsupported` (asserts `mock_run.call_count == 1`).
- [x] `review/engine.py:_prepare_worker` argv gets `--effort` after `--model`; `run_multi_review` forwards it.
  - Verified: `test_engine.py::TestReasoningEffort` (argv carries `--effort` after `--model`; omitted when None).

## Phase 3 — Per-caller effort wiring

- [x] 3a Supervisor frontier: `SupervisorConfig.supervisor_effort` threaded into `run_supervisor_check`;
  `--supervisor-effort` on fork/start/policy supervise. Verified: `test_supervisor.py` forwarding test.
- [x] 3b Tier-1 checker: `SupervisorConfig.checker_effort` (core.llm vocab) populates `ModelHyperparameters` in
  `run_plan_check` (merged via `merge_hyperparams`) + effort appended to the cache key; `--checker-effort` on
  fork/start/policy supervise. Verified: `test_plan_check.py` hyperparams-forwarding + cache-varies-by-effort tests.
- [x] 3c Memory writer: `MemoryWriterConfig.effort` threaded into `run_memory_writer`; `--effort` on `enable_cmd` via
  `_set_memory_activation`; **early-return fixed** to short-circuit only when enabled/mode/effort are all unchanged.
  Verified: `test_memory_writer.py` forwarding + `test_memory.py` early-return regression.
- [x] 3d Shadow curation: `run_shadow_curation` `reasoning_effort` param + `--effort` on
  `memory shadows review --curate` (inherits the writer's configured effort when omitted). Verified:
  `test_shadow_curation.py` forwarding.
- [x] 3e Team supervisor: `TeamSupervisorConfig.effort` threaded into `_run_supervisor` (manifest-only, no CLI).
  Verified: `test_handlers.py` forwarding + `test_config.py` vocab validation.
- [x] 3f Workflow: `reasoning_effort` threaded through `run_multi_review` (+ `run_adversarial`/`run_consensus` forward);
  `--effort` on `workflow panel/analyze/debate/consensus`. Verified: `test_workflow.py::TestEffortFlag`.

## Phase 4 — One-shot `policy supervisor`

- [x] Added only `--supervisor-effort` to `supervisor_cmd` ephemeral config.
  - Verified: `test_policy_supervisor.py::TestSupervisorOneShotEffort` (config `supervisor_effort=="high"`;
    `--checker-effort` is "no such option") + integration `test_supervisor_effort_reaches_claude_argv`
    (`--effort medium` in the logged claude argv).

## Validation, schema, docs

- [x] Effort fields validated shape-only in each `__post_init__` (two vocabularies); additive optional fields, no
  `SCHEMA_VERSION` bump. Verified: `test_store.py::TestEffortVocabularyValidation`, `test_config.py`.
- [x] Docs: help strings; `docs/end-user/session.md` (launch controls + cascade asymmetry + two vocabularies) +
  `memory.md` (writer `effort`); `docs/cli_reference.md`; supervisor/`-p` section of `docs/design_workflows.md`.

## Closeout

- [x] Acceptance-table tests green (906 passed across new+touched unit files); `make pre-commit` clean.
- [x] Scoped integration green: `test_session_commands_integration.py::test_fork_supervise_cascade_effort_persists`,
  `test_supervisor_e2e.py::test_supervisor_effort_reaches_claude_argv`.
- [x] `docs/board/change_log.md` entry added; durable invariants flagged for `impl_notes.md` (after human review).
- [ ] Move card `doing/ -> done/` after merge to `main`.

## Deferred follow-ups (recorded on card)

One-shot `--cascade --plan-file`; global `RuntimeConfig` default-effort; per-model workflow effort; per-model catalog
effort validation; explicit model/tier lever for memory writer / team supervisor.

## Acceptance Test Table

See the approved plan (`~/.claude/plans/stateful-zooming-pancake.md`, "Acceptance test table") — implemented verbatim:
per-consumer effort-forwarding (patched `run_claude_session`/adapter), the two-vocabulary validation matrix, the memory
enable early-return regression, fork/start cascade+effort persistence, `run_claude_session` fail-loud, and the
integration (launch persistence) + supervisor-E2E (`--effort` in logged argv) checks.
