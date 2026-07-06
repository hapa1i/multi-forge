# forge_hook_matcher_consolidation -- one hook-command matcher + a golden byte-contract, before the epic changes the bytes

**Lane**: `done/` -- shipped to `main` on 2026-07-06 via PR #87.

**Relationship**: **Pre-epic prep** for [`epic_global_forge_runtime`](../../proposed/epic_global_forge_runtime/card.md)
(its Seam 1 -- "all Forge-registered command strings + all three matchers"). Not an epic member: it is a
behavior-preserving consolidation that makes the epic *inherit* a locked contract instead of coordinating it across six
members. It enables the **update** branch of
[`forge_hook_legacy_writer`](../../proposed/forge_hook_legacy_writer/card.md) (T9) by providing the shared matcher that
writer would adopt, and it shrinks [`user_scope_hook_ownership`](../../proposed/user_scope_hook_ownership/card.md) (T5)
from "update three matchers in lockstep" to "update one predicate."

**Origin**: de-risking review (2026-07-06). The epic's hardest seam is byte-identity of registered hook commands across
two writers and two divergent matchers. This card front-loads that seam as an isolated, behavior-preserving change --
the same playbook as the shipped `diverged_twin_consolidation` and `test_mirror_and_contract_cleanup` cards
(single-source a duplicated primitive; characterize before aligning).

---

## Goal

1. Collapse the two divergent "is this a Forge hook command?" matchers into **one** shared predicate.
2. **Golden-pin** the full set of Forge-registered command strings + the merge -> unmerge round-trip **at today's
   bytes**, so every subsequent epic byte change is diffed against a locked contract instead of hoped to be consistent.

No command bytes change. No user-visible behavior changes. This is a safety net + a de-duplication.

## Why

The epic states byte-identity of registered hook commands **is the API**, and that detection must move in lockstep or it
lies. Today it does not move in lockstep -- there are two independently-authored matchers with different semantics:

- **Substring matcher (tracked, widely used).** `install/hooks.py::_entry_has_command` (`needle in cmd`), exposed via
  `has_forge_hook(worktree, hook_type, command_needle="forge hook")` (`:69`) and `has_forge_hooks` (`:103`). **Five
  read-only callers**: `session_manage.py:1075`, `search.py:160`, `session.py:232`, `session_lifecycle.py:253`, and
  `policy.py:323` (which passes the *specific* needle `"forge hook policy-check"`).
- **Prefix matcher (second writer only).** `cli/hooks/install.py::_is_forge_hook_entry`
  (`cmd.strip().startswith("forge hook ")`, `:139-164`), used only by `forge hook disable` to choose entries to remove.

They agree today only because **every registered command is bare `forge hook <name>`** -- substring and prefix both
match. They **stop agreeing the moment the epic rewrites the bytes**: an absolute path
`/abs/.../forge hook policy-check` still satisfies the substring but **breaks the prefix**; a `forge-hook` dispatcher
shim (hyphen) breaks **both**. That is precisely the epic's Seam-1 failure mode, and it is cheaper and safer to remove
the divergence *before* the byte change than to coordinate it across T2/T5/T6/T9.

Separately, the only existing byte-level guard pins **config equality**
(`FORGE_HOOK_CONFIG["hooks"] == get_builtin_preset()["hooks"]`, `test_bug_hook_registry_drift.py`). Nothing golden-pins
the **rendered registered entries** -- **16 Claude hook command entries across 13 event keys** (`PreToolUse` alone has
four: Read -> `read-hygiene`, ExitPlanMode -> `exit-plan-mode`, Write -> `policy-check`, Edit -> `policy-check`), the
`forge status-line` statusLine command, and the Codex managed block -- or the **merge -> unmerge round-trip** the epic's
"unmerge-before-merge" rule depends on. The two `policy-check` entries share one command string under different
matchers, so a set-of-strings snapshot would silently collapse them (and hide a matcher/timeout drift) -- the golden
must key on the full entry tuple.

## Target shape

