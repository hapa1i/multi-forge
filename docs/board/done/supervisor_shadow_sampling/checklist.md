# Checklist: Supervisor Shadow Sampling

Branch: `supervisor_shadow_sampling` · Plan: approved (capture → Stop-batch drain → read surface, shipped as one PR).

**Current focus:** Closed out — card moved to `done/`. Slices 1 + 2 + 3 shipped + verified (capture / Stop-batch
drain / read surface); durable lessons promoted to `impl_notes.md`.

Decisions locked during planning (corrections to the card):

- Shadow records live in `.forge/artifacts/<session>/shadow/`, NOT `confirmed.policy.decisions[]` (the 100-cap ring).
- Cap enforced at capture time; candidate identity is content-addressed; cap/dedup count **all** lifecycle states.
- Disagreement reuses the supervisor's own block bar (`confidence >= 0.8` + citations).
- Queue-vs-batch: **Stop-batch** (memory-writer pattern).
- Range validation lives on the shared intent path (`SupervisorConfig.__post_init__`), not the CLI surface.
- Single ledger emitter: `invoke_supervisor` (parameterized `usage_command`); the worker never re-emits.
- Frozen candidate stores **raw** replay inputs + a copied plan + routing snapshot (the frontier builds its own prompt).

---

## Slice 1 — Capture (inert)

- [x] **Config**: add `shadow_sample_rate: float = 0.0`, `shadow_max_per_session: int = 10`,
  `shadow_seed: str | None = None` to `SupervisorConfig` (`session/models.py:138`). Old manifests read fine (additive +
  defaulted).
- [x] **Validation**: `SupervisorConfig.__post_init__` rejects `rate ∉ [0,1]` / `max < 1` with a clear `ValueError`
  (auto-wrapped to `InvalidOverrideValueError` on the `session set` path via `effective.py:99`). Covers set, start,
  fork/resume, manifest read.
- [x] **Artifact dir**: add `shadow_abs`/`shadow_rel` to `ArtifactPaths` + `get_artifact_paths`
  (`session/artifacts.py`). **Not** added to `ensure_dirs` (would break rate=0 inertness); created lazily in
  `capture_candidate`.
- [x] **New module** `policy/semantic/shadow.py`: `should_sample` (deterministic hash, rate 0/1 short-circuits),
  `ShadowCandidate` (raw action + frozen plan + routing snapshot + dims + `status`), `count_existing_candidates`
  (distinct `<hash>` stems across `.json`/`.processing`/`.done`, excludes `.plan.md` sidecar), `capture_candidate`
  (dedup across all states, cap, lazy mkdir, copy plan to `<hash>.plan.md`, write `<hash>.json` pending).
- [x] **Seam** (`plan_check.py:534`, fresh-allow branch only): gated on `shadow_sample_rate > 0.0`; best-effort
  try/except; passes `route.model`/`route.provider`/`budget_tokens`/`CHECKER_PROMPT_VERSION` + `verdict.reason`. Add
  `CHECKER_PROMPT_VERSION = 1` constant.

### Slice 1 acceptance

| Test                        | Fixture                 | Assertion                                                                                         | File                                |
| --------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------- | ----------------------------------- |
| Rate=0 inert                | default                 | shadow dir not created; decision unchanged; zero capture                                          | `test_plan_check.py`                |
| Determinism                 | fixed seed              | `should_sample` stable; rate=1 always, rate=0 never                                               | `test_shadow.py`                    |
| Cap at capture              | rate=1, max=3, 5 allows | 3 candidates; cap counts `.processing`/`.done` too                                                | `test_shadow.py`                    |
| Freeze for replay           | rate=1 Edit             | raw `new_content`/`raw_diff`/`tool_args` + `<hash>.plan.md` + routing snapshot + dims; idempotent | `test_shadow.py`                    |
| Range validation            | rate=1.5 / max=-1       | `ValueError` / `InvalidOverrideValueError`                                                        | `test_shadow.py` / `test_models.py` |
| Sampled at fresh allow only | rate=1, cache hit       | no capture on cached allow                                                                        | `test_plan_check.py`                |

## Slice 2 — Drain + verdict (Stop-batch)

- [x] `run_supervisor_check` core (`usage_command` param + `SupervisorRun{decision,verdict,run_ok,parsed}`); single
  emitter; `parse_supervisor_verdict_with_status` surfaces parse status. `invoke_supervisor` is now a thin wrapper.
  Verified: 410 policy tests green (no caller regressions).
