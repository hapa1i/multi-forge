# Close CLI Enforcement and Recovery Gaps

**Lane**: `doing/`

**Epic**: [`1.0 Release Hardening`](../epic_1_0_release_hardening/card.md)

## Goal

Restore per-file policy enforcement for Git-quoted paths and make recovery guidance target the state that actually
failed.

## Scope

- Parse C-quoted Git diff headers without dropping or merging files (#4).
- Bind local Codex disable recovery to the explicit enable root rather than the caller's current directory (#9).
- Render persisted-proxy restart and explicit reroute recovery for durable model-route replay failures (#14).

## Constraints

- Preserve unquoted, deleted, renamed, and non-UTF-8 Git path behavior.
- Recovery commands must be executable for the exact target and must not weaken fail-closed routing.
- Keep policy hook adapters on their existing input path; only the terminal diff splitter changes.
