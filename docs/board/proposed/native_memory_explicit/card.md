# native_memory_explicit -- record and control native memory posture on managed session launches

**Epic**: [epic_native_multiagent](../epic_native_multiagent/card.md) (M8a -- main-session launch posture).

**Lane**: `proposed/`. No functional dependencies on source capture, curation or review. Coordinate shared launcher
edits with M0/M9; native-memory import is [M8b](../native_memory_import/card.md). Worker-only memory-off belongs to
[M0](../worker_native_controls/card.md).

## Problem (verified 2026-09-06)

- `docs/design_memory.md` §6.4 deliberately excludes native memory from Forge's memory writer, but managed launch
  construction does not assert that native memory is disabled.
- Native configuration varies with user/project settings, runtime home and worktree relationship. A maintainer's
  settings do not establish a managed-launch contract.
- `confirmed.launch` is a frozen original snapshot. It cannot describe current per-resume posture, and `allowed` cannot
  establish that memory was enabled or used. Legacy/external runs have no trustworthy recorded assertion.
- Interactive Codex argv in `src/forge/session/codex_invoke.py` bypasses headless `prepare_codex_request`. Claude roots
  finalize env in `src/forge/session/claude/invoke.py`, and sidecars receive explicit environment files. A change in one
  shared helper does not cover every launch.

[Claude memory controls](https://code.claude.com/docs/en/memory) and the
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) supply launch controls.
This card records what Forge emits, not historical or continuous native-memory use.

## Design

- **Intent:** runtime config `native_memory: off|allow`, default off, with `--native-memory off|allow` on supported
  managed start/resume/fork paths. Persist explicit session choice. Derivations inherit an explicit parent choice unless
  overridden; otherwise resolve the current global default. Resume re-resolves and records the source.
- **Off:** Claude emits `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`; Codex emits
  `-c memories.use_memories=false -c memories.generate_memories=false`. Apply at final env/argv construction for exec,
  interactive, deferred and sidecar launches without rewriting user-owned native config.
- **Allow:** omit Forge's disabling overrides, preserving user/native settings even if those keep memory disabled. Do
  not force either feature on. M0's worker profile remains off independently of main-session choice.
- **Facts:** add CLI-owned `confirmed.native_memory` for the latest dispatched managed run: run id, runtime, timestamp,
  requested/effective setting and source, emitted controls, and posture `asserted_off|allowed|unknown`. Keep per-run
  launch/usage evidence. Failed pre-dispatch attempts are not successful launch facts; legacy/external runs are unknown.
  Frozen original launch fields remain unchanged.
- **Surfaces:** `session show` and `transfer show` report the last recorded posture and timestamp. Native mid-session
  changes and prior memory-generation eligibility require separate evidence.
- **Import seam:** preserve the parent's launch/configuration context needed for later source resolution, including
  effective native home and relevant directory configuration when known. This card does not scan memory directories,
  read their contents or assert that a configured directory was used; unknown source context remains explicit.

No child receipts, identity classifier, review artifact or curation model is needed to establish these launch facts.
Compose with worker and delegation controls without resetting their settings.

## Acceptance

| Test                  | Fixture and assertion                                                                                             | Test file                                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Claude posture        | Off overrides inherited enablement; allow preserves user/native choice; root choice cannot relax worker profile   | `tests/src/core/reactive/test_env.py`                                                                                   |
| Codex path parity     | Exec and interactive start/resume emit both overrides and retain delegation configuration                         | `tests/src/core/invoker/test_codex_invoker.py`, `tests/src/session/test_codex_invoke.py`                                |
| Per-run facts         | Repeated launches refresh posture without mutating frozen launch; unknown/allowed never display as observed on    | `tests/src/core/ops/test_codex_session.py`, `tests/src/cli/test_session_activity_summary.py`                            |
| Inheritance           | Explicit parent choice, child/resume override and global fallback resolve with recorded source                    | `tests/src/cli/test_session_derivation.py`                                                                              |
| Root/sidecar coverage | Final root env and sidecar environment preserve emitted controls and parent configuration context                 | `tests/src/sidecar/test_container.py`, `tests/src/session/test_codex_invoke.py`                                         |
| Runtime assertion     | Clean-install Claude/Codex exec and interactive probes verify emitted controls, including no-.env credential path | Extend `tests/integration/cli/test_artifact_hooks_integration.py`, `tests/integration/core/test_codex_session_start.py` |

## Design-doc sync

`docs/design_memory.md` §6.4; `docs/design_sessions.md` §3.3 and runtime launch sections (per-run posture, inheritance
and preserved source context); `docs/end-user/memory.md`, `docs/end-user/session.md`, `docs/end-user/transfer.md` and
`docs/cli_reference.md`. Import behavior is documented when M8b ships.
