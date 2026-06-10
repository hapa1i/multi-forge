# Runtime Abstraction Checklist

Manual multi-session plan for executing [`card.md`](./card.md).

This card is in active execution under `doing/`. Move the whole `runtime_abstraction/` directory to `docs/board/done/`
after closeout.

## Maintenance

- Update this file during implementation sessions and once before ending a session.
- Keep tasks high-level, with concrete assertions that prove completion.
- Tick a task only when the assertion is satisfied and verification is recorded.
- Add short blocker notes inline under the relevant phase.
- Move completed-session details to `docs/board/change_log.md`; keep only active plan state here.
- Promote durable lessons to `docs/board/impl_notes.md` after human review.
- Update design docs per-phase as code ships (design docs are normative, not aspirational).
- Move the card directory to `docs/board/done/<slug>/` after the card is fully executed.
- Check size periodically while a card is active:

```bash
wc -l docs/board/doing/runtime_abstraction/checklist.md
./scripts/count-tokens.py --model <agent-model> docs/board/doing/runtime_abstraction/checklist.md
```

## Current Focus

**Phase 3 spike complete (2026-06-01) — native-relocate is VIABLE (PASS); opt-in wiring shipped (Stage C v1).** Both
gates agree on Claude Code 2.1.158: the control (resume without relocating) still reproduces the 2026-04-02 "No
conversation found" discovery failure, and the experiment (relocate the parent JSONL into the child CWD's encoded dir,
then `--resume --fork-session`) completes a signed-thinking tool-use continuation with the relocated parent unmodified.
Host repro (`scripts/experiments/native-resume/`) `[PASS]`; Docker contract test
(`tests/integration/docker/test_native_relocate_contract.py`) PASSED (23.6s). The spike also fixed a bug it surfaced:
`encode_project_path` now maps `_`→`-` (Claude 2.1.158 does, Forge didn't — broke transcript discovery for any
underscore path). `docs/design.md` §3.9 + the `session_fork.py` worktree-branch comment are version-stamped.

**Stage C v1 shipped (2026-06-01):** the opt-in `forge session fork --resume-mode native-relocate` (host mode only;
default stays transfer) relocates the parent JSONL and resumes byte-for-byte, with preflights (sidecar/`--direct`,
`--no-launch`, source-transcript), post-create rollback, and dir-scoped cleanup of the relocated copy. Deferred:
`--rewrite-paths`, sidecar native-relocate, `resume --resume-mode native-relocate`, and the (gated) default flip.

**Phase 2 complete (2026-06-01).** The optional always-on audit proxy shipped across commits `97abe5c` (OBSERVE),
`2663c06` (MUTATE), `d0eb708` (sidecar plumbing), and `5991896` (sidecar `--user` fix), plus the 2f docs slice:
`wire_shape`/`intercept`/`audit` config, the thinking-preserving `anthropic_passthrough` wire, redacted audit logs with
`forge proxy audit show|diff`, override-mode controls on the signature-safe path, and host-persistent sidecar audit.
`docs/design.md` §7.x + §3.4/§3.7/§4.0, `docs/design_appendix.md` §A.11/§A.12, and `docs/end-user/proxy.md` reflect it.
All Phase 2 slice boxes are ticked.

**Phase 1 complete (2026-05-31).** Schema-backed curated transfer, the `children/<child>.notes.md` overlay, and the
top-level `forge transfer show|regenerate|edit|diff` CLI shipped in commit `2b70c29`; `docs/design.md` §3.9 and
`docs/design_appendix.md` §M reflect it. All Phase 1 boxes are ticked.

Next: **Phase 4 (runtime-abstraction core)** -- **Slices 4a (run-tree env contract) + 4b (usage-ledger schema) + 4c
(instrument native + direct paths) + 4d (`HeadlessInvoker` + review fan-out migration + per-worker usage events) + 4e
(runtime registry capability matrix) + 4f (runtime-tagged `ActionContext` + named Claude hook adapter/responder behind
runtime-neutral protocols) shipped 2026-06-01**, and **Slice 4g (proxied per-request correlation) shipped 2026-06-08**
(Claude-Code custom-header feasibility confirmed; run-tree join, leak-gated injection, proxy-side validation, read-time
suppression) -- so all of Phase 4 is complete; the next phase is **Phase 5 (cross-runtime resume /
`CodexHeadlessInvoker`)**. The 4g feasibility canary PASSED 2026-06-08 (Claude Code 2.1.168, all 6 cases against a live
OpenRouter-backed proxy), so the external-forwarding dependency is verified, not just authored. The two cross-cutting
Phase 4 decisions are resolved (data-plane: separate planes linked by `request_id`; `FORGE_DEPTH`: additive run-tree
env, integer guard unchanged) -- see Open Decisions for the de-risked build sequence, recorded at the top of the Phase 4
section. Deferred Phase 3 follow-ups (`--rewrite-paths`, sidecar/resume native-relocate, the gated default flip) are
recorded as trackable boxes under Phase 3 and land when prioritized. The card stays in `doing/` until Phases 3-6 land
(board-contract: move to `done/` only when fully executed). A 2026-06-02 review pass hardened 4a-4d (cancellation race,
cancelled-worker emission, direct-LLM `cached_tokens`, partial-origin marker) -- see *Phase 4 hardening - review fixes*.

**Deferred prerequisite (memory_substrate reconciliation) -- RESOLVED 2026-05-30:**

- [x] Reconcile this card's "curated handoff" vocabulary with the shipped **transfer** taxonomy, and retarget the
  proposed `forge session handoff regenerate|edit|diff` surface before implementing the schema.
  - Resolution: `card.md` now uses **curated transfer** throughout (the `ai-curated` transfer strategy, repositioned as
    the primary cross-runtime substrate), with a vocabulary note in the "Curated Transfer as Cross-Runtime Substrate"
    section tying it to `docs/design.md` §3.9 (transfer) and §5.6 (memory writer). The doc-updater stays the **memory
    writer**; resume/fork context stays **transfer**.
  - Namespace: the retargeted verbs live under a new **top-level `forge transfer` group**
    (`forge transfer show|regenerate|edit|diff`), chosen over `forge session transfer` on user-mental-model grounds so
    it pairs with `forge memory`. `forge session resume --fresh --review` stays the ergonomic entry point, not a second
    namespace. See the resolved namespace task in Phase 1 and the Open Decisions.
  - Verification: `rg "handoff" card.md` returns only intentional refs (the quoted historical term in the vocabulary
    note + `forge session handoff` tombstone mentions); `rg "forge session transfer" card.md` returns nothing.

## Phase 0 - Baseline Confirmation

- [x] Confirm PR #8 cost-control and routing foundation state.
  - Verification: Phase 0 foundations map to shipped code: subprocess routing in `src/forge/core/reactive/routing.py`
    and `src/forge/review/routing.py`; proxy request cost logs/caps in `src/forge/proxy/cost_logger.py`,
    `src/forge/proxy/server.py`, and `src/forge/config/schema.py`; session subprocess proxy inheritance in
    `tests/src/session/test_subprocess_proxy_inheritance.py`.
- [x] Record Phase 0 gaps before starting Phase 1 work.
  - Verification: foundation is confirmed, with future gaps carried forward below.

Phase 0 gaps carried forward:

- Team supervisor verb-cost snapshots remain future for `src/forge/policy/team/handlers.py`; track under Phase 4 usage
  ledger callsites.
- Review engine routing plans shipped, but review fan-out is still outside the invoker abstraction; track under Phase 4
  `HeadlessInvoker` and fan-out migration.
- Session and Claude launchers have subprocess-proxy environment wiring, but the durable runtime usage ledger remains
  future; track under Phase 4 usage ledger callsites.

## Phase 1 - Curated Transfer Reframe

