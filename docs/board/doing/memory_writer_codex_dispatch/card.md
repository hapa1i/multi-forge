# T6c -- Memory-writer codex dispatch (the epic's first write-capable aux lane)

**Epic**: `docs/board/doing/epic_consumer_lanes/` (member T6c). Promoted from the inline T6b sketch on 2026-06-30;
branch `memory_writer_codex_dispatch`.

**Depends on**: T6a (`done/aux_consumer_lane_placement/`) -- lane binding + freeze + billing for the memory writer
already ship. T6b (`done/aux_consumer_codex_dispatch/`) -- the runtime-keyed codex dispatch seam and the
`_dispatch_codex_shadow_curation` template. **T6c adds the one aux consumer T6b deliberately deferred: the memory
writer, whose default mode WRITES files.**

**Proves** (epic row): a non-claude runtime for *write-capable* aux work -- extends the T4/T6b read-only codex arm to
the first consumer that mutates the user's repo, forcing the workspace-write trust decision the epic sequenced last.

---

## Why T6b deferred this (verified 2026-06-30, code-grounded)

The T6b card labeled the memory writer a "different shape -- file-editing, workspace-write, Claude-specific
permission-deny stdout scan." A direct read of `session/memory_writer.py` confirms the label is **well-founded, not
conservative**:

