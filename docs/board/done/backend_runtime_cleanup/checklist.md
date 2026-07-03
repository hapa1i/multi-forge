# Checklist -- Backend runtime cleanup (Step 2) + cli_style B1 backend-help fold-in

**Branch**: `feat/backend-runtime-cleanup` - **Card**: [`card.md`](card.md)

**Current focus**: Make local backend **runtime instances** first-class `stop` targets (by id, and `--all`), turn
`delete` into a config-only command, and keep `start` config-oriented -- then fold in the cli_style **B1** backend-help
pass (same PR, both edit `backend.py`). **Status: SHIPPED in PR #71; board closeout complete.**

**Guiding rules**: card [Proposal](card.md) + [Start/stop asymmetry](card.md); `coding_standards.md` §5
(research-preview clean break -- removed options rely on Click's native "No such option", named in the changelog);
`cli_style_guidelines.md` (tips via `forge.cli.output`, `Use --flag` / `Run '<cmd>'` forms, errors already route to
stderr after PR #70).

## Grounded base (verified on `main`, 2026-07-03 -- the card's line numbers predate PR #69/#70 and have drifted)

Scope is the single file `src/forge/cli/backend.py` (1067 lines) plus its test/doc surface. Current anchors:

| Symbol / site                     | Line (now) | Card said | Current behavior                                                                |
| --------------------------------- | ---------- | --------- | ------------------------------------------------------------------------------- |
| `backend()` group help + examples | `:58-67`   | `:58`     | example uses `create litellm` / `start litellm -p 4000` (`litellm` = adapter)   |
| `_source_record`                  | `:320`     | `:314`    | emits `"backend_id": source.id` **and** `"source_id": source.id` (`:329-330`)   |
| `_load_runtime_instances`         | `:356`     | --        | uses `store.list_backends()` -- which **prunes dead pids** (`registry.py:185`)  |
| `_resolve_lifecycle_operand`      | `:361`     | --        | source-or-adapter+`--port` -> `(adapter, port)`; used by **both** start & stop  |
| `_resolve_local_adapter_operand`  | `:381`     | --        | adapter/source -> adapter (create/delete)                                       |
| `_exit_click_error`               | `:404`     | --        | `print_error(error.message)` (stderr since #70) + `sys.exit(1)`; no console arg |
| `show_cmd`                        | `:629`     | `:623`    | arg `BACKEND_ID`; sole example `show litellm-4000` (an **instance**, `:638`)    |
| `test_auth_cmd`                   | `:748`     | `:736`    | arg `SOURCE_ID`; **no** leaf example; error already uses `err_console` (`:764`) |
| `start_cmd`                       | `:854`     | --        | arg `SOURCE_OR_ADAPTER` + `--port`; builds `f"{adapter}-{port}"` (`:874`)       |
| `_stop_instance(adapter, port)`   | `:892`     | --        | shared by delete; `manager.stop_backend(f"{adapter}-{port}")`                   |
| `stop_cmd`                        | `:905`     | --        | arg `SOURCE_OR_ADAPTER` + `--port`; single target, **no `--all`** -- rewrite    |
| `delete_cmd`                      | `:925`     | --        | arg `ADAPTER` + `--port` + `--yes`; `--port` stops instance -- rewrite          |
| `reconcile_cmd`                   | `:994`     | `:977`    | arg `SOURCE_ID`; `--request-id` help says `<source-id>` (`:1000`), no example   |

Registry/manager API (`src/forge/backend/`): `BackendInstance.backend_id` = runtime id `litellm-4000`
(`registry.py:66`), `.pid: int | None` (`:69`), `.adapter_type`. `BackendRegistryStore.read().backends` is the raw dict;
`list_backends()` prunes first (`:178`). `BackendManager.stop_backend(backend_id)` (`__init__.py:157`) raises
`ValueError` if absent, calls `adapter.stop(instance)` (**no-op when `pid is None`**), then pops the registry entry --
so a pidless entry is unregistered with **no** process killed already; the CLI only needs to report it.

**Precedent to mirror**: `proxy delete_cmd` (`cli/proxy.py:1098`) -- `nargs=-1` positional + `--all`/`-a` + `--yes`,
conflict guard (`:1122`), missing-target guard (`:1126`), empty-`--all` no-op (`:1135`), preview+confirm (`:1140`),
explicit dedupe `dict.fromkeys` (`:1149`), per-target `deleted`/`failed` loop that continues after failures and
re-raises `SystemExit` only when a single target (`:1154`).

## Phase 1 -- `stop` becomes runtime-instance-oriented (the core behavior)

- [x] Rewrite `stop_cmd` (`:905`) to `nargs=-1` targets + `--all`/`-a` + `--yes`/`-y` (mirror `proxy delete`): drop the
  single `source_or_adapter` arg and **remove `--port`**. **Assertion:** `stop litellm-4000` stops/unregisters that
  instance and leaves adapter config in place; `stop --help` shows no `--port`.
- [x] Add helper `_stop_runtime_instance(instance: BackendInstance)`: register `instance.adapter_type`
  (`manager.register_adapter(instance.adapter_type, get_adapter(instance.adapter_type))`) then
  `manager.stop_backend(instance.backend_id)` -- do **not** reconstruct the id from adapter/port (card
  [Implementation notes](card.md)). **Assertion:** stopping resolves the adapter from the registered instance, not from
  the operand string.
- [x] Explicit-target resolution order (per target): (1) present in `store.read().backends` -> stop it; (2a) a
  **local-lifecycle** source id (`source.local_lifecycle is not None`, e.g. `litellm-openai-local`) or an adapter ->
  reject with a runtime-id tip (`Use 'forge model backend list' to find the runtime instance id (e.g. litellm-4000).`),
  since stopping the source would hit the shared process; (2b) a **remote / no-lifecycle** source id (e.g. `openrouter`)
  -> keep the existing no-local-lifecycle message (`backend.py:364-367`); (3) unknown -> reject with the `list` tip.
  **Assertion:** `stop litellm-openai-local` exits non-zero with the runtime-id tip and stops **nothing** (never touches
  the shared `litellm-4000` backing sibling sources); `stop openrouter` exits non-zero with the no-local-lifecycle
  message and edits no registry entry.
- [x] `--all` reads `store.read().backends` **directly** (never `list_backends()` -- its prune side-effect would mutate
  the registry while merely building the preview; card + `registry.py:185`). Preview the target ids, prompt unless
  `--yes`, then stop each with per-target error reporting; continue after a failure. **Assertion:** `stop --all --yes`
  with two instances removes both, leaves both adapter configs intact, and prints a per-target result line.
- [x] Pidless (`pid is None`) entries under `--all`: unregister and report distinctly
  (`unregistered pidless instance '<id>'; no process was killed`). **Assertion:** `stop --all` over a `pid=None`
  instance exits **zero**, removes the entry, and prints the no-process-killed line (never attempts a port-based kill of
  an unknown-owner process in this MVP).
- [x] Guards: `stop <id> --all` -> exit non-zero (conflict); `stop` with no target and no `--all` -> exit non-zero with
  a `Run 'forge model backend list'` tip; empty registry `stop --all` -> "No runtime instances to stop." exit **zero**.
  **Assertion:** all three match the `proxy delete` shapes (`cli/proxy.py:1122,1126,1135`).
- [x] Bulk previews + prompts by default; single/multiple **explicit** stops keep the existing no-confirm behavior (only
  `--all` prompts). **Assertion:** `stop a b` stops both without a prompt; `stop --all` prompts unless `--yes`.

## Phase 2 -- `delete` becomes config-only (clean break: drop `--port`)

- [x] Rewrite `delete_cmd` (`:925`) to `(adapter, yes)` -- **remove `--port`**. **Assertion:**
  `delete litellm --port 4000` errors via Click "No such option" (exit 2); `delete --help` shows no `--port`.
- [x] Before `_resolve_local_adapter_operand`, reject a **runtime instance id** operand present in
  `store.read().backends` with a stop-focused tip
  (`Use 'forge model backend stop litellm-4000' to stop a runtime instance.`). **Assertion:** `delete litellm-4000`
  (that id in registry) exits non-zero with the `stop` tip, **not** "Unknown backend adapter/source".
- [x] Keep config deletion behavior: `delete <adapter>` still stops matching `f"{adapter}-*"` instances first, then
  removes the config dir (existing loop, `:977-991`). **Assertion:** `delete litellm --yes` still deletes the config and
  stops matching instances.
- [x] Remote boundary unchanged: `delete openrouter` keeps returning the intentional no-local-config message
  (`_resolve_local_adapter_operand`, `:387-390`); no registry edit. **Assertion:** exits with the remote message;
  registry untouched.

## Phase 3 -- `start` stays config-oriented (lock the asymmetry, do not add runtime-id parsing)

- [x] Leave `start_cmd` (`:854`) resolving via `_resolve_lifecycle_operand` (source id / adapter+`--port`).
  **Assertion:** `start litellm-4000` is still rejected (a runtime id is neither a source id nor an adapter) -- add a
  test locking this so a future editor does not "fix" the asymmetry.
- [x] Reflect the asymmetry in `start`/`stop` help one-liners: `start` = start a local **source/adapter config**; `stop`
  = stop a live **runtime instance** (they are different objects; local sources can share one process). **Assertion:**
  the two help strings name the distinct object each acts on.

## Phase 4 -- cli_style B1 backend-help fold-in (help-only; NO metavar rename)

> Scope guard: B1 here is the *help/definition* pass only. Do **not** rename the `SOURCE_ID` / `BACKEND_ID` / `ADAPTER`
> metavars on unchanged leaves (that's B1-table-row-1 + C2, staying in the `proposed/` index). The **one** metavar that
> legitimately changes is `stop`'s -- because its accepted id-space genuinely changed to runtime ids (Phase 1), not as a
> cosmetic unification.

- [x] Define the three id-spaces **once** in the `backend()` group help (`:58-67`): **source id** (`openrouter` -- an
  upstream endpoint/capacity unit shown by `forge model backend list`), **runtime instance id** (`litellm-4000` -- a
  running local process), **adapter** (`litellm` -- a local config type). **Assertion:** `forge model backend --help`
  defines all three id-spaces; each unchanged leaf metavar is then either explained by that definition or covered by a
  leaf example -- the metavars are **not** renamed here (see the scope guard).
- [x] Fix B1 trap 1 (group example teaches the wrong id): the group example uses `litellm` (an adapter) while
  `test-auth`/`reconcile` take a **source id** -- `test-auth litellm` fails. Add a source-id example to the group help
  and a leaf example to `test_auth_cmd` (`:759`, e.g. `test-auth openrouter`) and `reconcile_cmd`. **Assertion:** every
  example in `--help` is a *valid* invocation for the leaf that shows it.
- [x] Fix B1 trap 2 (`show`'s only example is an instance): add a **source** example to `show_cmd` (`:637-638`, e.g.
  `show openrouter`) alongside the existing `show litellm-4000`. **Assertion:** `show --help` shows one source + one
  instance example.
- [x] Clarify `reconcile` `--request-id` help (`:1000`): keep the `<source-id>` reference but say where to find them
  (`run 'forge model backend list' for source ids`). **Assertion:** the help names the discovery command. (The tip-form
  reword at `backend.py:1005` is **B2**, out of scope -- leave it.)
- [x] **B1 trap 3 -- source-row dual-key JSON (RESOLVED: keep both, document).** Two source-row emitters ship
  `{"backend_id": source.id, "source_id": source.id}` for one value: `_source_record` (`:329-330`) **and**
  `test_auth_cmd`'s payload (`:787-788`). Keep both keys -- `backend_id` is the telemetry-facing catalog id (downstream
  telemetry keys on it; `impl_notes.md` "Unified backend"), `source_id` is the same value for a source row and is `null`
  on the runtime-instance JSON (`show_cmd` `:686`). Add the same one-line "source-row JSON emitters" comment near
  **both** sites; **removing** `source_id` is a JSON-contract change = Batch C, out of this PR. **Assertion:** both
  sites carry the explaining comment; the JSON keys are unchanged.

## Phase 5 -- Tests (`tests/src/cli/test_backend_commands.py`, 605 lines)

- [x] Add the card's acceptance cases (table below). Use the existing registry-fixture pattern in that file; assert exit
  codes + registry state + tip text, not full output. **Grounded (2026-07-03):** the only existing `stop` coverage is
  the `["start", "stop"]` parametrization `test_remote_source_lifecycle_errors_before_registry_mutation` (`:277`) --
  `stop openrouter` -> "no local lifecycle", registry `{}`; the rewrite's bucket 2b preserves that, so it already covers
  the "Stop remote boundary" row and stays green. Everything else is net-new. **Assertion:** new cases green; that
  parametrization still passes unchanged.
- [x] Clean-break guards: `stop litellm --port 4000` and `delete litellm --port 4000` both exit 2 (Click "No such
  option"). **Assertion:** both asserted.
- [x] Obsolete-test check (`coding_standards.md` §5): the first pass missed
  `tests/regression/test_bug_backend_delete_double_stop.py`, which still patched removed `_stop_instance` and drove
  removed `delete --port`; per `coding_standards.md` §5 it was deleted. **Assertion:** stop/delete `--port` mentions are
  clean-break exit-2 guards, help-negative assertions, historical board notes, or unchanged `start ... --port` cases.

## Phase 6 -- Docs sync + changelog

- [x] `docs/cli_reference.md` "Model management" table: update the `backend stop` row (stop a **runtime instance** by
  id; `--all`) and `backend delete` row (**config-only**; `--port` removed); confirm the `backend start` row still reads
  source/adapter. **Assertion:** the three rows match shipped help.
- [x] `docs/design_appendix.md` §A.2.1 (the `forge model backend` operator-view paragraph): update the "`start` and
  `stop` accept local source ids or legacy adapter operands" sentence to the new split -- `stop` takes runtime instance
  ids + `--all`; `start` stays source/adapter; `delete` is config-only. **Assertion:** the paragraph names the
  start/stop asymmetry and the `--port` removal.
- [x] `docs/end-user/proxy.md`: add a short "flush suspect local backend processes" note (`stop --all` after a
  credential change), paralleling the `proxy delete --all` guidance. **Assertion:** the operator recovery path is
  documented.
- [x] `docs/board/change_log.md`: feature-completion entry (Goal / Key changes / Verification) at closeout, naming the
  clean breaks (`stop`/`delete` `--port` removed) and the B1 fold-in. **Assertion:** entry present, newest-first.

## Acceptance tests

| Test                         | Fixture                                | Assertion                                                          | Test File                                |
| ---------------------------- | -------------------------------------- | ------------------------------------------------------------------ | ---------------------------------------- |
| Stop by runtime id           | registry has `litellm-4000`            | stops/unregisters it; adapter config remains                       | `tests/src/cli/test_backend_commands.py` |
| Stop multiple runtime ids    | registry has two instances             | both attempted; failures reported per target; no prompt            | `tests/src/cli/test_backend_commands.py` |
| Stop all                     | registry has two instances             | `stop --all --yes` removes both; configs intact                    | `tests/src/cli/test_backend_commands.py` |
| Stop all includes pidless    | registry has a `pid=None` instance     | unregisters it; "no process killed" line; exit 0                   | `tests/src/cli/test_backend_commands.py` |
| Empty all                    | empty registry                         | `stop --all` prints no-target message; exit 0                      | `tests/src/cli/test_backend_commands.py` |
| Conflict guard               | `stop litellm-4000 --all`              | exit non-zero                                                      | `tests/src/cli/test_backend_commands.py` |
| Missing-target guard         | `stop` (no target, no `--all`)         | exit non-zero + `forge model backend list` tip                     | `tests/src/cli/test_backend_commands.py` |
| Stop rejects local source    | `stop litellm-openai-local`            | exit non-zero + runtime-id tip; stops nothing                      | `tests/src/cli/test_backend_commands.py` |
| Stop rejects bare adapter    | `stop litellm` (no `--port`)           | body runs; exit non-zero + runtime-id/list tip; registry untouched | `tests/src/cli/test_backend_commands.py` |
| Stop remote boundary         | `stop openrouter`                      | intentional no-local-lifecycle message; no registry edit           | `tests/src/cli/test_backend_commands.py` |
| Stop `--port` clean break    | `stop litellm --port 4000`             | exit 2 (Click "No such option")                                    | `tests/src/cli/test_backend_commands.py` |
| Start stays config-oriented  | `start litellm-4000`                   | still rejected; start uses source ids / adapter config             | `tests/src/cli/test_backend_commands.py` |
| Delete runtime-id precedence | `delete litellm-4000` (id in registry) | exit non-zero + `stop litellm-4000` tip (not "Unknown ...")        | `tests/src/cli/test_backend_commands.py` |
| Delete `--port` clean break  | `delete litellm --port 4000`           | exit 2 (Click "No such option")                                    | `tests/src/cli/test_backend_commands.py` |
| Delete config spelling       | `delete litellm --yes`                 | deletes config; stops matching instances first                     | `tests/src/cli/test_backend_commands.py` |
| Delete remote boundary       | `delete openrouter`                    | intentional no-local-config message; no registry edit              | `tests/src/cli/test_backend_commands.py` |
| B1 help: id-spaces defined   | `backend --help`                       | source id / runtime instance id / adapter all defined              | help-render assertion                    |
| B1 help: valid examples      | `test-auth --help`, `show --help`      | each example is a valid invocation (source vs instance)            | help-render assertion                    |

## Blockers / decisions

- **Resolved (maintainer, 2026-07-03) -- B1 trap 3 (source-row dual keys).** Keep both `backend_id` + `source_id`;
  document the split at **both** emitters (`_source_record` + `test_auth_cmd`); defer removal to Batch C (Phase 4 last
  item). Rationale: `impl_notes.md` "Unified backend" pins `backend_id` as the telemetry catalog id, and the
  runtime-instance JSON already carries `source_id: None` -- removing the key is a contract change.
- **Open question (card, deferred):** an `--unhealthy` filter for `stop`. MVP is `--all` only (operator case = "flush
  local runtime state"), not fault classification. Out of scope; leave the open question in the card.
- **Out of scope (stays in `doing/cli_style_ux_compliance` index):** the B1 metavar *standardization* (row 1) + C2
  rename; B2 tip-form/`--json`-wording; B3/B4/B5. Only B1's id-space definition + 3 traps fold in here.

## Closeout items

- [x] All phases ticked with verification recorded.
- [x] Focused suite `uv run pytest tests/src/cli/test_backend_commands.py -q` green; `make test-regression` green;
  `make test-unit` green; `make pre-commit` clean.
- [x] Integration: none expected (host CLI + registry file; no `claude -p`/Docker path). Confirm and record if that
  holds.
- [x] `change_log.md` entry added (feature-completion size).
- [x] Docs synced: `cli_reference.md`, `design_appendix.md` §A.2.1, `end-user/proxy.md`.
- [x] cli_style index annotated: **B1 shipped** (strike the group-help rows folded here); note the remaining B1 metavar
  \+ B2-B5 rows stay in `proposed/`. Point the index's next cursor at **Step 3** (resume cli_style A2/A4/A5, B2-B5, C).
- [x] Card moved `doing/ -> done/` after merge to `main` (with this checklist alongside).
