# Project compatibility mutator sweep

**Origin**: standalone follow-up split from the T7 [`forge_project_compat`](../../done/forge_project_compat/card.md)
closeout. **Reclassified 2026-07-11: not a member of
[`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md)** and does not hold the epic open -- the
sweep touches none of the epic's five seams and has no sequencing dependence on its members (precedent: the
consumer_lanes epic re-filed its team-supervisor follow-on as a standalone card).

**Lane**: `done/`. Shipped via PR #98 (`aa45114d`) and closed on `main` 2026-07-12. The execution record is preserved in
[`checklist.md`](checklist.md).

## Goal

Finish the `.forge/project.toml` enforcement coverage that T7 deliberately left visible: every remaining project-state
mutator either observes the compatibility guardrail or records a narrow exemption with rationale.

## Background

T7 `forge_project_compat` shipped the file reader, fail-open hook helper, extension lifecycle guards, shared session
repo-root guards, and doctor surfacing. Its first slice explicitly left three families for this follow-up:

- hook confirmed-state writes
- memory-writer doc writes
- proxy/backend registry mutations

The execution audit then found additional unguarded paths behind those families: cross-CWD target stores, direct `%`
mutations, search and memory commands, multi-root cleanup, startup queue drains, shadow workers, managed worktree
creation, `fork --into`, WorktreeCreate, and global index self-healing. The checklist classifies each rather than
treating T7's initial list as exhaustive.

The helper `check_project_compatibility_for_hook()` now has its first production caller through the named invocation
diagnostic seam used by lifecycle and Codex project-write hooks. Keep that helper paired with its caller rather than
letting contract-only code drift across releases.

## Design Rules

- Reuse `src/forge/install/project_compat.py`; do not reparse `.forge/project.toml` at call sites.
- Refusal paths use `enforce_project_compatibility()` (or explicitly reject a strict result with `compatible=False`);
  `try/except` around `check_project_compatibility()` alone is not enforcement.
- Preserve T7's strict/lenient posture: missing file is compatible/unconstrained; malformed, unreadable, unsupported, or
  incompatible state fails clear on command/operator mutation paths; session/context hook paths fail open with a
  degraded diagnostic.
- Check the Forge root that owns the target state, not merely the caller's CWD. Explicit multi-root commands may
  partially succeed, but must report refused roots and exit nonzero; background work refuses without changing foreground
  exit.
- Fresh managed worktrees keep the source precheck and add a target postcheck before target-local state/install writes;
  refusal rolls back the checkout and branch. Stale `--worktree --force` replacement checks both the existing target and
  the exact replacement commit before destroying anything, creates from that pinned commit, then retains the post-create
  defense. Derived global session/active-index self-healing is narrowly exempt, while paired index writes remain behind
  the owning project mutation's guard.
- Prefer small named guard points over sprinkling checks across leaf mutators. If a family is not actually project-local
  state, document the exemption in the checklist and design docs if user-facing behavior depends on it.
- Do not add `.forge/project.toml` authoring or implicit worktree copying. v1 remains hand-edit only, and a missing pin
  in a new checkout remains unconstrained.
- `forge_dev_runtime_override` bypass decision -- **resolved by T8 (2026-07-11): T8 adds no special bypass.** A
  `FORGE_DEV`-resolved forge keeps the existing compatibility posture unchanged. This sweep now routes lifecycle and
  Codex project-write hooks through a named invocation diagnostic that delegates to
  `check_project_compatibility_for_hook`; strict command enforcement remains separate.

## Acceptance Tests

| Test                         | Fixture                                                       | Assertion                                                                                          | Test File                                                                                      |
| ---------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| Hook fail-open               | incompatible/malformed pin; lifecycle and Codex write paths   | write proceeds; one debug diagnostic; stdout/stderr/JSON contracts unchanged                       | `tests/src/cli/hooks/test_project_compat_hooks.py` + existing Codex hook suites                |
| Direct command fail-closed   | incompatible target; `%policy`/supervisor/cancel mutations    | `decision:block`; no store mutation                                                                | `tests/src/cli/test_user_prompt_dispatcher.py`                                                 |
| Target-root enforcement      | caller and target roots with opposite pin states              | the target state owner's pin alone controls refusal                                                | session/policy/transfer/memory/search CLI suites                                               |
| Background refusal           | incompatible memory writer/index/shadow target                | no project write; foreground JSON/stderr unchanged; outcome/queue records refusal                  | `test_memory_writer_cli.py`, `test_startup_queue.py`, `test_queue.py`, `test_policy_shadow.py` |
| Multi-root partial result    | compatible + incompatible delete/cleanup/GC roots             | compatible targets mutate; refused targets remain and are reported; explicit command exits nonzero | session cleanup/delete and GC unit/integration suites                                          |
| `fork --into` atomic refusal | nested target Forge root with proxy-producing flags           | no proxy, child/index/transfer, target replacement, or orphaned state                              | `tests/src/cli/test_session_fork.py` + `tests/integration/docker/test_project_identity.py`     |
| Managed worktree posture     | fresh mismatch; stale target/future HEAD/branch refusal       | fresh target rolls back; stale checkout/branch/dirty state survives every preflight refusal        | session manager, fork-into, and lifecycle suites                                               |
| WorktreeCreate posture       | incompatible source or tracked target pin                     | source refusal creates nothing; target refusal rolls back; ignored pin is never copied             | `tests/src/cli/hooks/test_new_hooks.py`                                                        |
| Proxy/backend exemption      | incompatible CWD pin near global registry mutation            | proxy and backend writes succeed because `~/.forge` has no project owner                           | `tests/src/cli/test_proxy_commands.py` + `tests/src/cli/test_backend_commands.py`              |
| Global self-heal exemption   | filtered read; stale global index row belongs to another root | proven-stale derived row prunes without touching project files or a refused live mutation          | session index + active-store suites                                                            |
| Helper has caller            | production tree after Phase 1                                 | lenient helper is reached through the named hook diagnostic seam                                   | hook compatibility + install compatibility tests                                               |