1. **One predicate.** Extract a dependency-light
   `is_forge_hook_command(command: str, handler: str | None = None) -> bool` (plus an entry-level
   `entry_is_forge_hook(entry, handler=None)`) as the single home for "does this command invoke a Forge hook?".
   Canonical semantics = an **invocation token** match: `shlex.split(command.strip())`, length-guarded, with
   `Path(tokens[0]).name == "forge"` and `tokens[1] == "hook"`; an optional `handler` matches `tokens[2]`. This survives
   bare `forge hook ...` and absolute `/abs/.../forge hook ...` forms while rejecting contains-only strings such as
   `echo forge hook stop`. T5 later updates this **one** predicate for the dispatcher shim form. Repoint
   `has_forge_hook` to it with an explicit `handler=` argument. If T9 keeps the second writer, `_is_forge_hook_entry`
   calls it too (dropping the prefix divergence); if T9 deletes the writer, the prefix matcher simply vanishes -- either
   way the epic ends with one matcher.
2. **Byte-contract golden.** A characterization test that snapshots, at today's bytes:
   - all 16 rendered Claude hook entries keyed on the full **(event key, matcher, command, timeout)** tuple -- not a set
     of command strings, so the two `policy-check` entries (Write vs Edit) and per-entry timeouts cannot collapse,
   - the `forge status-line` statusLine command (`preset.py:218-222`),
   - the Codex managed-block command line(s) (`codex_hooks.py:84`; complements the existing trust-byte golden at
     `test_codex_hooks.py:71`),
   - a `merge_hooks -> unmerge` round-trip that returns the settings to their pre-install Forge-owned state.

## Scope

**In:**

- Extract + adopt the single shared predicate; delete the substring helper and (if the writer is kept)
  `_is_forge_hook_entry`'s bespoke prefix body in favor of it.
- Add the registered-string + round-trip golden characterization test at current bytes.
- Keep all five `has_forge_hook` callers behaviorally identical for real Forge registrations (the `policy.py`
  specific-handler call uses `handler="policy-check"`). Contains-only false positives such as `echo forge hook stop` are
  intentionally tightened to `False`.

**Out:**

- Any command-byte change (absolute path, dispatcher form) -- that is T2/T5, which this card only makes safer.
- The second writer's fate (keep/update/delete) -- **T9 owns it**; this card only offers it the shared matcher.
- The post-cutover detection *update* for the new command form -- **T5 owns it**, now against one predicate.
- `projects.toml`, sidecar resolution, statusLine scope -- unrelated epic members.

## Grounding (verified 2026-07-06)

- Two divergent matchers: substring `install/hooks.py:55-66` (`_entry_has_command`) / `:69` (`has_forge_hook`) / `:103`
  (`has_forge_hooks`); prefix `cli/hooks/install.py:139-164` (`_is_forge_hook_entry`, `:152`).
- Substring-matcher callers (all read-only presence checks): `session_manage.py:1075`, `search.py:160`,
  `session.py:232`, `session_lifecycle.py:253`, `policy.py:323` (needle `"forge hook policy-check"`).
- Merge/unmerge the round-trip must pin: `settings_merge.py:505` (`merge_hooks`), `:731` (`unmerge` by `stable_id`);
  source-only load `installer.py:817`.
- Registered entries to pin: `preset.py:47-217` (`get_builtin_preset()["hooks"]` -- 16 command entries across 13 event
  keys; `PreToolUse` `:58-98` holds 4, incl. Write `:79-87` and Edit `:89-97` both rendering `policy-check` with
  distinct matchers/timeouts), `preset.py:218-222` (statusLine `forge status-line`), `codex_hooks.py:84` (managed
  block).
- Existing guard pins config equality only, not rendered strings/round-trip:
  `tests/regression/test_bug_hook_registry_drift.py`.

## Risks

- **Predicate semantics drift.** Substring vs prefix differ for future byte forms and for destructive cleanup. The
  invocation-token predicate is the deliberate middle path: it survives the absolute-path form, preserves today's
  disable removal set for contains-only entries, and gives T5 one predicate to extend for the dispatcher shim.
