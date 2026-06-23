# Checklist: forge codex command group

**Card**: [card.md](card.md) - **Branch**: `forge_codex_command_group` - **Lane**: doing

Executing the codex proposal as one card but sequenced per its **Type** note: ship `forge codex status` first, gate the
Responses transport on the Phase 2 probe, and keep `forge codex start --proxy` parked until the transport exists. Do not
build the launcher before the probe resolves.

## Current focus

Phase 1 implementation complete and green (14 unit tests, mypy/pyright/ruff clean). Review-driven revision applied:
scope detection now mirrors `find_forge_installation` (not bare cwd), `--all` lists local, `registered_pairs` shows
Forge's footprint only, and `start` is removed (single-leaf `forge codex` allowlisted) rather than shipped as a
no-`--proxy` placeholder. Remaining: commit.

## Phase 1 - `forge codex status` (shippable now)

- [x] New `forge codex` group in `src/forge/cli/codex.py`, registered in `src/forge/cli/main.py`. Group stays visible
  when `codex` is absent (diagnostic surface). *(test_status_codex_absent_exits_zero,
  test_codex_group_registered_and_visible)*
- [x] `status` reports binary + version via `get_runtime("codex").detect()`. With `codex` absent, exits 0 and reports
  `installed: false`. *(test_status_codex_absent_exits_zero)*
- [x] Config-path inspection: default is the **detected** install scope via `find_forge_installation` (else user);
  `--scope user|project|local` and `--all` (lists local distinctly) widen it. Project/local roots resolve by walking up
  for `.git`/`.codex`, not bare cwd, so a subdir run still finds the per-project config + scope-keyed tracking.
  *(test_status_default_uses_detected_scope, test_status_default_is_user_when_no_install,
  test_status_all_includes_local_scope, test_status_project_scope_resolves_root_from_subdir)*
- [x] Tracking from `~/.forge/installed.json` (`codex_config_path`, `codex_commands`) when present.
  *(test_status_surfaces_installed_json_tracking)*
- [x] Managed-block presence via `read_codex_registration(...).block_present`. *(test_status_reports_managed_block)*
- [x] Event-aware registration pairs via `codex_registration_pairs(...)`, **filtered to Forge commands** so unrelated
  user hooks in the same config do not pollute the footprint (`SessionStart -> forge hook codex-session-start`,
  `PreToolUse -> forge hook codex-policy-check`). *(test_status_reports_managed_block, test_status_catches_wrong_event,
  test_status_filters_unrelated_hooks)*
- [x] Static enrollment posture: `registered: yes/no/partial/wrong-event`, `enrollment: unverified by static read`,
  `verify: forge runtime preflight codex --verify-enrollment`. Never claims enrollment from a static read.
  *(test_status_catches_wrong_event, test_status_does_not_claim_enrollment)*

### Style-guide compliance (new guards merged in #46)

- [x] **Single-leaf group (decision reversed).** The original plan registered a gated `start` so `forge codex` had two
  leaves. That doesn't survive review: a `start` with no `--proxy` that always errors *is* a tombstone-shaped
  placeholder, it contradicts the card (launcher = parked), and it would pin a `--proxy` contract the **Phase 2 kill
  criterion** may invalidate. Resolution: remove `start`; allowlist `forge codex` in `SINGLE_LEAF_GROUP_ALLOWLIST` as
  deliberate **phasing** debt (distinct from the flatten-style entries), to be removed when `start --proxy` ships in
  Phase 4. *(test_codex_group_registered_and_visible asserts `forge codex start` is "No such command".)*
- [x] `status` exposes `--json` with dest `as_json` (read-leaf rule). With `start` removed, the module has no
  hand-rolled error markup and no `print_error` call; `status`'s only error is Click's `UsageError` (already stderr), so
  the stdout/stderr split holds. **Deferred to Phase 4:** when `start` returns it must use a stderr `Console`.
- _Out-of-scope finding (flag, do not fix here):_ `forge.cli.output`'s fallback `console` is stdout (`output.py:22`), so
  the guide's "errors -> stderr" rule is violated project-wide by the shared helper (~18 files). Separate cleanup.

### Acceptance tests (Phase 1)

| Test                                     | Fixture                                   | Assertion                                                                            | Test File                            |
| ---------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------ |
| Status works when Codex absent           | runtime faked absent                      | exits 0, `installed: false`                                                          | `tests/src/cli/test_codex_status.py` |
| Status reports managed block             | config has Forge markers                  | shows config path, `block_present: true`, registered commands                        | same                                 |
| Status catches wrong-event registration  | command under wrong event                 | reports wrong-event/partial, not `registered: yes`                                   | same                                 |
| Status does not claim enrollment         | managed block present                     | enrollment unverified, points to `forge runtime preflight codex --verify-enrollment` | same                                 |
| Status supports JSON                     | any                                       | stable JSON fields (binary, config path, block, pairs, tracking, verify cmd)         | same                                 |
| Default uses detected scope              | `find_forge_installation` faked / raising | default shows detected scope, else falls back to user                                | same                                 |
| `--all` lists local distinctly           | any                                       | scopes == {user, project, local}                                                     | same                                 |
| Project scope resolves root from subdir  | `.git`+`.codex` at root, run from subdir  | finds root `.codex/config.toml` (`config_exists`/`block_present`)                    | same                                 |
| Registered pairs are Forge-only          | Forge block + unrelated hook              | unrelated command absent from `registered_pairs`; Forge command present              | same                                 |
| Group single-leaf; `start` not a command | runtime faked absent                      | `forge --help` lists `codex`; `forge codex start` is "No such command"               | same                                 |
| Tracking surfaced from installed.json    | seeded `installed.json`                   | `tracked_config_path` / `tracked_commands` populated in scope output                 | same                                 |

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

- [x] `forge codex status` documented in `docs/cli_reference.md` ("Codex management" section). End-user guide: no Day 1
  behavior change yet (read-only diagnostic; `start` still gated) -- revisit when the launcher ships.
- [ ] Phase 1 merged.
- [ ] `docs/design.md` updated if the codex CLI surface or ownership changes.
- [ ] Promote to `epic_forge_codex` once Phase 2 resolves and transport work activates (two or more live members).
- [ ] `change_log.md` entry at phase closeout; move `doing/ -> done/` when the card's live scope ships.
