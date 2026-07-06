# Checklist: forge_hook_matcher_consolidation

**Card**: [card.md](card.md) · **Branch**: `refactor/hook-matcher-consolidation` · **PR**: #87

**Status**: **shipped to `main` and closed 2026-07-06.** D1/D2 resolved below; historical checklist retained with the
verification that shipped the card.

**Current focus**: Lock the hook-command byte contract with a characterization golden, then collapse the two divergent
detection matchers into one shared predicate. Byte-preserving and behavior-preserving for real Forge registrations;
contains-only false positives are intentionally tightened. Pre-epic prep for
[`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md) Seam 1; enables the update branch of
[`forge_hook_legacy_writer`](../forge_hook_legacy_writer/card.md) (T9).

---

## Decisions owed (reviewer, before I start)

- [x] **D1 -- predicate semantics = invocation token (resolved 2026-07-06).** NOT plain/token substring:
  `"forge hook " in cmd` would remove a user hook like `echo forge hook stop` that today's prefix matcher preserves -- a
  silent delete on a *destructive* settings path (reviewer's Medium finding). The predicate matches a `forge hook ...`
  **invocation**: `forge` as the command token (bare **or** a path basename `.../forge`) immediately followed by `hook`.
  - **Target (recommended):** `shlex.split(cmd.strip())`, then length-guard before indexing:
    `len(tokens) >= 2 and Path(tokens[0]).name == "forge" and tokens[1] == "hook"`; optional `handler == tokens[2]`
    requires `len(tokens) >= 3`. Empty/single-token commands and malformed `shlex` (`ValueError`) -> `False`. Chosen
    over the interim string rule (`startswith("forge hook ") or "/forge hook " in stripped`) because it also gets
    quoted/space-in-path commands right (e.g. `"/opt/my tools/forge" hook stop`).
  - Matches: bare `forge hook stop`, `/abs/forge hook stop`. Rejects: `echo forge hook stop`, `myforge hook stop`, and
    -- for now -- the `forge-hook` dispatcher shim (that hyphen form is **T5**'s later extension of this one predicate).
  - Mandatory: an explicit false-positive test that `echo forge hook stop` is **not** matched, on both the presence and
    removal paths.
- [x] **D2 -- Phase 2 stays IN (resolved 2026-07-06, contingent on D1).** Because D1 is the invocation-token predicate,
  `forge hook disable` preserves today's removal set for contains-only entries, so converging `_is_forge_hook_entry`
  onto the shared predicate at today's bytes is safe. (Had D1 stayed loose substring, Phase 2 would be scoped out and
  the destructive matcher left entirely to T9.) The writer's keep/update/delete fate still stays **T9**.

---

## Phase 0 -- Characterization safety net (write BEFORE touching any matcher)

Locks current behavior so the refactor is provably byte-preserving ("characterize before aligning", impl_notes).

- [x] Add `tests/src/install/test_registered_commands_contract.py`.
  - [x] Pin all **16** rendered hook entries from `get_builtin_preset()["hooks"]` keyed on the **(event_key, matcher,
    command, timeout)** tuple. Assertion: the Write (`preset.py:79-87`) and Edit (`preset.py:89-97`) `policy-check`
    entries appear as **two distinct rows**; each entry's timeout (5/60/10/30/…) is pinned, not dropped.
  - [x] Pin the statusLine command (`forge status-line`, `preset.py:218-222`).
  - [x] Cover the Codex managed-block command line(s) (`codex_hooks.py:84`) -- either pin them here or assert the
    existing trust-byte golden (`test_codex_hooks.py:71`) already covers them. No second sanitizer.
  - [x] `merge_hooks -> unmerge` round-trip. Assertion: after `merge_hooks` then `unmerge`, the Forge-owned hook keys
    return **byte-identical** to the pre-install settings, and a non-Forge sibling entry under a shared event key is
    untouched.
  - [x] Assertion: the whole file is **green on current `main` code** before any matcher change (this is the baseline).
    Verified before matcher edits with `uv run pytest tests/src/install/test_registered_commands_contract.py -q` (4
    passed).

## Phase 1 -- Extract the single predicate

- [x] Add `is_forge_hook_command(command: str, handler: str | None = None) -> bool` (+ entry-level
  `entry_is_forge_hook(entry, handler=None)`) in `install/hooks.py` (dependency-light home). D1 invocation-token
  semantics: `forge` bare-or-basename + `hook`; length-guard before token indexing; `handler` matches the 3rd token;
  empty/single-token/malformed `shlex` -> `False`.
- [x] Repoint `has_forge_hook` to the shared predicate and expose `handler: str | None = None` directly: default
  `handler=None` matches any Forge hook; `handler="policy-check"` requires that handler.
  - Assertion: all **5** `has_forge_hook` callers return today's booleans on real settings -- `session_manage.py:1075`,
    `search.py:160`, `session.py:232`, `session_lifecycle.py:253`; and `policy.py:323`'s specific-handler check still
    discriminates present vs absent.
  - Assertion (presence tightening is intentional): a contains-only string (`echo forge hook stop`) that today's
    substring **falsely** matched now returns `False`. Audit existing `test_hooks.py` for any assertion that depended on
    the old false positive and update it with a recorded rationale (no real settings file contains such an entry).
  - Assertion: Phase 0 golden still green (proves no registered-entry byte change).

## Phase 2 -- Converge the second writer's matcher (D2: in scope)

- [x] Repoint `cli/hooks/install.py::_is_forge_hook_entry` to the shared predicate; delete its bespoke prefix body.
  - **Primary regression (reviewer's Medium finding):** over a mixed fixture (bare `forge hook <name>`, nested, a
    non-forge entry, **and** a contains-only `echo forge hook stop`), `forge hook disable` removes the real Forge
    entries and **preserves** `echo forge hook stop` -- byte-identical to today's prefix-matcher removal set. This is
    the guard that D1's invocation-token semantics keep the destructive path safe.
  - Assertion: removal set over the mixed fixture is byte-identical to pre-change behavior.

## Phase 3 -- Verify + close

- [x] Focused suites green: `tests/src/install/test_hooks.py`, `tests/src/install/test_registered_commands_contract.py`,
  `tests/src/cli/test_hooks.py`, `tests/regression/test_bug_hook_registry_drift.py`.
- [x] `make test-unit` green (no unrelated breakage).
- [x] Integration (installer/detection path, per testing_guidelines):
  `./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py`.
- [x] Scoped pre-commit clean on this card's changed files (ruff/black/isort/mypy/pyright/mdformat).
- [x] Design-doc sync: confirm no design doc documents matcher internals (expected: none -- matchers are internal);
  record "no design-doc change" or update.
- [x] Changelog entry (`docs/board/change_log.md`): Goal / Key changes / Verification.
- [x] Candidate `impl_notes.md` promotion (after human review): "one hook-command predicate in `install/hooks.py`; the
  registered-entry golden keys on (event, matcher, command, timeout) tuples, **not** a set of command strings -- a
  set-of-strings snapshot has lower cardinality than the 16 real entries and is blind to timeout/matcher drift."
- [x] Move card `doing/ -> done/` after merge to `main`.

## Acceptance tests

| Test                               | Fixture                                                                                                   | Assertion                                                                                                         | Test File                                                |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| Registered-entry golden            | rendered preset + statusLine + Codex block                                                                | 16 hook entries as (event, matcher, command, timeout) tuples; Write/Edit `policy-check` distinct; timeouts pinned | `tests/src/install/test_registered_commands_contract.py` |
| Merge -> unmerge round-trip        | settings pre-install, `merge_hooks`, then `unmerge`                                                       | Forge keys byte-identical to pre-install; non-Forge siblings untouched                                            | `tests/src/install/test_registered_commands_contract.py` |
| Invocation-token predicate         | `forge hook stop`, `/abs/forge hook stop`, `echo forge hook stop`, `myforge hook stop`, `forge-hook stop` | first two match; `echo`/`myforge` contains-only and the `forge-hook` shim do NOT (shim is T5's later extension)   | `tests/src/install/test_hooks.py`                        |
| One predicate, 5 callers unchanged | real settings with registered `forge hook <name>` entries                                                 | all 5 `has_forge_hook` sites return today's result via the shared predicate                                       | `tests/src/install/test_hooks.py`                        |
| Specific handler preserved         | PreToolUse with/without `forge hook policy-check`                                                         | `has_forge_hook(..., handler="policy-check")` still discriminates                                                 | `tests/src/install/test_hooks.py`                        |
| Disable preserves contains-only    | settings with `echo forge hook stop` + real Forge entries                                                 | `forge hook disable` removes the real entries, **preserves** `echo forge hook stop` (== today)                    | `tests/src/cli/test_hooks.py`                            |

## Blockers / deferred

- **D1/D2 resolved and implemented** (invocation-token predicate; Phase 2 in scope).
- The second writer's ultimate keep/update/delete is **T9** (`forge_hook_legacy_writer`), not this card. This card only
  provides the shared predicate and pins the byte contract.

## Closeout

Implemented 2026-07-06 on `refactor/hook-matcher-consolidation`. Verification completed:

- `uv run pytest tests/src/install/test_hooks.py tests/src/install/test_registered_commands_contract.py tests/src/cli/test_hooks.py tests/regression/test_bug_hook_registry_drift.py -q`
  -- 79 passed.
- `make test-unit` -- 7421 passed, 116 deselected.
- `./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py` -- 16 passed.
- `uv run pre-commit run --files ...` over this card's changed code/tests/docs -- clean after hook-applied formatting.

Design/end-user doc sync: no matcher internals are documented in `docs/design.md`, `docs/design_appendix.md`, or
`docs/end-user`; `docs/end-user/hook.md` only documents the public `forge hook disable` surface and needed no change.

Post-merge board closeout: moved this card to `done/` and removed the stale `proposed/` duplicate left by the local
planning commit. Verification: `make pre-commit-md`.