- [x] `enqueue_shadow_marker` (`core/workqueue/queue.py`, exported) + run-tree snapshot; Stop hook enqueues only when
  `has_pending_candidates` finds a pending `*.json`. Verified: `test_shadow_runner.py`, 1824 cli/workqueue green.
- [x] `_shadow_handler` in `cli/main.py` handlers dict → detached `Popen` of `forge policy shadow run`, reusing
  `_memory_writer_env` for run-tree re-root.
- [x] `shadow_runner.py` + hidden `forge policy shadow run` worker: atomic claim (`os.rename` → `.processing`),
  reconstruct full `ActionContext` + `SupervisorConfig` (plan_override_path → frozen `<hash>.plan.md`), run frontier,
  classify agree/disagree/inconclusive/error (parse-failure ≠ inconclusive), write verdict + rename `.processing` →
  `.done`. Verified: 42 drain tests.

### Slice 2 acceptance

| Test                         | Fixture                   | Assertion                                         | File                      |
| ---------------------------- | ------------------------- | ------------------------------------------------- | ------------------------- |
| Reconstruction fidelity      | frozen candidate          | rebuilt context/config → same `SUPERVISOR_PROMPT` | `test_shadow_runner.py` ✓ |
| At-most-once                 | re-spawn over same dir    | exactly one frontier call/candidate               | `test_shadow_runner.py` ✓ |
| Parse-failure ≠ inconclusive | unparseable frontier resp | classified `error`                                | `test_shadow_runner.py` ✓ |
| Single ledger row            | rate=1 drain              | one `supervisor-shadow` event; never enforced     | `test_shadow_runner.py` ✓ |

## Slice 3 — Read surface

- [x] `ShadowActivity` (`checked`/`agree`/`disagree`/`inconclusive`/`error`/`pending`) in
  `build_session_activity_summary` from the shadow dir (`.done` status; `since` windows on `captured_at`); spend is the
  separate `supervisor-shadow` ledger row already aggregated into `commands`. Verified: `test_usage_summary.py` (+9
  tests).
- [x] `forge activity` renders the Shadow (audit) line; `render_summary_line` adds an `audited`/`queued` segment.
  Verified: `test_activity.py` (+2), `test_usage_summary.py` render tests.
- [x] `forge policy shadow` group: hidden `run` (the detached worker) + visible `show [session] [--all] [--json]`
  listing disagreement artifacts with frontier verdict + citations (`read_done_records`). Verified:
  `test_policy_shadow.py` (6 tests).

### Slice 3 acceptance

| Test               | Fixture                  | Assertion                                               | File                      |
| ------------------ | ------------------------ | ------------------------------------------------------- | ------------------------- |
| Status breakdown   | `.done` agree/disagree/… | `ShadowActivity` counts per status; sidecar ignored     | `test_usage_summary.py` ✓ |
| Pending counted    | `*.json` + `.processing` | `pending` reflects undrained candidates                 | `test_usage_summary.py` ✓ |
| Since window       | old vs new `captured_at` | out-of-window records dropped                           | `test_usage_summary.py` ✓ |
| Activity render    | disagree `.done`         | `Shadow (audit)` line + JSON `shadow` object            | `test_activity.py` ✓      |
| Show disagreements | disagree w/ citations    | renders verdict + evidence + citation; `--all`/`--json` | `test_policy_shadow.py` ✓ |

## Review fixes (round 1)

- [x] **Relative plan path** (`shadow.py`): resolve `plan_override_path` against `forge_root` before copy (mirrors
  `load_plan_override`); a relative path was silently skipping the plan copy → replay with no plan. Test:
  `test_shadow.py::test_relative_plan_path_resolved_against_forge_root`.
- [x] **Orphaned `.processing`** (`shadow_runner.py`): finalize deterministic post-claim failures (unreadable JSON,
  reconstruction error) as `.done` `status="error"` instead of stranding `.processing` (phantom pending + cap leak).
  Tests: `test_shadow_runner.py::TestPostClaimFailure`.
- [x] **FORGE_DEPTH leak** (`main.py`): reset `FORGE_DEPTH=0` in the detached shadow worker env so the frontier replay
  spawns (depth ≥ 2 would skip it → false errors). Test: `test_startup_queue.py` (env assertion).
- [x] **Phantom `--shadow-rate` help** (`policy.py`): point to the real enable path
  `forge session set policy.supervisor.shadow_sample_rate <0..1>`.
- [x] **CLI reference** (`cli_reference.md`): add `forge policy shadow show`.
- [x] **Card status** (`card.md`): "Proposed" → in-progress + shipped-design note (artifact dir, not decision log).
- [x] **`shadow-run` → `shadow run`** spelling in docstring + checklist.
- [x] **Renderer** (`policy.py`): for a `disagree`, render only cited (blocking) violations; keep all for `--all`
  non-disagree. Typed `dict[str, Any]`. Tests: `test_policy_shadow.py` (2 added).
