# Checklist — Remove CLI rename-migration tombstones

Branch: `feat/remove-tombstones` (stacked on PR #18). Clean break at `0.4.0`; no compatibility shims.

## Current focus

Closeout: all source + test + doc changes landed and verified; ready for `make pre-commit`, commit, push, PR.

## Phase 1 — Bucket 2: command/flag rename tombstones (REMOVE)

- [x] `forge usage` removed (`activity.py` `usage_tombstone` + `main.py` registration).
- [x] `forge handoff run` removed (`memory_writer.py` `handoff_tombstone`/`_tombstone_run` + `main.py`).
- [x] `forge session handoff` group deleted (`session_handoff.py` whole file + `session.py` `_register_subgroups`).
- [x] `forge session memory` group deleted (`session_memory.py` whole file + `session.py`).
- [x] `forge search -q`/`--limit`/`--scope` legacy flags removed (`search.py`); unused imports dropped.
- [x] `forge memory track --as`/`--session` flags + removed-strategy hint removed (`memory.py`).
- [x] `--force` "Deprecated alias for --yes" removed from `auth`, `backend`, `config_cmd`, `claude`, `extensions`
  (disable), `proxy delete`, `proxy template reset`. Functional `--force` kept on `proxy stop`,
  `extensions enable/sync`, `session delete`, `session resume`, `hooks enable`.
- [x] `--resume-mode handoff` rejection removed (`session_lifecycle.py`); native/transfer validation kept.

## Phase 2 — Bucket 3a: stale-state migration guards (REMOVE)

- [x] Config-key migration removed: `_RENAMED_KEYS`/`_REMOVED_KEYS` (`runtime_config.py`) + `_prune_renamed_keys` and
  set/reset rejection blocks (`config_cmd.py`). Unknown keys now fall through to the generic "Unknown keys (ignored)"
  warning — no silent degradation.
- [x] Memory removed-strategy guards removed: `_REMOVED_STRATEGIES` + 3 validation sites (`passport.py`),
  `scan_stale_passports` (`project_memory.py`), `memory list` stale-warning loops (`memory.py`). Degrades to the
  existing `VALID_STRATEGY_NAMES` rejection.

## Phase 3 — Bucket 3b: schema_version validators (KEEP — verified untouched)

- [x] `cost_logger`/`audit_logger` `schema_version` forward-compat validators left intact (mandated by durable-state
  contract; guard newer-than-current data, not stale data).

## Phase 4 — Tests

- [x] Deleted whole files: `test_session_memory.py`.
- [x] Deleted tombstone tests/classes across `test_activity.py`, `test_memory_writer_cli.py`, `test_memory_report.py`,
  `test_search.py`, `test_memory.py`, `test_passport.py`, `test_project_memory.py`, `test_config_cli.py`,
  `test_runtime_config.py`, `test_session_commands.py`.
- [x] Migrated `proxy delete`/`proxy template reset` `--force` → `--yes` (and `--yes --kill-adopted` where the adopted
  kill path is asserted) across `test_proxy_commands.py`; renamed `*_force_*`/`*_without_force` test methods.
- [x] Dropped now-unused `from forge.cli.main import main` imports (`test_activity.py`, `test_memory_writer_cli.py`).

| Test                                        | Fixture                                             | Assertion                                        | Test File                              |
| ------------------------------------------- | --------------------------------------------------- | ------------------------------------------------ | -------------------------------------- |
| Unknown config key warns generically        | `handoff_timeout`/`show_rate_limits` in config.yaml | hits "Unknown keys" path (no targeted tombstone) | `tests/src/test_runtime_config.py`     |
| Removed strategy rejected                   | passport with `strategy: debugging`                 | `PassportError` via `VALID_STRATEGY_NAMES`       | `tests/src/session/test_passport.py`   |
| `proxy delete --yes` skips prompt           | registry entry, no TTY                              | exit 0, "Deleted"                                | `tests/src/cli/test_proxy_commands.py` |
| `proxy delete adopted --yes --kill-adopted` | adopted entry (pid=None)                            | registry entry removed, kill path reached        | `tests/src/cli/test_proxy_commands.py` |

**Verification**: `uv run pytest -m "not integration" tests/src tests/regression` → 5681 passed, 0 failed.

## Phase 5 — Docs

- [x] QA: removed `7-costs.md` §7.14 (`forge usage` rename probe); renumbered reset section 7.15 → 7.14; index
  `checklist.md` test-count 537 → 535 + "Last updated" note. Fixed `11-config.md` `claude preset reset --force` →
  `--yes`. Migrated `4-proxy.md` teardown `proxy delete --force` → `--yes` (16 sites).
- [x] Policy: rewrote `coding-standards.md` §5 "Helpful failure" → split into clean-break-for-commands +
  actionable-failure-for-durable-state; §6 "Removed shortcuts are tombstones" → "clean breaks". Updated `design.md` §4.0
  command-shape policy to clean-break.
- [x] `change_log.md` entry added.

## Closeout

- [x] `make pre-commit` clean.
- [x] Relevant integration tests pass — `test_proxy_commands_integration.py` (27) + `test_backend_cli.py` (8) green
  against the real CLI subprocess (`proxy delete --yes`/`--yes --kill-adopted`, `backend delete --yes`).
- [x] Commit + push `feat/remove-tombstones`; PR #19 opened, stacked on #18 (`feat/metric-evidence-simplification`).
- [ ] Move card `doing/` → `done/` after #19 merges to `main`.