| Fact                                                 | Evidence                                                                                                                                                                                                            | Consequence for a codex arm                                                                                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`augment` mode = the agent writes files**          | `MULTI_DOC_AUGMENT_INSTRUCTION = "Apply the specified updates to each file"` (`:115`); prompt "Read each file BEFORE modifying it" (`:106`). Forge does NOT parse+apply -- the agent uses its own Write/Edit tools. | codex arm needs `sandbox="workspace-write"` (vs the template's `read-only`) -- **the first write-granting lane in the epic**.                                                |
| **`augment` is the default mode**                    | `MemoryWriterConfig.mode: str = "augment"` (`models.py:106`). review-only is opt-in.                                                                                                                                | the *primary* memory-writer job is workspace-write; a read-only-only codex arm skips it.                                                                                     |
| **Write-success detection is Claude-specific**       | `_stdout_indicates_permission_denied` (`:281`) regex-scans Claude prose ("cannot write files") to catch an exit-0-but-couldn't-write run (`:593`); the hint names `forge claude preset edit`.                       | the scan does not transfer -- codex either has workspace-write or errors in-stream; augment needs codex-native verification (fold `runtime_is_error`, drop the Claude scan). |
| **`review-only` mode = clean mirror-T4**             | `MULTI_DOC_REVIEW_INSTRUCTION = "...Do NOT modify any files"` (`:116`); no permission scan (`:590-593`); `_persist_review_report` saves stdout (`:578`).                                                            | a near-verbatim `_dispatch_codex_shadow_curation` copy (read-only, persist stdout). Cheap.                                                                                   |
| **Prompt is transcript-file-fed, not blind-inlined** | prompt "Read the session transcript at `{transcript_path}`" (`:102`) -- an absolute `.forge/artifacts/.../transcript.jsonl` under forge_root.                                                                       | unlike shadow-curation's inlined content, the codex arm must let codex READ that file (fine under `cwd=forge_root`, but not "blind").                                        |

**So the deferral holds: T6c is not a free mirror.** Its default mode (augment) is exactly the workspace-write trust
escalation every prior lane (T4, T6b) sidestepped by staying read-only. review-only is a clean mirror but is the
*opt-in* mode, so a review-only-only T6c proves the seam without delivering the quota-offload win for the memory
writer's real work.

## What T6c adds (vs what already exists after T6a/T6b)

| Layer                                               | State after T6a/T6b                      | T6c                                                                                          |
| --------------------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------- |
| Consumer `allowed_lanes`                            | claude-max only (`memory_writer.py:58`)  | **add** `Lane(codex, chatgpt, gpt-5-codex)`                                                  |
| Runtime-keyed dispatch seam                         | shipped for supervisor + shadow-curation | **reuse the pattern** -- add the branch at `run_memory_writer` (`:530`) before `on_dispatch` |
| `_dispatch_codex_memory_writer` arm                 | absent                                   | **add** -- mirror `_dispatch_codex_shadow_curation`, `sandbox` per mode                      |
| Lane validation / freeze / billing / single-emitter | shipped (T6a/T6b)                        | reused unchanged (freeze past skip-return; invoker auto-emit; pinned Attribution)            |
| **Workspace-write sandbox (augment)**               | never granted (all lanes read-only)      | **new decision -- D1**                                                                       |
| **augment write-verification**                      | Claude stdout permission-scan            | **replace** with codex-native (`runtime_is_error` fold)                                      |

## Scope decision (D1 -- RESOLVED: Option A, both modes)

**Do we accept Codex `workspace-write` on the memory writer (augment mode)?** This is the epic's first write-granting
lane -- Codex editing the user's repo / memory docs, relaxing the read-only scope guard T4/T6b held.

- **Option A -- both modes (recommended).** augment -> `sandbox="workspace-write"`, review-only -> `read-only`; both
  share the runtime seam (the only per-mode delta is the sandbox param + augment's verification). Delivers the recurring
  quota-offload win (augment is the default). Requires accepting Codex repo-write.
- **Option B -- review-only only (defer the trust decision).** Ship the clean mirror; augment stays claude-only. Proves
  the seam extends to a 3rd consumer, zero trust change -- but skips the default mode, a partial win.
- **RESOLVED: Option A** (user, 2026-06-30) -- ship both modes. augment accepts Codex `workspace-write` on the repo's
  memory docs; this is the epic's first write-granting lane, so record the trust posture in the epic card + design docs
  (Phase 3). review-only stays `read-only`.

## Per-consumer degrade contract (memory writer = best-effort async)

Unlike shadow-curation (user-invoked -> fail-loud exit 1) and the supervisor (policy-hook -> fail-open allow), the
memory writer runs **detached from the work-queue** (stdout/stderr -> DEVNULL; `memory_writer.py:576`). The existing
claude path degrades with **log + `_record_memory_writer_outcome(status="error", ...)` + `return False`** (`:556-572`).
**Codex accounting (avoid a double upstream row -- see checklist Finding 1):** the invoker's `_emit_codex` already
writes the upstream outcome row (success + error) when `Attribution.operation` is set, so the codex arm calls
`_record_memory_writer_outcome` **only** for no-spawn setup/preflight failures; spawned runs rely on the invoker row.
Not fail-loud, not fail-open -- no user watches a terminal.

## Verified seams

- **Template to mirror**: `_dispatch_codex_shadow_curation` (`session/shadow_curation.py:445-524`) -- preflight gate ->
  `prepare_codex_request(sandbox=..., model=None, cwd=forge_root, attribution=Attribution(command="memory-writer", session=..., operation="memory_writer.run"))`
  -> `CodexHeadlessInvoker().run` -> fold `runtime_is_error`. Lane-validation guard: `shadow_curation.py:327-347`
  (`LaneRecord -> Lane -> resolve_lane`, keyword args).
- **Memory-writer touchpoints**: consumer `:54`; dispatch `:530-543`; claude emit `:546` (codex arm must skip --
  double-count); degrade `:556-572`; permission-scan `:281,593` (Claude-only -- do NOT port); on_dispatch freeze `:530`;
  upstream outcome `:68-90`.
- **Codex lane tuple**: `Lane(runtime_id="codex", backend_id="chatgpt", model="gpt-5-codex")`, model nominal (D2 parity
  with T6b).

## Decisions (all resolved)

- **D1 -- Workspace-write trust. RESOLVED: Option A** (user, 2026-06-30) -- both modes; augment uses
  `sandbox="workspace-write"`, review-only `read-only`. See Scope.
- **D2 -- Codex lane tuple. RESOLVED:** `Lane(codex, chatgpt, gpt-5-codex)` shipped, model nominal (T6b parity).
- **D3 -- Degrade. RESOLVED:** best-effort async -> `return False` + telemetry (never raises, never fails-open).
- **D4 -- augment verification. RESOLVED (Phase 0 refined the premise):** drop the Claude
  `_stdout_indicates_permission_denied` scan; fold `runtime_is_error` for provider/turn failures. The Phase 0 probe
  **falsified** the original premise -- a codex workspace-write *denial* does NOT surface as a runtime error (it exits 0
  with `is_error=False`, riding `turn.completed`) -- but it is immaterial: in-project doc writes (`cwd=forge_root`)
  auto-approve and never hit the rejection path.
- **D5 -- transcript read. RESOLVED:** Phase 0 confirmed codex reads the transcript under `cwd=forge_root` in the
  sandbox; the augment E2E reads the artifact transcript live.

## Acceptance (definition of done -- fixture-grounded)

| Test                               | Fixture                                                 | Assertion                                                                                                                           | Test File                                       |
| ---------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| codex lane selectable              | `MEMORY_WRITER_CONSUMER` + codex allowed_lane           | `valid_lanes` includes codex (claude-max preserved); `lane set --consumer memory_writer --runtime codex` resolves (was `LaneError`) | `test_memory_writer.py`, `test_session_lane.py` |
| review-only codex arm              | fresh preflight, `runtime_id=codex`, `mode=review-only` | `CodexHeadlessInvoker.run` called (`sandbox=read-only`); report persisted from stdout; no `run_claude_session`; no claude emit      | `test_memory_writer.py`                         |
| augment codex arm (if D1=A)        | fresh preflight, `mode=augment`                         | dispatched with `sandbox=workspace-write`; success -> `return True`; Claude permission-scan NOT applied                             | `test_memory_writer.py`                         |
| claude path unchanged              | default runtime                                         | claude arm byte-identical; codex preflight never read                                                                               | `test_memory_writer.py`                         |
| cold preflight degrades (not loud) | `read_fresh_codex_preflight` -> None                    | `return False` + `_record_memory_writer_outcome(error)`; NO claude fallback; skip-return -> NO freeze                               | `test_memory_writer.py`                         |
| single emitter                     | codex success                                           | `emit_usage_for_session_result` not called; invoker auto-emits; `Attribution.operation="memory_writer.run"`                         | `test_memory_writer.py`                         |
| freeze parity                      | spy `on_dispatch`                                       | success + failed-turn freeze; cold-preflight skip never freezes                                                                     | `test_memory_writer.py`                         |
| billing honesty                    | codex + chatgpt                                         | one `runtime=codex`/`billing_mode=subscription_quota` event                                                                         | real-codex E2E smoke                            |
| no double outcome row              | spawned codex failure                                   | exactly one upstream row (the invoker's); `_record_memory_writer_outcome` NOT called on the spawned path                            | `test_memory_writer.py`                         |
| codex works without claude         | `is_claude_available()`=False, runtime=codex            | codex arm dispatches; a claude/default binding still returns `claude_unavailable`                                                   | `test_memory_writer.py`                         |

## Non-goals

- **Not the supervised-Codex-executor** (no Codex hooks / policy enforcement) -- headless only, epic scope guard.
- **Not team-supervisor** (still deferred -- plan-snapshot context machinery).
- **Not fan-out workers / taggers** (epic "different shapes, later").
- **Not mid-session failover** (T7 owns the supervisor exhaustion case; the memory writer is one-shot per Stop).

## Depends on / relates to

- T6a (done), T6b (done) -- the binding + the codex dispatch seam + the template.
- T4 (done) -- the original supervisor codex arm.
- **If D1=A**, T6c is the epic's first lane to relax the read-only scope guard; record the trust posture in the epic
  card + design docs (design.md scope note, design_appendix §G).