- [x] **Prompt-drift test** (`test_shadow_runner.py`): drive the real `run_supervisor_check` (mocked
  `run_claude_session`) and assert the actual prompt — catches production assembly drift, not just helper-vs-helper.
- [x] **Pushed back (no change): `strict=False` raw `ValueError`.** Not a live bug — the sole `strict=False` caller
  (`direct_commands.py:1391`) already wraps it with a documented "escape hatch must work even with malformed overrides"
  fallback, and every `strict=True` caller wraps it into `InvalidOverrideValueError`. Wrapping the non-strict branch
  would defeat the `strict` parameter's purpose. Left as-is.

## Docs / closeout

- [x] `design_workflows.md` §1.2 shadow-sampling paragraph; `design_appendix.md` §A.13 `supervisor-shadow` emitter row.
- [x] `change_log.md` entry; notes additive `SupervisorConfig` schema break (old Forge can't read new manifests).
- [x] `impl_notes.md` durable lessons — promoted (capture/check split; queue reliability boundary at spawn →
  per-candidate atomic claim; count lifecycle states for cap/dedup; single ledger emitter via `usage_command`;
  parse-status flag separates `error` from `inconclusive`; re-root detached spend under the origin session).
- [x] `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat/gitleaks); full unit suite 6022 green.
- [x] Stop→queue→handler integration covered host-side (`test_artifact_hooks.py` enqueue, `test_startup_queue.py`
  detached-worker routing + env re-root). **Deferred (optional):** a real-Claude shadow E2E — the frontier replay reuses
  the already-Docker-tested `run_supervisor_check`/`run_claude_session` enforcement path, so the marginal value is low
  for a measurement-only feature that never enforces.

### Durable lessons (draft for `impl_notes.md` promotion after review)

- **Capture/check split**: the frontier supervisor builds its OWN prompt from raw inputs (`raw_diff or new_content`) and
  reloads the plan at run time, so a deferred audit must freeze the **raw** `ActionContext` + a **copied** plan
  (`<hash>.plan.md`) + a routing snapshot — never tier-1's packed text (which is local to `run_plan_check` and gone at
  the seam). Reconstruction fidelity is the test that locks this: rebuild → identical `SUPERVISOR_PROMPT`.
- **Work-queue reliability boundary is at spawn, not completion**: a handler "succeeds" the instant it `Popen`s, and the
  marker is deleted — so the queue's poison cap never sees a detached worker's outcome. Idempotency for detached work
  must be **per-item** (atomic `os.rename` claim → `.processing`), not via the marker. Because the drain re-sweeps only
  `*.json`, a deterministic post-claim failure must **finalize** to a terminal state (`.done` `status="error"`), not
  stay `.processing` — otherwise it is phantom-`pending` forever and leaks a cap slot. Only a hard crash mid-write may
  orphan.
- **A detached worker outlives its spawner's invariants — re-establish them locally**: it must not inherit the drainer's
  `FORGE_DEPTH` (a fresh top-level tree resets to 0, or the depth guard skips its frontier call → false errors), and any
  path it replays must resolve the **same** way the consumer resolves it (a relative `plan_override_path` is anchored at
  `forge_root`, not CWD — mirror `load_plan_override`, or the copy is silently skipped).
- **Count all lifecycle states for cap/dedup**: a content-addressed candidate exists as `.json`/`.processing`/`.done`;
  counting only `*.json` undercounts mid-drain and lets identical content re-capture (over-cap + double billing).
- **Single ledger emitter via `usage_command`**: `run_supervisor_check` is the sole cost/usage emitter; the shadow path
  parameterizes the label (`supervisor-shadow`) instead of re-emitting, so a run is never double-counted.
- **Parse-status flag separates `error` from `inconclusive`**: `parse_supervisor_verdict` collapses empty/unparseable →
  divergent+0.0 (a warn that looks like a real low-confidence verdict). The audit needs
  `parse_supervisor_verdict_with_status`'s `parsed` flag to classify a failed run as `error`, distinct from a genuine
  `inconclusive`.
- **Re-root detached-worker spend under the origin session**: snapshot `origin_run_id`/`origin_root_run_id` into the
  marker at enqueue (Stop hook runs in the session env) and re-root via `_memory_writer_env` at drain; otherwise spend
  attributes to whoever drained the queue. Scrub `FORGE_SESSION` (don't re-inject) to avoid a self-spawning hook loop.
