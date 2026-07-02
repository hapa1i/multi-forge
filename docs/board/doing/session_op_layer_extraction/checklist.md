# Checklist -- Session Op Layer Extraction

Execution plan for `card.md` (this dir). Branch: `session-op-layer`. This card is a staged, behavior-preserving
extraction of Claude session launch/resume logic out of the CLI layer, mirroring the Codex core-ops split.

## Current Focus

**Slice 1 complete (2026-07-02):** characterization safety net added, launch system-prompt resolution extracted into
`forge.core.ops.claude_session`, and the CLI-free model-pin support cluster moved into `forge.session.model_pin`. This
slice intentionally did not touch the dangerous `invoke_claude`/launcher seam; the card remains in `doing/` for Slice 2.

## Verified Baseline

Rechecked against the current tree before work began. Use these values, not the stale counts in `card.md`.

| Fact                                                  | Verified value                                                                        | Card claimed |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------ |
| `session_lifecycle.py` size                           | 2,497 lines                                                                           | --           |
| Parent `patch("forge.cli.session.<name>")` sites      | 270 single-line (+11 multiline), 13 files                                             | 255          |
| Patch concentration                                   | `invoke_claude` 146 + `SessionManager` 54 = 200/270 (74%)                             | --           |
| Split-module patches                                  | 49                                                                                    | 47           |
| `def _sess()` defs                                    | 4: `session_lifecycle.py`, `session_fork.py`, `session_codex.py`, `session_manage.py` | 4            |
| `_apply_and_persist_direct_model_override` call sites | 7                                                                                     | 5            |
| `core/ops/` importing `forge.cli`                     | none                                                                                  | --           |
| Manifest characterization test                        | missing                                                                               | --           |

## Slice 1 Tasks

- [x] Reconcile board cursor before starting: close `rewind_resume_strategy` and move it `doing/ -> done/`.
- [x] Accept this proposal: move `proposed/session_op_layer_extraction` to `doing/session_op_layer_extraction`.
- [x] Create this checklist with the corrected Slice 1 scope and baseline.
- [x] Add manifest characterization coverage before code movement:
  - start path: `forge session start --no-launch`.
  - resume path: one reconnect/fresh branch that exercises the resume manifest surface without launching real Claude.
  - compare normalized JSON strings without `sort_keys` so dataclass field order is pinned.
- [x] Add `src/forge/core/ops/claude_session.py` with `resolve_and_validate_system_prompt`.
  - The helper is CLI-free, not pure: it may create `cwd/.claude/forge.system-prompt.generated.md`.
  - It returns `Path | None`; the CLI converts to `str | None` at the launcher boundary.
  - Do not import `ExecutionContext` until the module actually uses it.
  - `--no-launch` + system-prompt validation remains CLI-owned by the early launch guard; the op does not duplicate it.
- [x] Add `src/forge/session/model_pin.py` and move the CLI-free support cluster intact:
  - `_proxy_supports_model_pin`.
  - `_apply_direct_model_env_if_supported`.
  - `_validate_proxy_model_pin`.
  - `_validate_direct_model_pin_for_routing`.
- [x] Keep UI-tangled persistence in `cli/session_model_pin.py`; no re-export shims for the moved support functions.
- [x] Rewire CLI callers:
  - `session_lifecycle.py` host launcher `_apply_direct_model_env_if_supported`.
  - `session_lifecycle.py` start-path `_validate_proxy_model_pin`.
  - `session_lifecycle.py` resume-path `_validate_direct_model_pin_for_routing`.
  - `session_fork.py` `_apply_direct_model_env_if_supported`.
- [x] Repoint tests that import the moved support functions.
- [x] Record post-slice patch counts: parent patches remain 270 single-line hits across 13 files; split-module patches
  remain 49.

## Slice 1 Assertions

- [x] `src/forge/core/ops/claude_session.py` imports no CLI modules and contains no Click/Rich/rendering/`sys.exit`.
- [x] `src/forge/session/model_pin.py` imports no CLI modules and contains no Click/Rich/rendering/`sys.exit`.
- [x] `src/forge/cli/session_lifecycle.py` line count does not increase above the 2,497-line baseline (post-slice:
  2,496).
- [x] Manifest characterization test is green before and after the extraction.
- [x] Passthrough model-pin behavior remains covered and green.
- [x] Behavior stays unchanged: same error text, same ordering, same manifest shape.
- [x] Follow-up fix: removed the dead op-level `no_launch`/`ForgeOpError` branch so future CLI cleanup cannot expose an
  uncaught traceback.

## Acceptance Tests

- [x] Layering grep passed empty:
  `grep -rn "from forge.cli\|import forge.cli" src/forge/core/ops/ src/forge/session/model_pin.py`.
- [x] CLI-free helper grep passed empty:
  `grep -nE "click|rich|console|sys\.exit|print_error|print_tip" src/forge/core/ops/claude_session.py src/forge/session/model_pin.py`.
- [x] Characterization: `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py -q` -- 2
  passed.
- [x] Focused units:
  `uv run pytest tests/src/session/test_claude_session_manifest_characterization.py tests/src/session/test_direct_model.py tests/src/cli/test_session_model_pins.py tests/src/cli/test_session_commands.py tests/regression/test_bug_passthrough_model_pin.py -q`
  -- 241 passed.
- [x] Integration: `./scripts/test-integration.sh tests/integration/docker/test_session_lifecycle.py -v` -- 21 passed.
- [x] Pre-commit: `make pre-commit` -- passed.

## Roadmap

| Slice | Scope                                                                   | Crux                                                              |
| ----- | ----------------------------------------------------------------------- | ----------------------------------------------------------------- |
| 1     | system-prompt op + model-pin cluster relocation + characterization test | Low-risk pattern and harness                                      |
| 2     | `start_claude_session -> ClaudeSessionStartResult`                      | Relocate launcher/invoker seams out of CLI-safe wrappers          |
| 3     | `resume_claude_session -> ClaudeResumeResult`                           | Collapse repeated launch/resume routing/model/preference logic    |
| 4     | `validate_and_setup_supervisor` + `prepare_sidecar_session`             | Test supervisor/sidecar without CLI module                        |
| 5     | Retire the shim                                                         | Delete all 4 `_sess()` defs and the parent `session.py` re-export |

## Closeout Items

- [x] Slice 1 assertions ticked with verification recorded.
- [x] `docs/board/change_log.md` entry added for Slice 1.
- [x] `make pre-commit` clean.
- [x] Integration result recorded, including any environment limitation.
- [x] Card remains in `doing/` after Slice 1; move to `done/` only when all 5 slices land.