- **Golden brittleness.** Snapshotting rendered entries can turn every intentional command change into a failing golden.
  That is the point pre-epic (the change must be conscious), but the test must be trivially re-baseline-able and name
  the epic member that will legitimately churn it.
- **Low, but non-zero, coupling to T9.** If T9 lands first and deletes the writer, this card's matcher work is smaller
  (only the substring survivor + golden). Land whichever first; the other adapts. No hard ordering.

## Open questions

- Predicate home: reuse `install/hooks.py` (already the tracked, dependency-light matcher module) vs a new `core`-level
  leaf. Prefer `install/hooks.py` unless a non-install caller needs it.
- Does the golden live as one regression file (`test_registered_commands_contract.py`) or extend the existing
  `test_bug_hook_registry_drift.py`? Prefer a new, clearly-named contract test; leave the drift regression focused.

## Acceptance tests

| Test                                                                     | Fixture                                                                                                   | Assertion                                                                                                                                                                | Test File                                                |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| Invocation-token predicate                                               | `forge hook stop`, `/abs/forge hook stop`, `echo forge hook stop`, `myforge hook stop`, `forge-hook stop` | first two match; contains-only and dispatcher-shim forms do not yet match                                                                                                | `tests/src/install/test_hooks.py`                        |
| One predicate, five callers unchanged                                    | real settings with registered `forge hook <name>` entries                                                 | all five `has_forge_hook` call sites return today's result via the shared predicate                                                                                      | `tests/src/install/test_hooks.py`                        |
| Specific handler preserved                                               | `PreToolUse` with `forge hook policy-check` present + absent                                              | `has_forge_hook(..., handler="policy-check")` still discriminates                                                                                                        | `tests/src/install/test_hooks.py`                        |
| Registered-entry golden                                                  | rendered preset + statusLine + Codex block                                                                | all 16 hook entries pinned as `(event, matcher, command, timeout)` tuples (Write/Edit `policy-check` stay distinct) + statusLine + Codex block match the frozen baseline | `tests/src/install/test_registered_commands_contract.py` |
| Merge -> unmerge round-trip                                              | settings pre-install, then `merge_hooks`, then `unmerge`                                                  | Forge-owned keys return to pre-install bytes; non-Forge settings untouched                                                                                               | `tests/src/install/test_registered_commands_contract.py` |
| Second-writer matcher shares the predicate (only if T9 keeps the writer) | `forge hook disable` over mixed entries including `echo forge hook stop`                                  | removal decision comes from `is_forge_hook_command`, prefix body deleted, contains-only entry preserved                                                                  | `tests/src/cli/test_hooks.py`                            |

## Sequencing

Pre-epic. No dependency on any epic member; both epic byte-change tracks (T2 incident, T3->T6 model) start from the
locked contract this card creates. Pairs loosely with T9 (shared matcher) -- land either first.

## Closeout

Implemented 2026-07-06 on `refactor/hook-matcher-consolidation`; merged via PR #87 and closed on `main`.

- Shared predicate: `install/hooks.py::is_forge_hook_command` and `entry_is_forge_hook` now own Forge hook-command
  detection. `has_forge_hook(..., handler=...)` calls the shared entry helper directly; `forge hook disable` calls the
  same helper with `require_command_type=True`.
- Contract golden: `tests/src/install/test_registered_commands_contract.py` pins the 16 rendered Claude hook rows as
  `(event, matcher, command, timeout)`, the statusLine command, Codex hook commands, and `merge_hooks -> unmerge`
  sibling preservation.
- Behavior: real registered `forge hook <name>` entries keep today's results; contains-only strings like
  `echo forge hook stop` are intentionally tightened to `False` and preserved by the destructive disable path.

Verification: focused hook/contract/regression suite (79 passed); `make test-unit` (7421 passed, 116 deselected);
`./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py` (16 passed); scoped pre-commit on this
card's changed files clean. No design/end-user doc update was needed because matcher internals are not documented.
Post-merge board closeout moved the card to `done/` and removed the stale proposed duplicate. Verification:
`make pre-commit-md`.
