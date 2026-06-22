# Checklist: forge codex command group

**Card**: [card.md](card.md) - **Branch**: `forge_codex_command_group` - **Lane**: doing

Executing the codex proposal as one card but sequenced per its **Type** note: ship `forge codex status` first, gate the
Responses transport on the Phase 2 probe, and keep `forge codex start --proxy` parked until the transport exists. Do not
build the launcher before the probe resolves.

## Current focus

Phase 1 - `forge codex status` (read-only; every building block already exists).

## Phase 1 - `forge codex status` (shippable now)

- [ ] New `forge codex` group in `src/forge/cli/codex.py`, registered in `src/forge/cli/main.py`. Group stays visible
  when `codex` is absent (diagnostic surface).
- [ ] `status` reports binary + version via `get_runtime("codex").detect()`. With `codex` absent, exits 0 and reports
  `installed: false`.
- [ ] Config-path inspection: default scope plus `--scope user|project|local` and `--all`.
- [ ] Tracking from `~/.forge/installed.json` (`codex_config_path`, `codex_commands`) when present.
- [ ] Managed-block presence via `read_codex_registration(...).block_present`.
- [ ] Event-aware registration pairs via `codex_registration_pairs(...)`
  (`SessionStart -> forge hook codex-session-start`, `PreToolUse -> forge hook codex-policy-check`).
- [ ] Static enrollment posture: `registered: yes/no/partial/wrong-event`, `enrollment: unverified by static read`,
  `verify: forge runtime preflight codex --verify-enrollment`. Never claims enrollment from a static read.

### Style-guide compliance (new guards merged in #46)

- [ ] **Single-leaf group.** Shipping only `status` makes `forge codex` a single-visible-leaf group, which trips
  `test_command_tree_invariants::test_no_single_leaf_groups`. Resolution: register `start` from the outset (the card's
  runtime-visibility table registers it unconditionally) so the group has two leaves; `start`'s preflight failure
  ("Responses-capable proxy required") is real behavior, not an error-only tombstone. Confirm this, do not allowlist
  `forge codex`.
- [ ] `status` exposes `--json` with dest `as_json` (read-leaf rule); errors route through
  `print_error`/`print_error_with_tip` (no hand-rolled `[red]Error:[/red]`); results to stdout, diagnostics to stderr.

### Acceptance tests (Phase 1)

| Test                                    | Fixture                   | Assertion                                                                            | Test File                            |
| --------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------ |
| Status works when Codex absent          | PATH excludes `codex`     | exits 0, `installed: false`                                                          | `tests/src/cli/test_codex_status.py` |
| Status reports managed block            | config has Forge markers  | shows config path, `block_present: true`, registered commands                        | same                                 |
| Status catches wrong-event registration | command under wrong event | reports wrong-event/partial, not `registered: yes`                                   | same                                 |
| Status does not claim enrollment        | managed block present     | enrollment unverified, points to `forge runtime preflight codex --verify-enrollment` | same                                 |
| Status supports JSON                    | any                       | stable JSON fields (binary, config path, block, pairs, tracking, verify cmd)         | same                                 |
| Group visible for diagnostics           | PATH excludes `codex`     | `forge --help` lists `codex`; `forge codex status` explains missing runtime          | `tests/integration/cli/test_help.py` |

## Phase 2 - Live-probe Codex proxy contract (hard go/no-go gate)

**Blocks Phases 3-4.** Pin how the installed Codex CLI accepts a Responses base URL (env/argv vs `config.toml`
`model_provider`). **Kill criterion**: if routing is reachable only by writing codex-owned `config.toml`, the `--proxy`
launcher is infeasible as designed -- stop, do not work around it. Document the exact contract in the card closeout.
(Card Slice 1.)

## Phase 3 - Responses proxy transport (gated on Phase 2)

From-scratch build: `/v1/responses` route + Responses\<->internal converters + SSE translation + advertised capability +
live `proxy_supported` posture. Not a config toggle; this is the epic-member work the Type note flags. (Card Slice 2.)

## Phase 4 - `forge codex start --proxy` launcher (blocked on Phases 2-3)

Sessionless proxy-backed TUI launch with full child-env scrub (session + run-tree + subprocess vars); no `.forge/`, no
`confirmed.codex`. Parked until the transport exists. (Card Slices 3-4.)

## Blockers / deferred

- Phase 2 probe is a hard gate: a config-only routing result kills the launcher design (Phases 3-4), not just delays it.
- `forge codex preset` is out of scope by design (`config.toml` is codex-owned and trust-frozen).

## Closeout

- [ ] Phase 1 merged; `forge codex status` in `docs/cli_reference.md` and relevant `docs/end-user/*`.
- [ ] `docs/design.md` updated if the codex CLI surface or ownership changes.
- [ ] Promote to `epic_forge_codex` once Phase 2 resolves and transport work activates (two or more live members).
- [ ] `change_log.md` entry at phase closeout; move `doing/ -> done/` when the card's live scope ships.