- [x] Reposition `ai-curated` / curated transfer in `docs/design.md` as the primary cross-runtime and cross-topology
  transfer substrate, not merely a lossy fallback.
  - Assertion: design text distinguishes native resume (byte-faithful but opaque and CWD-locked) from curated transfer
    (runtime-neutral, user-editable) by user agency and runtime portability; `structured` remains the CLI default unless
    an explicit default change is approved.
  - Scope note (assertion refined 2026-05-31): the native-*relocate* leg of the agency reframe stays in `card.md` and
    lands in `design.md` only when Phase 3 ships native-relocate. Design docs describe shipped behavior
    (documentation-guidelines Rule 2), so an unshipped Phase 3 spike must not be written as current design; the original
    assertion's "native-relocate" clause was dropped for this reason.
  - Verification (2026-05-31): `docs/design.md` §3.9 ("Curated transfer is the primary cross-boundary substrate, not a
    lossy fallback") shipped in commit `2b70c29`; `structured` confirmed still the CLI default in both the prose and
    `transfer.py`.
- [x] Verify `forge session resume --fresh --review` behavior.
  - Note: this shipped before the runtime-abstraction checklist was activated; it is retained here as verified Phase 1
    foundation.
  - Assertion: transfer-mode resume opens the per-child user-notes overlay (`children/<child>.notes.md`) in `$EDITOR`;
    native mode rejects `--review` with an actionable error.
  - Verification: `src/forge/cli/session_lifecycle.py` implements the `resume --review` option, native-mode rejection,
    and `$EDITOR` launch for the user-notes overlay; `docs/design.md` command reference documents the CLI contract;
    `tests/src/cli/test_session_resume_review.py` covers the behavior.
- [x] Decide the resume-context command namespace before adding `regenerate|edit|diff`.
  - Decision (2026-05-30): **top-level `forge transfer` group** -- `forge transfer show|regenerate|edit|diff`. Chosen
    over the `forge session transfer` subgroup on user-mental-model grounds: users think "inspect/reshape the context
    that moves forward," not "a subresource of session," and it pairs with the top-level `forge memory` as the two
    halves of the former "handoff." This is a user-facing-namespace choice, not a scoping claim -- transfer is still
    session-derived and every verb takes a parent session argument.
  - Verified free/occupied (2026-05-30): `forge transfer` is unclaimed (no CLI command; `transfer` appears only as the
    `--resume-mode` value, a `forge clean` category key, and internal `transfer.py` symbols). `forge session handoff` is
    a removed-command tombstone (redirects to `forge memory report show`) and `forge session context` is a hidden
    deprecated alias for `forge session show` -- neither reusable. `forge transfer show` (assembled transfer artifact)
    is deliberately distinct from the deprecated `forge session context` (a running session's runtime context).
  - Single canonical namespace only: `forge session resume --fresh --review` remains a delegating entry point, not a
    competing surface.
- [x] Define the Forge-owned curated transfer schema contract in docs.
  - Assertion: schema records lineage, decisions with citations, current state, open questions, runtime hints, and user
    notes overlay.
  - Verification (2026-05-31): `docs/design_appendix.md` §M documents the contract -- §M.1 child-agnostic frontmatter
    (`schema_version: 1`, `schema`, `strategy`, `lineage`, `target_runtime`), §M.2 the 8 canonical sections (Lineage,
    Goal/Current Task, Decisions cited, Current State, Relevant Files, Open Questions, Runtime Hints, User Notes), §M.3
    the three-file layout + overlay. Shipped in `2b70c29`.
- [x] Implement the curated transfer schema in `src/forge/session/transfer.py`.
  - Assertion: generated transfer markdown has stable sections for the schema fields; existing
    `minimal|structured|full|ai-curated` strategies either emit that schema or document their compatibility fallback.
  - Verification (2026-05-31): `transfer.py` `_build_ai_curated_output()` emits canonical sections 1-7 (section 8 is the
    `.notes.md` overlay merged at show/launch); `_build_frontmatter()` stamps `schema: "full"` only for a successful
    ai-curated body and `schema: "compatibility-fallback"` for `minimal|structured|full`;
    `_validate_decision_citations()` drops fabricated citations so `schema: full` stays honest. Shipped in `2b70c29`.
- [x] Add tests for schema output and artifact durability.
  - Assertion: tests cover parent cache regeneration, per-child artifact preservation, and required schema sections for
    curated output.
  - Verification (2026-05-31): 113 passed -- `tests/src/session/test_transfer.py`
    (`test_ai_curated_renders_schema_sections`, `test_compatibility_fallback_frontmatter`,
    `test_generated_and_child_are_byte_identical`, citation grounding), `tests/src/cli/test_transfer_cli.py`
    (`test_regenerate_preserves_strategy`, `test_regenerate_does_not_touch_notes`,
    `test_show_json_includes_section_map`), `tests/src/session/test_prev_sessions.py` (notes round-trip, compose,
    `iter_children` excludes notes), and regression `tests/regression/test_bug_transfer_notes_not_gc_orphaned.py`.
- [x] Define the user notes overlay convention.
  - Assertion: docs/code state where user notes live, how they compose with generated content, and that regeneration
    never overwrites authoritative user notes.
  - Verification (2026-05-31): `children/<child>.notes.md` is the editable overlay (design.md §3.9, appendix §M.3);
    `prev_sessions.py` composes notes after the frozen snapshot at launch, `ensure_child` never overwrites an existing
    child, and `forge transfer regenerate` rewrites only `generated.md`. Covered by `test_prev_sessions.py`
    (`test_snapshot_notes_round_trip`, `test_compose_merges_user_notes`, `test_compose_skips_empty_notes`). Shipped in
    `2b70c29`.
- [x] Decide how `ctx` relates to Forge transfer.
  - Assertion: docs state whether `ctx` is only prior art, an import/export peer, or a future dependency.
  - Decision (2026-05-31): `ctx` is **prior art and inspiration only -- never a dependency**. The Forge-owned transfer
    schema is canonical and no `ctx` interop is planned (an optional import/export bridge could be added later on the
    existing schema, but is not committed work). Recorded in `docs/design_appendix.md` §M.4; the matching `card.md`
    prose and Open Question are aligned and marked resolved.
- [x] Confirm Phase 1 schema is stable enough for Phase 5 target-runtime tuning.
  - Assertion: Phase 5 can tune transfer presentation for Codex without changing transcript source artifacts or schema
    semantics.
  - Verification (2026-05-31): the schema reserves `target_runtime` (frontmatter + `TRANSFER_TARGET_RUNTIME`, appendix
    §M.1) and code owns the section skeleton, so Phase 5 retargets presentation without touching transcript artifacts or
    schema semantics. Closeout gates cleared -- the `ctx` posture is recorded (§M.4) and both default-behavior Open
    Decisions are resolved (keep `--review` opt-in, keep `structured` default). All Phase 1 boxes are now ticked; the
    card stays in `doing/` for Phases 2-6.

## Phase 2 - Optional Audit Proxy (compacted 2026-06-09; shipped 2026-05-31 -> 2026-06-01)

Compacted per the board-contract size policy when Phase 6 planning pushed this file over the 30k-token hook. Full slice
detail (acceptance tables, review-fix lists) lives in git history and the change_log 2026-06-01 "Phase 2: optional audit
proxy" entry; `design.md` §7.x and `design_appendix.md` §A.11/§A.12 are normative for shipped behavior. Sliced
OBSERVE-before-MUTATE; two axes kept distinct everywhere: **wire shape** (`openai_translated` | `anthropic_passthrough`)
and **intercept mode** (`passthrough` | `inspect` | `override`).

- [x] 2a config schema + loader propagation + `wire_shape` (strict unknown-key rejection; defaults inert).
- [x] 2b anthropic-passthrough forward path + template (raw body forwarded byte-identical; thinking blocks preserved).
- [x] 2c audit logging + redaction + drift + `forge proxy audit show` + preflight (OBSERVE) + 10 review fixes (the
  middleware is the SOLE passthrough entry point; caps/cost wired; no-leak regression through the server path).
- [x] 2d override mode: cache-aware augment + guards + reasoning pin + mutation-safety fingerprint + `audit diff`
  (MUTATE) + 14 review fixes (override REQUIRES `anthropic_passthrough`; guards validated at config load;
  all-blocks-before-any-strip).
- [x] 2e sidecar audit plumbing + hardening (host-persistent audit/costs mounts; Linux `--user`/`HOME=/root` fix; two
  latent entrypoint bugs fixed; sidecar image wired into the canonical test runner).
- [x] 2f docs + always-on posture + closeout.

Carried-forward debt (unchanged): (a) real-upstream `@slow` passthrough signature-replay e2e (release-validation tier);
(b) streamed full-body capture stays request-body + response-metadata only; (c) optional shared helper for the sidecar
`docker run` argv so `tests/integration/sidecar/test_audit_plumbing.py` and `run_sidecar_session` cannot drift.

## Phase 3 - Native-Relocate Spike

**Spike outcome (2026-06-01): PASS on Claude Code 2.1.158 — native-relocate is viable.** The relocate primitive, host
reproduction, and Docker contract test shipped; the opt-in `--resume-mode native-relocate` CLI wiring (the per-code-path
split + derivation/GC provenance) is the deferred **Stage C** follow-up (touch points recorded in the execution plan).

- [x] Spike cross-CWD Claude JSONL relocation.
  - Assertion: integration contract test proves Claude Code can resume relocated JSONL across CWD boundary without
    signature-validation failure, while explicitly acknowledging the prior Claude Code 2.1.90 negative result documented
    in `docs/design.md` §3.9.
  - Verification (2026-06-01): `tests/integration/docker/test_native_relocate_contract.py` PASSED (23.6s) — signed
    parent thinking block exercised, child resume exit 0, ≥2 tool_use in the fork, relocated parent sha256 unchanged.
    Host repro `[PASS]`. The control still reproduces the "No conversation found" discovery failure (now confirmed on
    2.1.158 too); design.md §3.9 acknowledges it.
- [x] Tie the spike to the current no-op and transfer-only guards.
  - Assertion: checklist/test references cover the native-resume guard in `src/forge/session/manager.py` and the
    worktree-fork transfer branch in `src/forge/cli/session_fork.py`.
  - Verification: the `session_fork.py` worktree-branch comment (the transfer-only guard) is version-stamped with the
    spike result; the cross-`forge_root` native-resume no-op guard at `manager.py:700-703` is recorded as the Stage C
    wiring point (deferred, untouched here).
- [x] Gate path rewriting separately.
  - Assertion: absolute path rewriting is opt-in and disabled by default until tests prove it harmless.
  - Verification: `relocate_transcript(rewrite_paths=...)` is a reserved seam — `True` raises `NotImplementedError`
    (default off); content-untouched copy is the signature-safe minimum. Locked by
    `test_claude_relocate.py::TestRelocateTranscript::test_rewrite_paths_not_implemented`.
- [x] Decide outcome of native-relocate.
  - Assertion: either introduce opt-in `--resume-mode native-relocate` or record why curated transfer remains the only
    cross-CWD path.
  - Decision (2026-06-01): native-relocate is **viable** (PASS); the opt-in `--resume-mode native-relocate` wiring
    shipped as **Stage C v1** (fork, host mode only), and transfer remains the default for worktree forks. Deferred:
    `resume --resume-mode native-relocate`, sidecar, path rewriting, the default flip. Recorded in design.md §3.9.
- [x] Split native-relocate handling by code path. *(Stage C v1 — shipped for fork)*
  - Assertion: `fork --worktree` and `fork --into` resume natively via relocation;
    `resume --resume-mode native-relocate` has an explicit deferred status.
  - Verification (2026-06-01): `fork --resume-mode native-relocate` (a `click.Choice(["transfer", "native-relocate"])`
    on `forge session fork`, `default=None`) relocates the parent JSONL into the child's encoded dir and launches
    `--resume --fork-session` from the worktree CWD (`src/forge/cli/session_fork.py`). Host mode only (sidecar rejected,
    `--direct`-aware), `--no-launch` rejected, source-transcript preflighted before create, post-create relocate failure
    rolls back the fork (`delete_session`, owns_worktree-aware). `resume --resume-mode native-relocate` is **deferred**
    (the shared resume validator stays `{native, transfer}`). Covered by
    `tests/src/cli/test_session_commands.py::TestSessionFork` (10 cases: routing, notice, same-dir/strategy tips,
    sidecar/no-launch/source rejects, `--direct` allowed, conflict rollback).
- [x] Preserve derivation and GC invariants for relocated artifacts. *(Stage C v1 — shipped)*
  - Assertion: the relocated JSONL is traceable and cleaned up without orphaning or touching the parent's original.
  - Verification (2026-06-01): `Derivation.resume_mode="native-relocate"` + `relocated_parent_session_id` (the parent
    UUID) record the relocation (`models.py`, `manager.fork_session`); `delete_session` unlinks
    `get_transcript_path(child_root, parent_uuid)` in a branch gated only on the derivation (independent of the child
    UUID, so failed/partial launches still clean up) — dir-scoped to the child, never the parent's original. Covered by
    `test_fork_into.py::TestForkNativeRelocate` (derivation, same-dir fallback, cleanup-without-child-UUID).

#### Phase 3 hardening - review fixes (DONE 2026-06-01; compacted 2026-06-09)

10 review issues (5 Medium / 5 Low) verified and fixed; both gates re-run green after the changes (host repro `[PASS]`,
Docker contract test 23.0s). Durable kernels preserved: the contract test uses an underscore-bearing child root so the
`encode_project_path` `_`->`-` branch is exercised end-to-end against real Claude; both gates emit `[INCONCLUSIVE]`
(never `[PASS]`) when no signed thinking block was present -- a clean resume with nothing to revalidate is not evidence
for signature survival; only `/` `.` `_` are characterized against real Claude -- do not broaden the encoding rule
without a characterization test. Full per-issue detail in git history.

### Phase 3 - Deferred follow-ups (parked; land when prioritized)

Recorded so they are not lost while Phase 4 proceeds. None block Phase 4. Verified still deferred against code at commit
`21688d6` (2026-06-01).

- [ ] `--rewrite-paths`: rewrite absolute paths inside relocated `tool_result` blocks (historical paths point at the
  parent checkout). Seam reserved; `relocate_transcript(rewrite_paths=True)` raises `NotImplementedError`
  (`session/claude/relocate.py:93`). **Gated**: needs a contract test proving the rewrite cannot invalidate a thinking
  signature (it touches signed historical content). **Blocks the default-flip below.**
- [ ] `resume --resume-mode native-relocate`: extend native-relocate from `fork` to `resume --fresh`. Validator
  currently accepts only `{native, transfer}` (`cli/session_lifecycle.py:346`); only `fork` has the choice. Lowest-risk
  item (relocate primitive + derivation/GC plumbing already exist); same stale-path caveat as `--rewrite-paths`.
- [ ] Sidecar native-relocate: currently rejected at preflight (`cli/session_fork.py:386`) because relocation writes to
  the host `~/.claude` store, which the sidecar does not mount. Needs a decision on mounting part of host `~/.claude`
  into the sidecar (UID/port-isolation tradeoffs per design.md §7). `--direct`/`--no-proxy` already escape to host mode.
- [ ] Gated default-flip: make native-relocate the default for cross-CWD forks. Two gates: (a) stale-path mitigation
  proven (`--rewrite-paths`), AND (b) a compaction/fallback story defined (relocated history is lost on `/compact`, same
  as native resume). Order: `--worktree` flips before `--into` (more collision surface on an existing `--into`
  worktree). Wiring point: the cross-`forge_root` native-resume no-op guard at `session/manager.py:700-703`.

## Phase 4 - Runtime Abstraction Core

**Cross-cutting decisions resolved (2026-06-01, see Open Decisions):** data-plane (three separate planes linked by
`request_id`) and `FORGE_DEPTH` vs run-tree (additive, orthogonal). **De-risked build sequence:** (1) run-tree env
contract in `build_claude_env` (additive, touches no durable schema); (2) define `usage/events/<month>_<pid>.jsonl`
schema with nullable `source_refs`; (3) instrument native + direct `core.llm` paths first (linkage exact or moot); (4)
proxied per-request correlation fork last. The `HeadlessInvoker` refactor is the largest *implementation* risk but is
internal/refactorable -- it does not mint a durable contract, so it does not gate the schema work.

### Slices 4a-4f (DONE 2026-06-01; hardened 2026-06-02; compacted 2026-06-09)

Compacted per the board-contract size policy. Full slice detail (assertions, verification bodies, review-fix lists)
lives in git history and the change_log 2026-06-01 "runtime_abstraction Phase 4 (Slices 4a-4f)" + 2026-06-02 hardening
entries; `design.md` §3.14/§4.1.4/§4.1.5/§5.5.5 and `design_appendix.md` §A.13/§C.1/§F.5 are normative.

- [x] 4a run-tree env contract: `(FORGE_RUN_ID, FORGE_PARENT_RUN_ID, FORGE_ROOT_RUN_ID)` stamped at the single env choke
  point, orthogonal to `FORGE_DEPTH` (its three recursion guards unchanged); interactive launches mint a fresh root in
  `invoke._build_environment`; the queue-decoupled memory writer re-roots under its originating session's snapshotted
  origin identity.

- [x] 4d `HeadlessInvoker` + `ClaudeHeadlessInvoker` (`core/invoker/`): the seam is the **lifecycle, not the routing**
  (requests arrive already-routed); review fan-out moved verbatim behind `run_parallel` (process groups, `os.killpg`
  SIGTERM->SIGKILL, deterministic ordering, SIGTERM-before-executor-join); the 4 single-shot callers keep
  `run_claude_session`. Per-worker usage events emit here (worker granularity, cost null -- the verb aggregate holds the
  estimate; events record the actual routed model/provider/proxy_id).

- [x] 4e runtime registry (`core/runtime/`): frozen `RuntimeSpec` per runtime in a module-level `RUNTIMES` table;
  tri-state capability literals declare Codex/Gemini limits as values, never parity-implying omissions
  (`pretool_policy="partial"`, `native_hooks="gated"` + machine-readable version gate); `forge runtime list [--json]`.

- [x] 4f runtime-tagged `ActionContext` (required `runtime: str`; `PolicyEngine.evaluate` never branches on it --
  attribution metadata, not control flow) + the Claude adapter/responder named behind runtime-neutral
  `HookAdapter`/`HookResponder` protocols (`src/forge/cli/hooks/protocols.py`); output bytes + exit codes unchanged (77
  hook-command snapshot tests untouched); a `CodexHookAdapter`/`CodexHookResponder` is the stub the protocols make room
  for. Integration: `test_policy_hooks.py` 10/10 through the real wheel CLI.

- [x] 4b durable usage ledger (`~/.forge/usage/events/<month>_<pid>.jsonl`): versioned `UsageEvent`
  (`schema_version=1`), strict typed reads (unknown field == corruption), PID-sharded, best-effort 0600 writer; modeled
  on `audit_logger.py`.

- [x] 4c instrumented emitters: the 4 workflow verbs, memory writer, semantic supervisor, shadow curation, action tagger
  (exact provider tokens; `X-Request-ID` join when the target is a registered Forge proxy); deferred-by-design:
  interactive launchers (own concern), native Codex/Gemini (landed Phase 5).

- [x] Phase 4 hardening (2026-06-02): 4d spawn/register cancellation race fixed (lock-guarded `cleanup_started`; every
  child reaped by exactly one of cleanup/worker); cancelled workers emit no usage (typed `HeadlessResult.cancelled`);
  direct-LLM `cached_tokens` copied; the both-or-neither origin-marker contract pinned with a test.

### Slice 4g - Proxied per-request correlation (exact `claude -p` cost) (2026-06-08)

Resolves the last Phase 4 open decision (above). Replaces the concurrency-fragile before/after proxy snapshot delta for
proxied `claude -p` cost with an **exact** run-tree join: Forge stamps its own headless subprocess's outbound requests
with validated run ids (via `ANTHROPIC_CUSTOM_HEADERS`), the proxy records them on each cost record, and the read
surface sums by `forge_root_run_id`. ToS-clean (Forge's own subprocesses through Forge's own proxy, opaque non-secret
ids; no credential extraction; interactive OAuth session untouched). The deferred OAuth-MITM tier is unrelated.

- [x] **4g.1 - Proxy stamp + validate (write side).** Middleware reads `X-Forge-Run-ID`/`X-Forge-Root-Run-ID`, validates
  each (`is_valid_run_id`, `^run_[0-9a-f]{12}$`) and stores `None` on mismatch, threading
  `forge_run_id`/`forge_root_run_id` through `_calc_and_log_cost` -> `log_request_cost` as additive cost-record fields
  (no `COST_SCHEMA_VERSION` bump; one middleware site covers translated + passthrough wire shapes).
  - Files: `src/forge/proxy/server.py`, `src/forge/proxy/cost_logger.py`, new dependency-free `src/forge/core/run_id.py`
    (shared `RUN_ID_RE`/`is_valid_run_id`/`mint_run_id` + header constants, so the proxy imports the validator without
    dragging `core.reactive`'s eager tagger/`core.llm` imports).
  - Tests: `tests/src/proxy/test_cost_logger.py::TestForgeRunCorrelation` (fields persisted additively at
    `schema_version` 1; default `None`; root join sums by root; present-without-cost), `tests/src/core/test_run_id.py`
    (mint/validate + injection/spoof rejection). Inert until headers arrive (records carry `None`).
- [x] **4g.2 - Env injection (gated, Forge-owned).** `build_claude_env` stamps the two headers only when
  `derive_run_identity` (a headless child -- excludes the interactive harness, preserving the `forge +$Y` boundary)
  **AND** the target is a **proven Forge proxy** (`target_is_forge_proxy(base_url)` OR `FORGE_SUBPROCESS_PROXY_ID`
  present **AND** `base_url == FORGE_SUBPROCESS_BASE_URL`). The URL-match defeats an inherited marker paired with an
  explicit opaque `base_url` override. Headers are Forge-owned: strip inherited `X-Forge-*` lines, re-stamp the child's
  ids, preserve user lines.
  - Files: `src/forge/core/reactive/env.py` (`_apply_correlation_headers`, `_target_is_proven_forge_proxy`).
  - Tests: `tests/src/core/reactive/test_env.py::TestCorrelationHeaders` (proven proxy -> stamped; opaque base_url -> no
    header; inherited marker + explicit opaque base_url -> no header; interactive -> no header; user lines preserved;
    inherited `X-Forge-Run-ID` replaced not duplicated).
- [x] **4g.3 / 4g.4 - Read-time root join + suppression + fan-out/orphan.** `sum_reported_cost_by_root(roots, *, since)`
  (`cost_logger.py`) returns `has_records`/`runs_with_records` (presence, incl. dollar-less records) and
  `has_cost`/`per_run` (dollars) separately; `usage_summary._join_session_cost` sums by `forge_root_run_id` three ways:
  exact dollars -> suppress the snapshot; records-but-no-dollars -> suppress snapshot, render **unavailable** (not
  `$0`); no records -> event-sourced fallback (direct `runtime_native` + pre-4g).
  - **Suppression is per-run-subtree, not whole-root** (review fix 2026-06-08): a `verb_snapshot_estimated` event is
    superseded only when its OWN run produced records (`run_id in runs_with_records`) OR it is a verb whose DIRECT
    children did (`run_id in producer_parents`, derived from worker `parent_run_id`). Whole-root suppression
    (`root_run_id in roots_with_records`) silently dropped a correctly-unstamped sibling's snapshot whenever any run
    under the shared session root was stamped. Root-summing still captures orphan cancelled leaves (cost counted; a verb
    whose workers were ALL cancelled has no fan-out parentage to reconstruct, but skips its own emit too -- documented
    edge).
  - **Exact figures render without `~`** (review fix 2026-06-08): `cost_estimated` on `SessionActivitySummary`/
    `CommandUsage` (default `True`, the safe caveat for hand-built summaries) is `False` when the figure is entirely
    cost-plane-exact, so `forge activity` / the session-end line drop the estimate marker and the footnote reads "exact
    via run-tree join" -- realizing the `proxy_request_exact` read-surface label the docs claim.
  - Files: `src/forge/core/ops/usage_summary.py` (`_join_session_cost` -> `_CostJoin`, used by `sum_forge_added_cost`
    and `_aggregate_ledger`), `src/forge/cli/activity.py` (per-command + total `~` gating, footnote).
  - Tests: `tests/src/core/ops/test_usage_summary.py::TestRootJoin4g` (exact supersedes snapshot; fan-out no
    double-count; no-cost route unavailable-not-zero; mixed exact+no-cost partial; orphan cancelled leaf via root;
    interactive isolated; direct `runtime_native` kept; pre-4g snapshot; exact-not-estimated +
    exact+snapshot-estimated); `test_cost_logger.py` (`runs_with_records` presence); `test_activity.py` (exact renders
    without `~`); regression `tests/regression/test_bug_4g_mixed_stamped_unstamped_undercount.py` (shared-root
    undercount guard).
- [x] **4g.5 - Docs + board sync.** design.md §3.14 (run-tree join sentence), design_appendix.md §A.9 (cost-record
  schema gains `forge_run_id`/`forge_root_run_id`, additive at `schema_version` 1) + §A.13 (`proxy_request_exact` as a
  read-time provenance label; `source_refs` stays null by design), this Open Decision resolution, and this slice block.
- [x] **4g.0 - Feasibility canary (GATING) -- PASSED 2026-06-08 on Claude Code 2.1.168.**
  `tests/integration/proxy/test_forge_run_id_correlation.py`: all 6 cases green against a live OpenRouter-backed Forge
  proxy (28.6s). A live Forge proxy validates + stamps valid headers, drops malformed ones, and -- the load-bearing
  external dependency -- a real `claude` forwards `ANTHROPIC_CUSTOM_HEADERS` so the proxy stamps the run ids. Covers
  plain `claude -p`, `claude -p --bare` (env vars survive `--bare`; settings.json does not), and a multi-request tool
  loop that confirmed **every** cost record in the window is stamped (the tool loop did force >= 2 requests; a harness
  that set the header only on the first request would fail here). The validated Claude Code version is captured +
  reported (`CLAUDE_VERSION_VALIDATED = "2.1.168"`); the standing version-regression guard against a future Claude Code
  that drops/renames the env var. **Requires** an OpenRouter key + the `claude` binary on PATH (no Docker LiteLLM -- the
  `openrouter-anthropic` template routes directly); re-run with
  `uv run pytest tests/integration/proxy/test_forge_run_id_correlation.py -v`.

## Phase 5 - Cross-Runtime Resume

**Status (2026-06-09): Phase 5 complete — all slices shipped (5.0, 5a, 5b, 5c, 5d, 5e, 5f).** Two adversarially-verified
research sweeps re-pinned the external tools and corrected stale card assumptions before scoping (verdict below).
**Decided:** one-shot `codex exec` transport (the app-server transport is a deferred follow-up, tracked under 5b). The
cross-runtime hop is **curated transfer** (reasoning signatures are non-portable -- confirmed); Codex-side continuation
after the hop can use `codex exec resume`. Goal: run Codex as a first-class headless runtime and demonstrate "plan in
Claude -> implement in Codex" with correct auth preflight and usage attribution. Depends on shipped Phase 4 seams
(`HeadlessInvoker`/`run_parallel` 4d, runtime registry 4e, usage ledger + reserved
`codex_exec`/`codex_jsonl`/`runtime_native` literals 4b/4c, run-tree env 4a/4g) and the Phase 1 transfer schema
(`target_runtime` reserved).

### Research verdict (verified 2026-06-08; every claim re-fetched from official docs/changelogs)

**Version drift:** Codex CLI **0.124.0 (card pin) -> 0.137.0 stable** (~13 minors; 0.138.0-alpha exists) -- re-pinned.
Claude Code **2.1.168 = at head** (no CLI drift; model layer moved). Gemini CLI 0.45.2, **folding into "Antigravity CLI"
on 2026-06-18** -> out of Phase 5 scope; defer the GeminiHeadlessInvoker and target paid/Vertex auth.

**Codex corrections (applied to card.md + registry in Slice 5.0):**

- Hooks are **default-on** (`[features] hooks`); `codex_hooks` is a **deprecated alias** of `hooks` (still works -- do
  not author new config with it; 0.134.0 removed the plugin-hooks *gate*, not the alias). \[codex/hooks +
  config-reference\]
- Lifecycle is **10 events** (was 5): +`SessionStart`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact`.
- **`SessionStart` additionalContext** is the native injection seam but **conditional** -- it fires only when hooks are
  enabled AND the hook is trusted (trust keyed to the hook hash; untrusted/first-run projects skip project-local
  `.codex/` hooks; managed hooks are review-exempt). So 5d keeps an **initial-message fallback** and 5a checks hook
  state, or the curated context silently vanishes.
- `PreToolUse` can **mutate** tool input (`permissionDecision:"allow"` + `updatedInput`); `PermissionRequest` is the
  approval seam; PreToolUse stays a **partial** guard (registry `pretool_policy="partial"` kept).
- First-party **non-interactive auth** exists: `CODEX_API_KEY`, `codex login --device-auth`, enterprise tokens;
  `codex doctor` is a preflight primitive. Prefer over the LiteLLM `chatgpt/` route (undocumented by OpenAI, header
  spoofing, volatile model roster) -> gated last resort.
- A proxy fronting Codex must serve **Responses on its Codex-facing endpoint** -- Codex emits `wire_api="responses"`
  only (custom-provider `wire_api="chat"` removed ~Feb 2026 per `config-reference`; the `codex/models` prose is stale).
  The **backend** may speak Chat Completions and be translated (LiteLLM), so block only on the Codex-facing surface,
  never the backend wire. [config-reference + discussion #7782]
- Enterprise `allow_managed_hooks_only=true` (`requirements.toml`) silently suppresses user/project hooks.
- JSONL usage schema: `item.completed`->`{type: agent_message}`; `turn.completed.usage` carries
  `input/cached_input/output/reasoning_output_tokens` (reasoning added 0.125.0).
- Interactive Codex is GA in the Codex CLI (C10 "superseded"); a headless **app-server** (`codex remote-control`,
  `codex app-server` -- default stdio / `--listen stdio://` / `--stdio`) now exists -> Phase 6 re-scope (in card.md).

**Claude Code (Forge already owns this side) -- all headless mechanics confirmed on 2.1.168:**
`ANTHROPIC_CUSTOM_HEADERS` (doc-implied forwarding; **Forge-validated by the 4g canary** on 2.1.168 -- keep that canary
as the standing regression guard), `--output-format json` (`total_cost_usd` + per-model `modelUsage`),
`--resume`/`--fork-session`/`--session-id`/`--bare`/`--append-system-prompt-file`, parallel-tool floor `>= 2.1.80`,
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`. New + relevant: `claude setup-token` / `claude auth status --json` (preflight
primitives), `--max-budget-usd` / `--max-turns` (in-invoker governors with `error_max_budget_usd`/`error_max_turns`
subtypes), Opus 4.7/4.8 **reject manual `thinking.budget_tokens`** (400 -> use `effort`, 5 levels), `fallbackModel` can
change the active model **mid-turn**, and the **June 15 2026 Agent SDK credit** splits subscription `claude -p` billing
(no change to `total_cost_usd` reporting). `--bare` will become the `-p` default in a future release -> set Forge's
flags explicitly.

### Slice 5.0 - Re-pin + correct stale assumptions (DONE 2026-06-08)

- [x] Correct the Codex hook/version facts in `card.md` and the runtime registry; sync `design.md` §5.5.5.
  - Assertion: the card no longer claims `codex_hooks = true` is required or lists 5 events; the registry's Codex
    `RuntimeSpec` drops the removed flag and records the version gate honestly; tests pass.
  - Verification (2026-06-08): `card.md` Codex hooks paragraph + capability matrix (Native hooks, Curated transfer
    input) + posture bullets (non-interactive auth, Responses-API) + Phase 5/6 notes corrected;
    `src/forge/core/runtime/registry.py` Codex spec -> `hook_feature_flag=None`, `hook_min_version="0.131.0"`,
    `native_hooks="gated"` (version-only), default-on note (10 events, `updatedInput`, `allow_managed_hooks_only`,
    Responses-API, verified vs 0.137.0); `HookSupport` Literal comment generalized; `cli/runtime.py` markup comment
    updated. `design.md` §5.5.5 synced. Tests updated + green: `tests/src/core/runtime/test_registry.py::TestCodexSpec`
    - `tests/src/cli/test_runtime.py` (17 passed); `mypy` clean on changed src.
  - [x] (debt, pre-commit) run `make pre-commit` before committing -- `mdformat` re-aligns the capability-matrix cells
    edited above and validates links/anchors. Cleared 2026-06-08 (Slice 5a; full `make pre-commit` clean).

### Slice 5a - Codex auth/runtime preflight

**Stage A probe (verified 2026-06-08, codex-cli 0.137.0) -- binary-authoritative facts (sanitized; no raw
output/secrets/paths):**

- **`codex --version`** -> `codex-cli 0.137.0` (>= 0.131.0 floor; `detect()`/`_probe_version` must parse the
  `codex-cli <ver>` two-token shape).

- **`codex doctor --json`** -> `schemaVersion: 1`; exited 0 this run (the earlier exit-1 was transient provider
  reachability) -- "parse stdout regardless of returncode" (B3) stands as defensive coding.

  - `overallStatus: "warning"` **while `auth.credentials.status="ok"`** -- the warning is an unrelated
    `state.rollout_db_parity` (stale rollout rows), NOT auth. **Empirical proof `overallStatus` must NOT gate `ready`**
    (B3/B4); it is informational `doctor_status` only.
  - `auth.credentials.details` uses **string booleans** (`"true"`/`"false"`, not JSON booleans). Confirmed exact field
    names: `stored API key`, `stored ChatGPT tokens`, `stored agent identity`, `stored auth mode`. Parser MUST compare
    `== "true"` (a non-empty `"false"` is truthy).
  - **No hook-trust check exists in `doctor`** (checks are
    auth/config/git/install/mcp/network/sandbox/state/updates/...; there is no `hooks` check). **RESOLVES the plan's one
    open unknown:** 5a cannot read per-hook trust from doctor -> 5a never returns `hook_seam="active"`; `unknown` is the
    honest normal case (B4). (`config.load` lists `hooks` among "enabled feature flags" -- that is enablement, not
    trust.)
  - `doctor` reports `auth env vars present: OPENAI_API_KEY` yet `stored API key=false` / `stored auth mode=chatgpt`:
    confirms an `OPENAI_API_KEY` in env does NOT satisfy Codex auth (the `codex-api` note's "not OPENAI_API_KEY" holds).

- **`codex features list`** (no `--json`) -> columnar `<name> <stability> <bool>`; this machine: `hooks  stable  true`.
  Stability column can be multi-word (`under development`), so parse by **first token == `hooks`, last token == bool**;
  match the exact token (a `plugin_hooks  removed  false` row also exists; the `codex_hooks` alias is not present).

- **`codex exec --help`** -> confirms `--sandbox {read-only,workspace-write,danger-full-access}`, `-p/--profile`,
  `--dangerously-bypass-hook-trust`, and the `exec resume` subcommand for 5b; no `--full-auto` (use sandbox/profile).

- **`codex app-server --help`** -> `--stdio` and `--listen stdio://` (default) are real (the stale-docs case);
  subcommands `daemon|proxy|generate-ts|generate-json-schema` (5b/Phase 6 input).

- **`codex login status`** -> "Logged in using ChatGPT" (this machine's active auth = `chatgpt_tokens`).

- **Managed config**: neither `$CODEX_HOME/requirements.toml` nor `/etc/codex/requirements.toml` present -> `hook_seam`
  falls through to `unknown` here (absence is not proof of "not suppressed"; B4).

- **This machine's expected preflight:** installed, `0.137.0`, `version_ok`; `auth_method=chatgpt_tokens` /
  `auth_source=codex_store` / `billing_mode=subscription_quota`; `ready=True` (no `--proxy`); `hook_seam=unknown`;
  `proxy_responses=native_direct`; `doctor_status="warning"` (informational only).

- [x] Build a native-Codex preflight (the card's "Compliance and Auth Preflight" for Codex), run by the launcher before
  any `codex exec`. Reads the runtime registry (4e); does the dynamic environment checks the static matrix cannot.

  - Assertion: resolves a non-interactive credential (`CODEX_API_KEY` -> device-token -> enterprise token) and **fails
    closed** with setup guidance when none resolves; reports `codex doctor` state; verifies hook **enablement + trust**
    (so the 5d `SessionStart` transfer seam won't silently no-op -- else 5d falls back to an initial message) and
    surfaces `allow_managed_hooks_only` as a capability limitation; blocks only when the proxy cannot serve the
    **Responses API on its Codex-facing endpoint** (a translated chat-completions *backend* does NOT block); tags
    API-key vs ChatGPT-subscription as distinct billing pools.
  - Verification (2026-06-08): shipped `src/forge/core/runtime/codex_preflight.py` -- frozen `CodexPreflight` contract +
    `preflight_codex`/`assert_codex_ready` (typed `CodexPreflightError`, mirroring `validate_proxy_startup`) + the
    non-rendered `codex_api_key_for_subprocess()` (the resolved key value is NEVER a result field -- would leak via
    `asdict()`/`--json`); the `codex-api` (`CODEX_API_KEY`) credential; and
    `forge runtime preflight codex [--proxy] [--json]`. Binary-authoritative per the Stage-A note: doctor parsed
    regardless of exit code, string-boolean details (`== "true"`), `overallStatus` NEVER gates `ready`
    (`ready = installed AND auth resolved AND not responses-blocked`). **Stage-A-driven honesty deviations from the
    original assertion:** doctor exposes NO per-hook trust, so 5a verifies hook **enablement** only and `hook_seam`
    never returns `active` (per-hook-hash trust is a 5d check); the Responses concern is a capability **report** read
    from an existing proxy's `wire_shape` via `config.loader` (no `forge.proxy` import, no `/v1/responses` route), not
    an over-blocking guard. Live `forge runtime preflight codex` (0.137.0):
    `chatgpt_tokens`/`codex_store`/`subscription_quota`, `hook_seam=unknown`, `doctor=warning`, **Ready YES**, exit 0;
    unknown `--proxy` -> exit 1; non-codex runtime -> exit 2. Tests: 85 focused green (`test_codex_preflight.py`,
    `test_runtime.py` preflight, `test_capabilities.py` codex-api) + 244 broader (auth/runtime/CLI); mypy + pyright
    0/0/0 on changed src. No Docker/integration tier (5a spawns nothing).
  - Review hardening (2026-06-08, 7 findings): (1) `_resolve_responses_posture` catches the loader's
    `ValueError`/`TypeError` (invalid id / corrupt `proxy.yaml`) -> `proxy_unsupported`, never a traceback (the
    never-raise contract held); (3) managed-suppression tests monkeypatch `_managed_requirements_paths` (no `/etc`
    leak); (4) nested `[hooks]` TOML branch covered; (5) version compare pads components (`0.131` meets `0.131.0`); (6)
    **decision:** stored-auth is PRESENCE-based -- do NOT gate on `auth.credentials.status` (same false-fail-closed risk
    as overallStatus; validity is proven at 5b), documented + tested; (2) stale credential docs fixed
    (`authentication.md` + `design_appendix.md`); (7) per-worker doctor cost recorded as the 5b note above.
  - Design-doc debt (-> 5f): `design.md` §5.5.5 still frames the preflight as a *future* first consumer of the registry;
    flip it to "shipped" in 5f's comprehensive Phase 5 design sync (the approved plan batches Phase 5 design sync
    there).

| Test                                 | Fixture                                                                                 | Assertion                                                                                                                                                   | Test File                                        |
| ------------------------------------ | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| No credential -> fail closed         | doctor stored apikey/agent/chatgpt all `"false"`; no env token                          | `assert_codex_ready` raises; reason names `CODEX_API_KEY` + `codex login --device-auth` + `CODEX_ACCESS_TOKEN` + `forge auth login -c codex-api`; not ready | `tests/src/core/runtime/test_codex_preflight.py` |
| Installed is a precondition of ready | `which`->None but `CODEX_API_KEY` in env                                                | `installed`/`ready` False; reason names install (a resolved key alone is not ready)                                                                         | same                                             |
| Doctor authoritative (env absent)    | doctor stored ChatGPT tokens `"true"`                                                   | ready; `chatgpt_tokens`/`codex_store`/`subscription_quota` (env-only would wrongly fail closed)                                                             | same                                             |
| Doctor parsed on non-zero exit       | `subprocess.run` returncode=1 + valid JSON stdout                                       | parsed; auth resolves; `doctor_status` captured but does not gate `ready`                                                                                   | same                                             |
| String-boolean parsing               | detail `stored API key == "false"` (truthy string)                                      | treated as absent, not present                                                                                                                              | same                                             |
| Billing + auth method                | env `CODEX_API_KEY` / doctor chatgpt / env `CODEX_ACCESS_TOKEN` / doctor agent identity | api_key/api; chatgpt_tokens/subscription_quota; enterprise_token/unknown (x2)                                                                               | same                                             |
| Credential-store hydration           | `CODEX_API_KEY` only in credential file                                                 | `credential_file`; ready; `codex_api_key_for_subprocess()` returns it; value absent from `asdict(result)`                                                   | same                                             |
| Managed suppression (explicit only)  | tmp `requirements.toml` `allow_managed_hooks_only=true` / no file                       | `managed_suppressed` (NOT a ready blocker) / not inferred (`unknown`)                                                                                       | same                                             |
| Hook seam never `active`             | features=false / version `0.130.0` / unparseable version / enabled + doctor trust hint  | disabled / disabled / unknown / unknown                                                                                                                     | same                                             |
| Responses report                     | proxy `None` / `proxy.yaml` `wire_shape` / unknown id                                   | `native_direct` / `proxy_unsupported` (cites wire_shape) / `proxy_unsupported` ("not found")                                                                | same                                             |
| CLI                                  | stubbed `preflight_codex`                                                               | `--json` shape (no secret) + exit 0 ready / exit 1 not-ready / unknown runtime exit 2                                                                       | `tests/src/cli/test_runtime.py`                  |

**5b-5f shipped; Phase 5 complete** (5f = docs-only design/end-user sync + Phase 6 record). The build group was executed
probe-first from the approved plan: a real `codex exec --json` run pins the parser, then parser -> shared lifecycle ->
invoker -> emitter -> transfer relabel; 5e composes them into the Claude->Codex bridge under one run tree.

**Resolved decisions (baked into shipped code):**

- **5c `confidence` = `unavailable`** (not `reported`): the ledger's `confidence` is a **cost** signal and Codex reports
  no dollars; tokens are still attributed (`reporter=codex_jsonl`/`runtime_native`). Mirrors the Claude tokens-only
  branch `_direct_cost_provenance`.
- **5d depth = minimal relabel** (frontmatter `target_runtime` + `## Runtime Hints` body). The curated body stays
  Claude-worded; curation-prompt tuning is a follow-up.
- **SessionStart-hook delivery -> Phase 6.** `hook_seam` can't confirm per-hook trust (5a), so the curated transfer is
  delivered as the **initial `codex exec` message** (prepended to the prompt) rather than a SessionStart
  additionalContext hook. 5b/5d ship the request-builder + relabel; the prompt-composition seam shipped in **5e**
  (`core/ops/codex_bridge.py::compose_codex_initial_message`).

### Slice 5b - CodexHeadlessInvoker (one-shot `codex exec`) (DONE 2026-06-08)

- [x] **B0 probe-first fixtures.** One real cheap `codex exec --json` captured verbatim (secret-scanned) to
  `tests/fixtures/codex/{exec_json_success.jsonl,exec_json_error.jsonl,exec_last_message_success.txt,README.md}`
  (codex-cli 0.137.0). Authoritative over docs; confirmed the doc-sourced token field names.
- [x] **B1 `parse_codex_jsonl_stream`** (`core/invoker/codex_stream.py`): pure JSONL reducer ->
  `(final_text, tokens, is_error)`. `final_text == -o oracle`; error stream (`error`+`turn.failed`, exit 1, no usage) ->
  `runtime_is_error`.
- [x] **B2 shared lifecycle** moved verbatim into `_HeadlessLifecycleBase` (`core/invoker/_lifecycle.py`) with six
  template hooks; `ClaudeHeadlessInvoker` subclasses it. ~30 test patch-strings migrated `claude.<sym>` ->
  `_lifecycle.<sym>` across `test_claude_invoker.py` + 3 review drivers + the json-flag regression; both retry-race
  canaries + cancellation green ("moved, not changed").
- [x] **B3/B4 `CodexHeadlessInvoker` + `prepare_codex_request`** (`core/invoker/codex.py`): argv
  `codex exec --json --sandbox <mode> [-m <model>]`; env built once per launch (inject `CODEX_API_KEY` only when
  `auth_source in {env, credential_file}`; no `ANTHROPIC_*`/`base_url`); run-tree triple stamped via the neutral
  `stamp_run_identity` (factored out of `build_claude_env`). Codex's format-retry predicate is always `False` (dead
  branch). Preflight runs **once** per launch -- the ~20s `codex doctor` ceiling is not multiplied across a fan-out.

| Test                       | Fixture                                        | Assertion                                                                                                                                                                                | Test File                                                   |
| -------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| Stream parse (pinned)      | `exec_json_success.jsonl` + `-o` oracle        | `final_text == oracle == "OK"`; tokens `(14936, 22, 10624)`; error fixture -> `is_error`                                                                                                 | `tests/src/core/invoker/test_codex_stream.py`               |
| Claude lifecycle unchanged | 17 existing tests, patch paths -> `_lifecycle` | all green incl. both retry-race + cancellation + ordering                                                                                                                                | `tests/src/core/invoker/test_claude_invoker.py`             |
| Codex invoker              | Popen replays the fixture                      | `stdout=="OK"`, tokens lifted; error stream -> `runtime_is_error`+rc1; missing binary -> `"codex CLI not found in PATH"`; input-order; run_id surfaced                                   | `tests/src/core/invoker/test_codex_invoker.py`              |
| No-format-retry            | Claude-rejection stderr                        | exactly one Popen (predicate `False`)                                                                                                                                                    | same                                                        |
| Request-builder            | preflight stub                                 | argv `codex exec --json`; `CODEX_API_KEY` injected for `credential_file`, NOT for `codex_store`; run-tree triple; `base_url is None`; attribution stamped `runtime=codex`+`billing_mode` | same                                                        |
| (gated) real smoke         | real `codex` + auth                            | `codex exec --json` returns parsed text + tokens; one `runtime_native` event                                                                                                             | `tests/integration/core/test_codex_exec_smoke.py` (`@slow`) |

Deferred (recorded): the `codex app-server`/`--stdio` transport for resumed multi-turn Codex sessions -- one-shot
`codex exec` ships first; spike before committing if multi-turn resume is clumsy.

### Slice 5c - Codex usage attribution (ledger) (DONE 2026-06-08)

- [x] `emit_codex_usage` (`core/usage/emit.py`): `route=codex_exec`/`reporter=codex_jsonl`/`runtime_native`,
  `confidence=unavailable`, `cost_micro_usd=None`, `source_refs=None`; tokens from the JSONL; `billing_mode` from
  `CodexPreflight` (carried via a new optional `Attribution.billing_mode`). Wired through `_emit_codex` in `codex.py`.

| Test                      | Fixture                                            | Assertion                                                                                                                         | Test File                                 |
| ------------------------- | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Reserved-literal event    | tokens + `billing_mode="api"`                      | `route=codex_exec`/`reporter=codex_jsonl`/`runtime_native`/`confidence=unavailable`/`cost None`/`source_refs None` + exact tokens | `tests/src/core/usage/test_codex_emit.py` |
| Invoker-path emission     | `run_parallel` w/ `Attribution(runtime=codex,...)` | one worker event; run-tree ids == stamped env                                                                                     | same                                      |
| Opt-out / no run id       | no attribution / empty run_id                      | no event                                                                                                                          | same                                      |
| Run-tree join (5e anchor) | Codex + Claude leaf share root                     | `read_usage_events(root_run_id=...)` returns both                                                                                 | same                                      |

### Slice 5d - Target-runtime transfer (minimal relabel) (DONE 2026-06-08)

- [x] `target_runtime` threaded through `assemble_transfer_context` (default `claude`, byte-identical to pre-5d);
  replaces the hardcoded `TRANSFER_TARGET_RUNTIME` at the frontmatter stamp + `## Runtime Hints` body.
  `forge transfer regenerate <parent> --target-runtime {claude|codex}` (`cli/transfer.py` -> `core/ops/transfer.py`),
  defaulting the runtime from the existing cache frontmatter (never silently flips). Delivery will be initial-message
  (no system-prompt-file flag; no `$CODEX_HOME/hooks` write); the prompt-composition seam that prepends the transfer
  body to the `codex exec` prompt is **5e**. Curation-prompt tuning is the deferred follow-up.

| Test                  | Fixture                  | Assertion                                                                                                    | Test File                            |
| --------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| Frontmatter + relabel | `target_runtime="codex"` | frontmatter `target_runtime: codex`; Runtime Hints names Codex idioms (`codex exec`, sandbox)                | `tests/src/session/test_transfer.py` |
| Invariants            | claude vs codex variant  | `schema_version` unchanged (==1); section skeleton identical; everything before Runtime Hints byte-identical | same                                 |
| CLI regenerate        | `--target-runtime codex` | frontmatter flips to codex; defaults from cache (no silent flip back); unknown runtime rejected              | `tests/src/cli/test_transfer_cli.py` |

**Verification (build group):** the unit suites above + migrated review/regression suites (430 passing); real-codex
`@slow` smoke green (8s); `mypy` clean (15 files); `make pre-commit` clean. Design sync done here (the thin/consolidated
touch the plan scheduled at the build-group tail): `design.md` §5.5.5 (shared `_lifecycle` base + two invokers), §3.14
(native Codex `runtime_native` emitter), §3.9 (`target_runtime` relabel + initial-message delivery; SessionStart ->
Phase 6). This resolves 5a's deferred §5.5.5 "future" note; 5f's remaining scope is the end-user guide + Phase 6 record.

### Slice 5e - Claude->Codex resume bridge (the payoff) (DONE 2026-06-09)

Scope (planning Q&A): UI-agnostic **core-ops function** only -- the user-facing `--runtime codex` frontend is Phase 6;
drive the demo with `--strategy ai-curated` and **instrument the transfer curation** to emit the non-Codex side of the
run tree; the end-user demo doc is **deferred to 5f**.

- [x] `core/ops/codex_bridge.py::bridge_session_to_codex`: parent session -> ai-curated transfer
  (`target_runtime=codex`) -> transfer body **prepended to the `codex exec` prompt** (initial-message delivery, _not_ a
  `SessionStart` hook -- per-hook trust is unconfirmable, 5a) -> `CodexHeadlessInvoker().run` -> Codex implements;
  curation + codex events attributed across **one run tree**.
  - Assertion: the hop uses **curated transfer** (signatures non-portable); a fresh root minted via
    `new_root_run_identity()` and set into `os.environ` for the block is what places both the curation `core.llm` call
    and the `codex exec` run under one root; `read_usage_events(root_run_id=...)` + `build_session_activity_summary`
    show both sides, same session.
- [x] Part A: transfer curation now emits a usage event (`.ask`->`.complete` to capture in-band tokens; `route=core_llm`
  / `runtime=forge_cli` / `command=transfer-curate`). General gap-fix: no-ops without an ambient run identity, so a
  normal `resume --strategy ai-curated` outside a run tree stays silent.

| Test                            | Fixture                                                    | Assertion                                                                                                                                                                            | Test File                                               |
| ------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| Bridge orchestration (hermetic) | mock curation `.complete` + Codex `Popen` (success stream) | per-run child key; frontmatter `target_runtime: codex`; `read_usage_events(root)` -> exactly one `core_llm`/`forge_cli` + one `codex_exec`, same root+session; `os.environ` restored | `tests/src/core/ops/test_codex_bridge.py`               |
| Seam + env manager              | unit                                                       | `compose_codex_initial_message` body precedes task, Codex framing, no frontmatter; `_temporary_run_env` sets root+session, scrubs parent, restores on exception                      | same                                                    |
| Curation emits under run tree   | run identity set vs unset                                  | one `core_llm`/`forge_cli` event with identity; none without                                                                                                                         | `tests/src/session/test_transfer.py`                    |
| Real-codex E2E (`@slow`)        | real `codex`; curation mocked at `_call_llm_for_curation`  | real `codex exec` consumes the curated-transfer prompt + completes; both events under one root; activity summary shows both                                                          | `tests/integration/core/test_claude_to_codex_resume.py` |

**Verification (2026-06-09):** hermetic + transfer + codex-emit suites pass (99); real-codex E2E green (~8s, real
`codex 0.137.0` chatgpt_tokens); 5b smoke regression green (~5s); `mypy` clean (changed src); `make pre-commit` clean.

**Deferred to 5f (design-sync debt):** `design.md` §3.9 (Codex **initial-message** delivery via the bridge), §3.14
(transfer curation now emits a `core_llm`/`forge_cli` usage event), §5.5.5 (the bridge composes preflight + invoker);
the end-user cross-runtime workflow doc. No CLI command and no `SessionStart`-hook delivery (both Phase 6).

**Minor follow-up (non-blocking):** each bridge run writes a synthetic `<parent>-codex-<run-suffix>` child under
`prev_sessions/<parent>/children/` with no backing child session; these accumulate. A namespacing/GC pass can land later
(out of 5e scope). The action tagger's pre-existing `emit_direct_llm_usage` default `runtime="claude_code"` is unchanged
here; reconciling it with `forge_cli` for `core.llm` calls is also out of scope.

### Slice 5f - Design/end-user doc sync + Phase 6 re-scope (record) (DONE 2026-06-09)

Docs-only closeout of Phase 5. No code. (Design sync lands in §3.9, **not** §5.5.5 as the checklist loosely scoped: the
bridge is a cross-runtime resume-delivery op, not a workflow runner; §5.5.5 was already correct and untouched.)

- [x] `design.md` §3.9 rewritten future->past: the shipped `bridge_session_to_codex` (parent -> ai-curated
  Codex-targeted transfer -> body prepended to the `codex exec` prompt -> `CodexHeadlessInvoker().run`, one run tree);
  initial-message delivery is the Phase 5 mechanism, `SessionStart`-hook delivery deferred to Phase 6; no CLI yet (user
  surface = `forge transfer regenerate --target-runtime codex` + manual `codex exec`). §3.14 gained a "Transfer curation
  usage (Phase 5e)" paragraph (`route=core_llm`/`runtime=forge_cli`/`transfer-curate`).
  - Assertion: design docs describe shipped Phase 5 behavior (documentation-guidelines Rule 2); no stale 5-event /
    `codex_hooks` claim remains outside `done/` (sweep confirmed none survived; the `design.md`/`card.md` `SessionStart`
    refs now name initial-message delivery).
- [x] `design_appendix.md`: §A.13 enums flip `codex_exec` (route) + `codex_jsonl` (reporter) from reserved -> emitted;
  per-emitter table gains the `transfer-curate` row (tags `session`); §M.1 `target_runtime` comment de-staled.
- [x] New end-user guide `docs/end-user/transfer.md`: the `forge transfer show|regenerate|edit|diff` group + the
  three-file model + the honest cross-runtime workflow (`regenerate --target-runtime codex` -> `show` -> manual
  `codex exec`; one-command bridge is Phase 6). Registered in `README.md`; `session.md` artifact note repointed to it.
- [x] `card.md` Phase 6 note corrected ("Phase 5 uses only `SessionStart`" -> initial-message delivery; SessionStart
  deferred). The dated 5a change_log "provisional" line is left as a historical snapshot (board-contract: don't rewrite
  dated entries).

**Verification (2026-06-09):** `make pre-commit` clean (mdformat + the new guide); `design.md`/`design_appendix.md`
under the tiktoken size hook; grep gates clean (`SessionStart` outside `done/` names initial-message delivery;
`codex_exec`/`codex_jsonl` shown as emitted); `forge transfer --help`/`regenerate --help` confirm the guide matches the
shipped CLI; the documented `regenerate -> show -> codex exec` path is covered end-to-end by the 5e real-codex E2E
(`tests/integration/core/test_claude_to_codex_resume.py`). **Phase 5 complete.**

### Open risks (carry into execution; verify empirically)

- **Transport:** one-shot `codex exec` vs the app-server (`--stdio`) for resumed multi-turn Codex sessions is unproven
  -- the chosen `codex exec` path ships first; spike the app-server before committing if multi-turn resume is clumsy.
- **Custom-header forwarding** is doc-*implied*, not doc-stated -- the 4g canary is the standing empirical guard; re-run
  it on Codex/Claude version bumps.
- **Codex hooks graduation version** (0.131.0 default-on) carries mild uncertainty -- the 5a preflight should verify
  against the installed build via `codex doctor`, not trust `hook_min_version` blindly.
- **`fallbackModel`** (CC 2.1.166/168) can change the active model mid-turn -> the usage event `model` must be the
  actual routed model, and the 4g run-tree join must tolerate it.
- **LiteLLM `chatgpt/` route** is ToS-gray (header spoofing) with a volatile model roster -- gated last resort only.
- **`SessionStart` transfer injection is conditional**, not guaranteed: it fires only when hooks are enabled and the
  hook is trusted (untrusted/first-run projects skip project-local `.codex/` hooks; new/changed hooks are skipped until
  reviewed). 5d MUST keep an initial-message fallback and 5a MUST check hook state, or the curated context silently
  vanishes. The one review-exempt delivery is a managed hook (`requirements.toml`).
- **Codex wire (V1 nuance):** the requirement is Responses on the proxy's *Codex-facing* endpoint only; the backend may
  be Chat Completions translated. Do not block a route just because the upstream model speaks chat-completions. The
  `codex/models` prose still shows a stale either/or; `config-reference` (`wire_api="responses"` only) is authoritative.

## Phase 6 - Codex Frontend Beta (evaluation only)

**Scope (resolved 2026-06-09; see Open Decisions):** Phase 6 is **evaluation only** -- no product features.
Deliverables: a reproducible probe harness (`scripts/experiments/codex-hooks/`), a Stage-A-style decision record with
per-deliverable go/no-go verdicts, and a follow-up build card (`docs/board/proposed/codex_frontend/`). Hook fixtures are
descoped to the build card (see Slice 6.1): hook payloads need a firing hook, which is headless-unavailable. The
decision record satisfies this phase's evaluate box and completes the card (build work moves to the follow-up card).
Evaluation coverage decisions: the probe pins facts for the **broader hook set** (PreToolUse + PermissionRequest + Stop
\+ UserPromptSubmit); **SessionStart transfer delivery with initial-message fallback** is the build direction whose
trust/`additionalContext` feasibility the probe must settle; **app-server transport is deferred, unevaluated** (recorded
verbatim, not probed).

- [x] Evaluate Codex as an interactive frontend runtime.
  - Assertion: decision is based on headless invocation, usage accounting, policy semantics, and curated transfer
    results from earlier phases.
  - Execution (2026-06-09): satisfied by the Slice 6.1 decision record (go/no-go table, every verdict citing probe-stage
    artifacts), not by shipped frontend code. Net: bridge CLI is GO; all hook-dependent deliverables are
    headless-impossible or gated on unverified interactive firing -> the `codex_frontend` build card.

### Slice 6.0 - Probe harness (pin the unverified facts)

Every Phase 6 deliverable rests on facts that are doc-implied or never exercised against the binary. Standing rule
(5.0/5a precedent): the installed binary is authoritative; docs are leads. Harness mirrors
`scripts/experiments/native-resume/` (staged `reproduce.sh`, verdict vocabulary, hermetic mktemp root + isolated
`CODEX_HOME`, auth copied 0600 into the temp tree, loud secret-scan in `sanitize.sh`, cheap one-word-reply turns, ~18-22
total turns).

Fact groups: (1) hook payload JSON shapes per event; (2) response wire contracts (deny JSON/exit-2, `updatedInput`,
UserPromptSubmit block -- the `%`-command seam, SessionStart `additionalContext` landing verifiably in model context,
PermissionRequest `decision.behavior`, Stop block-once, malformed-output fail-closed); (3) registration mechanics
(user/proj x toml/json surfaces, matchers); (4) trust mechanics (untrusted-skip, project `trust_level` vs per-hook-hash,
where trust state lives, hash-keying on content change); (5) whether hooks fire under `codex exec` at all -- the gating
unknown; (6) interactive management facts (initial-prompt arg, `FORGE_SESSION` reaching hooks, session/rollout file
location + discoverable session id); (7) `codex exec resume` semantics (`thread_id`, `--json` composition, cross-cwd,
`--last`); (8) PreToolUse bypass paths (simple/compound shell, apply_patch, optional MCP).

- [x] Stage 00 preflight (0 turns): codex-cli **0.138.0** (drift-stamped from the 0.137.0 pin), `features list`
  hooks=true, `CODEX_HOME` isolation verified, `--help` captured.
- [x] Stage 05 config-schema (0 turns; added during execution): `--strict-config` + bogus-model classifies registration
  acceptance without a completion. **Refutes the doc-implied "strict registration":** required inner fields ARE
  validated (a `comand` typo errors "missing field `command`"; unknown top-level keys error), but unknown inner/outer
  hook-entry fields **and bogus event names** (`[[hooks.NotARealEvent]]`) load **silently** -- a misspelled event never
  errors.
- [x] Stage 10 headless-fire **(GATE)**: SessionStart tee on all 4 surfaces, plain exec +
  `--dangerously-bypass-hook-trust` retry -> **0 firings**. Stage verdict **`[NO-FIRE-UNCATEGORIZED]`**; 5 independent
  clean controlled runs confirmed headless hooks do not fire. Interactive firing is **unverified** (operator-gated ->
  build card), so the result is NOT "[INTERACTIVE-ONLY]" -- that classification would require interactive evidence.
- [x] Stage 20 payloads (facts 1, 3): real read-only + workspace-write turns. A real `SessionStart`/`Stop` payload was
  captured (snake_case, doc-shape confirmed) but **only via a non-reproducible codex first-run/bootstrap session** --
  clean isolated turns fire 0. Payload **shape** pinned; reliable headless capture is not available.
- [~] Stage 30 responses (fact 2): **moot headless** -- a hook that never fires cannot demonstrate a deny/mutate/
  additionalContext contract. Deferred to an interactive (operator/build-card) probe. Not spent (saved ~8 turns).
- [x] Stage 40 trust (fact 4): headless sub-steps run; 0 firings even with project `trust_level` set and bypass-trust.
  The interactive trust-flow + trust-store-location discovery is **operator-gated (TTY)** -> build card.
- [x] Stage 50 interactive (fact 6): headless sub-steps run. **Pinned:** session/rollout path
  `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl` (filename embeds the session id); `FORGE_SESSION`
  reaches the model shell; codex does a first-run plugin-marketplace clone into `$CODEX_HOME/.tmp/plugins`. Interactive
  initial-prompt arg + interactive hook firing are **operator-gated (TTY)** -> build card.
- [x] Stage 60 exec-resume (fact 7): **`codex exec resume <thread_id>` works, recalls context, and resumes CROSS-CWD**
  (unlike Claude's CWD-bound `--resume`); `--json` composes with options before the `resume` subcommand; the id is the
  stream `thread_id`. `--last` is unreliable headless (spawned a fresh thread). Feeds bridge-CLI = GO.
- [~] Stage 70 bypass (fact 8): **moot headless** (PreToolUse never fires headless) -> interactive/build-card.

### Slice 6.1 - Decision record (+ registry correction)

- [~] Fixtures to `tests/fixtures/codex/hooks/`: **descoped to the build card.** The only reliably-reproducible artifact
  headless is the `codex exec resume` stream (≈ the existing `exec_json_success.jsonl` + `thread_id` continuity), and
  hook **payload** fixtures require firing, which is headless-unavailable -- they must be captured on the interactive
  path (operator/build-card). The confirmed payload **shape** is recorded below; no raw hook fixtures are committed this
  phase.
- [x] Decision record written (below).
- [x] Registry correction: the binary contradicts the declared facts -- `native_hooks="gated"` + `hook_min_version` read
  as "hooks work once version-gated," but hooks are enabled + version-OK yet **do not fire headless**. Corrected the
  Codex `RuntimeSpec` machine-readable fields (not just the note): `native_hooks="headless_inert"` (new `HookSupport`
  value -- registers/enables but does not fire under `codex exec`; interactive unverified) and `pretool_policy="none"`
  (PreToolUse never fires headless -> no verified enforcement). A consumer reading the field, not just the prose, now
  sees the limit. `codex_preflight.py` `hook_seam` updated to match: the normal enabled+version-OK headless case now
  returns `headless_inert` (was `unknown`/"trust unproven") -- a new `HookSeam` literal mirroring the registry value, so
  `forge runtime preflight codex` no longer reads as "might work, trust unproven." Still never returns `active` (that
  verdict belongs to 5d's real hook); `unknown` is kept only for the moot not-installed / unparseable-version cases.

#### Phase 6 probe -- Codex hooks/frontend evaluation (verified 2026-06-09, codex-cli 0.138.0)

**Harness:** `scripts/experiments/codex-hooks/` (`./reproduce.sh`); captures outside the repo. Re-pinned 0.137.0 ->
**0.138.0** (changelog claims 0.138/0.139 hook-neutral). Markers: confirmed-doc / refuted-doc / doc-silent-now-pinned.

- **(fact 5, GATE -- doc-silent-now-pinned) Headless `codex exec` does NOT deliver hooks.** 0 firings across **5
  independent clean isolated runs**: 4 registration surfaces (user/project x `config.toml`/`hooks.json`); plain exec,
  `--dangerously-bypass-hook-trust`, and repeated same-home turns; real turns including one that executed a shell tool.
  No hook/trust warning on stderr. Two harness stages (40/50) first showed firings -- traced to a stale per-stage
  capture dir (harness bug, fixed: `probe_init` now clears it) and/or a non-reproducible codex first-run bootstrap
  session; neither reproduced under isolation. **For Forge: headless hook delivery is not dependable.**
- **(fact 1 -- confirmed-doc) Payload shape is snake_case as documented.** A real `SessionStart` payload:
  `{session_id, transcript_path, cwd, hook_event_name, model, permission_mode, source}` with `source:"startup"`; `Stop`
  carries the same `session_id`. Reliable *capture* needs the interactive path; the shape is pinned.
- **(fact 3 -- refuted-doc) Registration validation is shallow.** `--strict-config` validates required inner fields
  (missing `command` errors) and unknown top-level keys, but **silently accepts unknown hook-entry fields and bogus
  event names** -- a typo'd event (`[[hooks.NotARealEvent]]`) never errors. A Forge installer must validate event names
  itself.
- **(fact 7 -- confirmed + refined) `codex exec resume <thread_id>` is solid and CROSS-CWD.** Recalls prior context from
  a *different* project dir (Claude's `--resume` cannot); `--json` composes (options before the `resume` subcommand); id
  = stream `thread_id`. `--last` unreliable headless (spawned a fresh thread). Codex-side continuation after the bridge
  hop is viable by id.
- **(fact 6 -- partly pinned) Session files + env.** `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<session_id>.jsonl`
  (filename embeds the session id -> discoverable for a `confirmed` manifest field); `FORGE_SESSION` reaches the model
  shell; first-run plugin-marketplace clone into `$CODEX_HOME/.tmp/plugins`. Initial-prompt arg + interactive hook
  firing: **operator-gated (TTY); not verifiable from a non-interactive harness** (`codex` refuses non-TTY stdin; a pty
  via `script` starts the TUI but it needs real terminal interaction).
- **(facts 2, 4, 8 -- interactive-gated) Not observable headless.** Response contracts, trust flow + trust-store
  location, and PreToolUse bypass all require firing hooks; deferred to an interactive operator probe in the build card.
- **(scope) app-server: not probed -- deferred, unevaluated** (decision 2026-06-09).

**Go/no-go (every verdict cites stages above):**

| #   | Deliverable                                           | Verdict                                                                           | Basis                                                                                                                                                                   |
| --- | ----------------------------------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| iii | One-command bridge CLI over `bridge_session_to_codex` | **GO**                                                                            | No hook dep; `exec resume` incl. cross-CWD verified (60); the core op already ships (Phase 5e)                                                                          |
| ii  | SessionStart curated-transfer delivery                | **NO-GO for the (headless) bridge -> initial-message stays primary, permanently** | Headless hooks never fire (5,10) -- a `codex exec` bridge can't use `additionalContext`. Vindicates the Phase 5 deferral. Interactive frontend *could*, iff (iv) clears |
| i   | Codex hook adapter/responder (policy on Codex)        | **NO-GO headless; UNVERIFIED interactive**                                        | Policy on `codex exec` fan-out impossible (5,10,30-moot). Payload->`ActionContext` mapping is shape-ready (1); responder contracts unverified (2 interactive-gated)     |
| iv  | Interactive Codex frontend under Forge sessions       | **UNVERIFIED -- gated on interactive hook firing**                                | Requires a TTY operator session (50); folded into the build card as its first gating probe                                                                              |
| v   | App-server transport                                  | **DEFERRED, unevaluated**                                                         | Scope decision 2026-06-09                                                                                                                                               |

**Net:** the bridge CLI is the one clearly-shippable Phase 6 deliverable; everything hook-dependent is gated on a firing
capability that `codex exec` lacks on 0.138.0 and that interactive Codex has not been verified to provide. The
interactive-firing probe + hook-payload fixtures move to the build card (you only need them if you build the interactive
frontend).

### Slice 6.2 - Follow-up card + closeout

- [x] Authored `docs/board/proposed/codex_frontend/card.md`, seeded with the probe facts: bridge CLI (GO, build first),
  the interactive-firing gating probe, hook adapter/responder + the `ActionContext.runtime -> origin` rename,
  SessionStart-with-fallback, interactive frontend, installer Codex support, app-server (deferred).
- [x] Closeout per board-contract: Phase 6 boxes ticked with verification; `change_log.md` Phase 6 entry added; durable
  lessons proposed via `.forge/memory/shadow_impl_notes.md` (human-promote gate). **Design-doc check: `design.md`
  runtime-registry section synced** to the corrected Codex capability values. Phase 6 changed no runtime/execution
  behavior; the `src/` edits are `registry.py` + `codex_preflight.py` capability-honesty corrections
  (`native_hooks="headless_inert"`, `pretool_policy="none"`, `hook_seam`) -- machine-readable data nothing branches on,
  surfaced only in `forge runtime list`/`preflight` output. The probe harness lives under `scripts/experiments/`.
  - [x] `git mv docs/board/doing/runtime_abstraction docs/board/done/` -- **done after the #23 squash-merge to `main`**
    (board-contract: move only once merged; matches how Phases 2-5 stayed in `doing/` on-branch).

**Phase 6 complete (2026-06-09) -- the card is fully executed (Phases 0-6).** Merged via #23 (squash) and moved to
`done/`; the card is closed.

## Open Decisions

Tracks Forge-local execution decisions for this checklist. For broader card questions, see
[`card.md` Open Questions](./card.md#open-questions).

- [x] Phase 6 scope. **Resolved 2026-06-09: evaluation only.** Four decisions taken together: (1) Phase 6 ships no
  product features -- a probe harness, fixtures, a go/no-go decision record, and a follow-up build card are the
  deliverables, and the decision record completes the card; (2) the evaluation covers the **broader hook set**
  (PreToolUse + PermissionRequest + Stop + UserPromptSubmit), answering the card's "minimum Codex hook coverage" open
  question at the evaluation layer; (3) **SessionStart transfer delivery with initial-message fallback** is the build
  direction -- the probe must pin trust/`additionalContext` feasibility so the build card can implement it (or record
  "fallback stays primary" if trust is opaque); (4) **app-server transport is deferred, unevaluated** -- recorded in the
  decision record verbatim, not probed. Build work lands in `docs/board/proposed/codex_frontend/`.

- [x] Should Forge MITM the **interactive OAuth/subscription** session for wire observability (inspect /
  effort-override)? **Resolved 2026-06-07: deferred + double-gated, not forbidden.** The cost motivation is gone
  (`metric_evidence_simplification` makes Forge track only its own cost; `payer` stays separate), so MITM's only
  remaining justification is observability (April-2026 postmortem) -- which carries high, intrinsic account-safety/ToS
  cost. Gate to build: (a) a recurring harness-degradation incident AND (b) a feasibility spike (OAuth auths
  in-container; survives MITM incl. token refresh). NOT gated on "wait and see if Anthropic behaves." Full reasoning +
  mechanism + containment facts recorded in `card.md` ("OAuth interactive wire observability -- deferred decision"); the
  `card.md` Non-Goal was softened from "never" to "deferred/gated" to match. Cheap ToS-clean alternative spun out to
  `docs/board/proposed/harness_drift_canary/`. No execution tasks here until the gates clear.

- [x] Should `forge session resume --fresh --review` become default for curated transfer workflows? **Resolved
  2026-05-31: no -- keep `--review` opt-in.** A plain `--fresh` resume launches immediately; `--review` stays an
  explicit flag so non-interactive/scripted resume never blocks on `$EDITOR`. Curation is deliberate. Docs-only, no code
  change.

- [x] Which transfer-owned namespace should the resume-context commands use? **Resolved 2026-05-30: top-level
  `forge transfer ...`** (not `forge session transfer ...`), pairing with `forge memory`. Rationale and free/occupied
  verification are recorded in the Phase 1 namespace task above.

- [x] Should Phase 1 remain prose/schema-only, or should it change the default strategy after schema tests land?
  **Resolved 2026-05-31: prose/schema-only -- keep `structured` as the CLI default.** `ai-curated` stays opt-in via
  `--strategy ai-curated`, keeping the resume hot path deterministic, free, and LLM-free (matches design.md §3.9).
  Docs-only, no code change.

- [x] Where do proxy cost logs, audit logs, and the future usage ledger converge? **Resolved 2026-06-01: they do not
  physically converge -- three separate planes linked by a shared `request_id`.** `costs/requests/*.jsonl` stays the
  cap-enforcement spend log + bootstrap source; `audit/requests/*.jsonl` stays the privacy-sensitive wire record with
  its own retention; the new `usage/events/<month>_<pid>.jsonl` (PID-sharded) is the canonical attribution ledger
  ("which run/workflow/session invoked which runtime/provider/model via which route and consumed what"), referencing the
  other planes via **nullable** `source_refs` (`{cost_request_id, audit_request_id}`), not absorbing them. Join key
  verified to exist: the proxy generates one `request_id` per request (`server.py:1627`) and threads it into both the
  cost writer (`cost_logger.py:50`) and every audit writer (`audit_logger.py`). Denormalize `cost_micro_usd` into the
  event for greppability while keeping `source_refs` for provenance; native-runtime events (Codex/Gemini) carry units
  directly and leave `source_refs` null.

- [x] How should `FORGE_DEPTH` compose with future run-tree attribution ids? **Resolved 2026-06-01: run identity is
  authoritative; `FORGE_DEPTH` stays an additive integer guard, not reinterpreted.** New env
  `FORGE_RUN_ID`/`FORGE_PARENT_RUN_ID`/`FORGE_ROOT_RUN_ID` (root sets root to its own run_id; children inherit
  unchanged). `FORGE_DEPTH` keeps its `parent+1` computation at the single choke point (`env.py:130`); run tree and
  depth are **orthogonal** (no derivation to build), stamped together so they cannot drift. Do NOT reinterpret the
  integer -- three recursion guards depend on `>= 2` (`supervisor.py:393`, `team/handlers.py:180`,
  `review/engine.py:145`). Real Phase 4 task: audit that every spawn path (incl. review-engine fan-out, sidecar) stamps
  both at one site.

- [x] Proxied per-request correlation: how does the attribution id reach the proxy cost/audit plane for `claude -p`
  subprocess traffic, where **Forge is not the HTTP client** (Claude is)? **Resolved 2026-06-08 (Slice 4g): option (a)
  header propagation, joining by the run tree, not `source_refs`.** Claude Code forwards `ANTHROPIC_CUSTOM_HEADERS`
  (verified: `-p`, `--bare`, custom `ANTHROPIC_BASE_URL`; env vars survive `--bare`), so `build_claude_env` stamps
  `X-Forge-Run-ID`/`X-Forge-Root-Run-ID` and the proxy validates + records `forge_run_id`/`forge_root_run_id` on each
  cost record. Five review refinements shaped the final shape: **(1)** the join key is the **run tree**
  (`forge_root_run_id`), not single-valued `source_refs.cost_request_id` — one run makes many requests, so `source_refs`
  stays null and `test_bug_usage_claude_p_null_source_refs.py` holds (no `UsageEvent` schema change); **(2)** injection
  is gated on a **proven Forge proxy** (`target_is_forge_proxy(base_url)` OR marker `FORGE_SUBPROCESS_PROXY_ID` present
  **AND** `base_url == FORGE_SUBPROCESS_BASE_URL`), so an opaque/third-party `base_url` — including an inherited marker
  paired with an explicit opaque override — never leaks the header; **(3)** the two header names are **Forge-owned**
  (strip inherited `X-Forge-*` lines, re-stamp the current child's ids, preserve user lines); **(4)** the proxy
  **validates** the inbound ids (`^run_[0-9a-f]{12}$`, shared with `mint_run_id` via the dependency-free
  `forge.core.run_id` leaf) and stores `None` on a malformed/spoofed value — never persists a raw client header; **(5)**
  the correctness join is **read-time** (cost records flush in the proxy's stream-end callback *after* the client sees
  end-of-stream, so a write-time join at subprocess exit would miss the last record) — `forge activity`/`forge +$Y` sum
  cost records by `forge_root_run_id` and **suppress** every `verb_snapshot_estimated` aggregate when the root-join has
  records, killing the fan-out double-count by construction. A records-present/no-dollars route
  (`has_records && !has_cost`, e.g. Anthropic passthrough) suppresses the snapshot yet renders cost **unavailable**,
  never a fabricated `$0`. Orphan leaves (a cancelled worker that emitted no ledger event but still produced a cost
  record) are captured because the join is by root, not the ledger-derived run set. The deferred **OAuth-interactive
  MITM** tier is unrelated and stays deferred (resolved above): 4g touches only Forge's own headless subprocesses
  through Forge's own proxy with opaque non-secret run ids — ToS-clean, no credential extraction.

- [x] On-demand policy CLI runtime origin (4f follow-up, surfaced by review 2026-06-02): the manual `forge policy check`
  (`cli/policy.py` `check`, :519) and `forge policy supervisor` (`supervisor_cmd`, :693) leaf commands tag
  `ActionContext.runtime="claude_code"`, but their actual actor is a human at a terminal, not Claude (synthetic
  `session_name="on-demand"`, no session). 4f's contract is "which runtime *produced* the action" -- the file under
  review may be Claude's output, but that is the check's *subject*, not its *invoker*. **Inert today**: nothing reads
  `ActionContext.runtime` (`policy/types.py:57` is a plain `str`, no `Literal`/registry validation; the engine ignores
  it; it does not flow to the usage ledger, whose emit helpers take a separate `runtime` param), so no behavior is wrong
  yet. The `%policy check` path (`direct_commands.py:_handle_policy_check`, :1173) is **genuinely Claude-context** (a
  UserPromptSubmit `%`-command) and correctly stays `claude_code` -- only the two CLI leaves are the over-claim.

  - **Resolved 2026-06-09 (direction; execution gated on first consumer):** the field is the event's *origin* (the
    runtime that produced the action), not the subject under review. The manual CLI checks get a distinct origin --
    `forge_cli`, **not** `unknown` (the actor is known; reserve `unknown` for genuinely-undeterminable/lossy payloads).
  - **Rename `ActionContext.runtime` -> `origin`** when this lands, rather than overloading the name `runtime` with a
    widened domain. The latent footgun is the *name*: it invites a future `get_runtime(ctx.runtime)` bridge, which
    raises `ValueError` for any non-registry value (`core/runtime/registry.py:213`). A field named `origin` with values
    `{forge_cli, claude_code, codex, ...}` simply does not invite that lookup; `runtime` does.
  - **No `subject_runtime` axis (YAGNI, structural not just "not now"):** `PolicyEngine.evaluate` is runtime-agnostic by
    contract and policies match on **content** (`new_content`/`raw_diff`), so the subject's runtime is never an
    evaluation input; the field's only purpose is attribution, and an attribution fact about *a check* is its invoker,
    not who authored the file. The split has no consumer on either side. (Prior art that validates the *origin* axis
    while bounding it to one field: the usage ledger already separates `UsageEvent.runtime` = which agent from `route` =
    invocation channel -- `core/usage/{ledger.py:111,vocabulary.py:23}`.)
  - **Doc nit to fix with the rename:** the `ActionContext.runtime` docstring claims it "flows into attribution," but it
    does not reach the ledger yet (the emit helpers take a separate `runtime` param) -- correct the docstring when the
    consumer lands.
  - **Trigger:** execute only when a consumer first reads the field (Phase 5/6). Pure churn before then -- the field is
    wired through 4 production constructors + ~45 test constructions with zero behavioral payoff today.
