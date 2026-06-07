# Remove CLI rename-migration tombstones (clean break at 0.4.0)

Branch: `feat/remove-tombstones` (stacked on `feat/metric-evidence-simplification` / PR #18 — depends on its renames).

## Problem

Solo research-preview fork at `0.4.0`; no external users. The CLI carries rename-migration **tombstones** — hidden,
error-only stubs whose only job is to print "renamed to X" pointers. They were most valuable right after each rename;
now they're clutter. Remove them for a pristine CLI.

## Scope (decided with the user)

Three buckets wear the same `hidden=True` hat; only two are removed:

- **Bucket 2 — command/flag rename tombstones (REMOVE).**
- **Bucket 3a — config/memory migration guards for stale on-disk state (REMOVE).** Safe because the maintainer wipes
  `~/.forge/` state routinely, so there is no stale config/passport data to protect.
- **Bucket 3b — `cost_logger`/`audit_logger` `schema_version` validators (KEEP).** Not tombstones: they guard against
  **newer-than-current** data (forward-compat), are mandated by the durable-state contract, and "cleaning state" does
  not apply.
- **Live machine-facing hidden commands (KEEP):** `status-line`, `hook`, `memory-writer` group + internal options.

### Verified exclusion

- **`forge session context` — NOT removed.** Verified it is a *functional* deprecated command (`--field`/`--json`
  extraction), not an error-only stub. Removing working behavior is a separate, deliberate decision; out of scope here.

## Items removed

Bucket 2:

- `forge usage` (`activity.py` `usage_tombstone`) + reg in `main.py`.
- `forge handoff run` (`memory_writer.py` `handoff_tombstone`/`_tombstone_run`) + reg in `main.py`.
- `forge session handoff` group (`session_handoff.py`, whole file) + reg in `session.py`.
- `forge session memory` group (`session_memory.py`, whole file) + reg in `session.py`.
- `forge search -q`/`--limit` legacy flags (`search.py`).
- `forge memory track --as`/`--session` flags + removed-strategy CLI hint (`memory.py`).
- `--force` "Deprecated alias for --yes" in 8 commands (`auth`, `proxy` ×2, `backend`, `config_cmd`, `claude`,
  `extensions`).
- `--resume-mode handoff` rejection (`session_lifecycle.py`).

Bucket 3a:

- Config-key migration: `_RENAMED_KEYS`/`_REMOVED_KEYS` (`runtime_config.py`) + lookups + `_prune_renamed_keys`
  (`config_cmd.py`).
- Memory removed-strategy: `_REMOVED_STRATEGIES` (`passport.py`) + 3 validation sites + `scan_stale_passports`
  (`project_memory.py`) + the `memory list` stale-warning (`memory.py`). Degrades cleanly to the existing "unknown
  strategy" check.

## Follow-through (in this PR)

- Delete obsolete tests (whole files: `test_session_memory.py`, `test_session_context.py` — wait, context excluded, so
  keep its tests; just the tombstone tests) and tombstone test classes/methods.
- QA: delete `7-costs.md` §7.14 (`forge usage` rename probe); fix `11-config.md` `--force` → `--yes`.
- Policy docs: rewrite `coding-standards.md` §1 "Helpful failure" (scope it to durable-state/reset paths, drop the
  command-tombstone allowance) and §6 "Removed shortcuts are tombstones" → clean-break, no command tombstones. Keep the
  durable-state rejection requirement (that protects 3b).
- `change_log.md` entry.

## Risks

- Missing a registration site → broken CLI or dangling import (every reg mapped in the inventory).
- Memory-strategy removal touches `passport.py` validation (core) → rely on full test suite.
