# reject_rewind_transfer_strategy -- rewind is not a transfer-context strategy

**Lane**: `doing/` -- bug fix in flight (PR against `main`). Moves to `done/` after merge.

**Origin**: review of the uncommitted follow-up to `107b9251` (rewind resume, #66), 2026-07-02.

**Type**: single bug fix + its single-source-of-truth consolidation. Not an epic; no execution plan needed.

**References**: `src/forge/session/transfer.py` (`ResumeStrategy`, `assemble_transfer_context`);
`src/forge/core/ops/{codex_session,codex_interactive,codex_bridge,transfer}.py`;
`src/forge/cli/{session_codex,transfer}.py`; `docs/cli_reference.md:50` (rewind is Claude-only).

---

## Problem

`107b9251` added `ResumeStrategy.REWIND`. The codex/transfer ops validated an incoming `strategy` against
`{s.value for s in ResumeStrategy}`, which now *includes* `rewind` -- so the front door accepted `strategy="rewind"`
even though `assemble_transfer_context` rejects it. Rewind is a Claude-only launch path
(`--strategy rewind --drop-last N`), not a context-assembly strategy; it has no meaning for a codex/transfer session.

Blast radius was latent (the codex CLI `--strategy` `Choice` already excluded rewind), so only a programmatic caller
could trigger it -- but when triggered, rewind slipped past the fail-fast guard and paid the ~20s `codex doctor`
preflight plus a session create/rollback before failing, with a message that pointed at a Claude-only flag.

## Fix (shipped in this branch)

- Single source of truth in `session/transfer.py`: `TRANSFER_CONTEXT_STRATEGIES` / `TRANSFER_CONTEXT_STRATEGY_VALUES`
  (the four assembly strategies: minimal, structured, full, ai-curated) + `parse_transfer_context_strategy()`.
- All four codex/transfer ops validate through that parser; both transfer-facing CLI `Choice` lists (`session transfer`,
  `session start --runtime codex`) source from the constant. `assemble_transfer_context` now rejects any non-transfer
  strategy (not just `REWIND`) with one uniform message -- a strictly better backstop.
- Rejection fires at the front door, before the codex-doctor preflight and session creation.

**Deliberately untouched**: the `manager.py` / `cli/session.py` transfer-mode branches (the resume/fork CLIs dispatch
rewind to its dedicated launch path before those branches see it; their `assemble` backstop still fires) and the
`session_fork` / `session_lifecycle` `Choice` lists (they carry the rewind-inclusive *superset* -- fork/resume
legitimately support rewind, so they cannot source from the transfer-only constant).

## Acceptance

| Assertion                                                             | Verification                                                                                             |
| --------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `strategy="rewind"` rejected before session creation at each codex op | `test_codex_session.py::test_unknown_strategy_rejected_before_creation[rewind]` + bridge/interactive kin |
| `assemble_transfer_context` rejects rewind with the uniform message   | `test_transfer.py::test_rewind_strategy_is_not_a_transfer_context_strategy`                              |
| Codex CLI `--strategy` choices track the constant (no hardcoded copy) | `TRANSFER_CONTEXT_STRATEGY_VALUES` sourced in `session_codex.py`; 253 codex/transfer/session_codex green |

**Verification**: 253 unit tests green (codex ops + transfer + session_codex); `make pre-commit` hooks clean on all
touched files (mypy, pyright, isort, ruff, black).

## Closeout

- **Merged** via PR #68 (`016e9d0a`), 2026-07-02. Moved `doing/ -> done/`; `change_log.md` entry added (2026-07-02).
