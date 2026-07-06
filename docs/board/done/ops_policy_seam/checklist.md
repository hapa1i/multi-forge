# Checklist: ops_policy_seam (Seam A)

Execution plan for the policy `core/ops` seam. See `card.md` for the thesis and target shape.

**Type**: behavior-preserving refactor + one small defect fix (A2 proxy-id-recovery posture). Two slices, both shippable
as their own PRs.

**Branch**: split from `refactor/ops-seam-completion` (the board-split branch). Implementation branch:
`refactor/ops-policy-seam` (cut when A1 starts).

---

## Current focus

**Closed 2026-07-06.** A1 and A2 shipped together on `refactor/ops-policy-seam`; the sibling `proxy_tier_resolvers`
remains independent work.

### Recorded review decisions (2026-07-06)

- **Q1 SPLIT** — this card = Seam A (A1+A2); sibling `proxy_tier_resolvers` = Seam B. No epic.
- **Q3 recovery-helper home = `proxy/proxies.py`** beside `find_by_base_url`, **not** `core/ops/proxy.py`. Verified:
  `core/ops/proxy.py:1` is command-core for user-facing `forge proxy`/`%proxy`; the recovery helper serves session
  launch/context/hooks (a lower layer). Keep `find_by_base_url` fail-loud as the primitive (it does `self.read()`, which
  propagates registry corruption — callers like `%proxy show` want that loud); add a **separate** best-effort wrapper
  that catches, logs at debug, returns `None`. Do not bury the try/except in the primitive.
- **Q4 A2.3/A2.4 stay in A2** — contract hygiene on the same seam; no separate A3.
- **Second review (2026-07-06): include `supervisor_cascade`.** Cascade is a duplicated supervisor mutation too
  (`cli/policy.py:1488` `@supervisor.command("cascade")`; `%direct` at `direct_commands.py:938`), so A1 covers
  set/off/on/remove/reload/**cascade** — not just the first five.
- **Second review: coupling note corrected.** The earlier `ln`-module-alias claim was an artifact of a malformed
  `rg -r ln` (replace) flag — no `ln` alias exists. Real coupling is fully-qualified
  `monkeypatch.setattr("forge.cli.policy.…")`; see Pre-flight.

---

## Pre-flight findings (verified 2026-07-06 against `main` @ `052a37c0`)

- **A2 defect confirmed.** Proxy-id-recovery error posture has drifted across 4 copies: `claude_session.py:1205`
  (sidecar) `except Exception: pass` (silent); `session_start.py:335` (hook) `except Exception: pass  # Fail-open`
  (silent); `claude_session.py:1389` (host) `logger.debug(...)` (logged); `session_context.py:484` `_log.debug(...)`
  (logged). Converge to logged fail-open (coding_standards §5).
- **A1 mutation set = {set, off, on, remove, reload, cascade}.** Cascade (`cli/policy.py:1488`, `%direct`
  `direct_commands.py:938`) was missing from the first draft — now in scope.
- **A1 coupling is fully-qualified `monkeypatch.setattr("forge.cli.policy.<symbol>")`**, not
  `patch("forge.cli.policy.…")` strings (0 of those): e.g. `test_policy_supervisor.py:773,789,1134`,
  `test_policy_shadow.py:56,63,66`; `cli/hooks/direct_commands.py` has **no** fully-qualified monkeypatch sites. If A1
  relocates a symbol patched at `forge.cli.policy.<symbol>`, keep it referenced there or repoint the `setattr`. A1.0
  enumerates the set.
- **`core/ops/policy.py` does not exist yet** — A1 creates it.

---

## Slice A1 — `core/ops/policy.py` supervisor lifecycle

- [x] **A1.0 Enumerate real blast radius + confirm the mutation set.** Confirm the duplicated supervisor mutations are
  exactly {set, off, on, remove, reload, cascade} across both surfaces (none missed — `status`/`evaluate` are
  read/one-shot, out of scope). Grep fully-qualified `monkeypatch.setattr("forge.cli.policy.…")` (e.g.
  `test_policy_supervisor.py:773/789/1134`, `test_policy_shadow.py:56/63/66`) and any on
  `forge.cli.hooks.direct_commands` (currently none). Assertion: a written list of the mutation ops + every patched
  symbol in a moved path + whether it stays importable at `forge.cli.policy` or the test is repointed.
- [x] **A1.1 Create `core/ops/policy.py`** with `supervisor_{set,off,on,remove,reload,cascade}(...)` returning
  structured results + typed errors (cascade's eager plan-resolution failure is a typed error the CLI/`%` responder
  renders — no `sys.exit`/print in the op). Assertion:
  `rg -n "click|rich|sys\.exit|print\(" src/forge/core/ops/policy.py` empty (test-guarded).
- [x] **A1.2 Repoint `cli/policy.py`** supervisor leaves (incl. `cascade` `:1488`) to delegate; CLI keeps all rendering
  \+ exit codes (incl. cascade's exit-1-when-no-plan).
- [x] **A1.3 Repoint `%direct` `_handle_policy_supervisor` (`direct_commands.py:753`, cascade branch `:938`)** to the
  same op; the `%` responder keeps block/allow JSON.
- [x] **A1.4 Behavior parity across all six verbs.** Same manifest mutation and same `%direct` JSON before/after for
  set/off/on/remove/reload/cascade (row A1-a).

**Exit signal:** every supervisor mutation lives once; both surfaces delegate; no Click/print in the op.

## Slice A2 — routing-override + one-posture proxy-id recovery + contract fixes

- [x] **A2.1 `recover_proxy_id_from_base_url(...)` — best-effort wrapper in `proxy/proxies.py`** beside
  `find_by_base_url` (Q3). Posture: return `None` + `logger.debug(..., exc_info=True)` on failure. Repoint all 4 sites
  (`claude_session.py:1205`, `:1389`; `session_context.py:476`; `session_start.py:335`). **Do not change
  `find_by_base_url`'s fail-loud primitive posture.** Assertion: **regression test** proves the wrapper logs (caplog) +
  returns None when the registry raises, while `find_by_base_url` still propagates the error.
- [x] **A2.2 Routing-override / effective-proxy helpers live in ops only.** Collapse `claude_session.py:909` (+
  routing-override) vs `cli/session.py` twins; CLI imports the op. Assertion: no local routing-override/effective- proxy
  helper in `cli/session.py`.
- [x] **A2.3 `list_sessions_older_than(ctx, scope)` matches its sibling contract** so `cli/session_manage.py:437` stops
  importing op-private `_scope_filters`. Assertion: `rg "_scope_filters" src/forge/cli/` empty.
- [x] **A2.4 `ActiveSessionStore.is_live` public** so `core/ops/gc.py:424` uses the public method. Assertion:
  `rg "_entry_is_live" src/forge/core/ops/gc.py` empty.

**Exit signal:** CLI imports no op-private symbol; proxy-id recovery has one logging posture.

---

## Acceptance test table

| Test                                                                                      | Fixture                                                                                               | Assertion                                                                                                                                                                                                                                                                                                                             | Test File                                                                                 |
| ----------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| A1-a: both surfaces delegate (parametrized: set target, off, on, remove, reload, cascade) | session state per verb (configured supervisor where the verb needs one; approved plan for cascade-on) | for set, `forge policy supervisor set <target>` and `%policy supervisor <target>` produce identical manifest state; for off/on/remove/reload/cascade, both surfaces produce identical manifest state via the matching `core.ops.policy.supervisor_*` op; `%direct` block/allow JSON preserved; add/keep a direct bare-target set test | `tests/src/cli/test_policy_supervisor.py`, `tests/src/cli/test_user_prompt_dispatcher.py` |
| A1-b: op is UI-free                                                                       | n/a (static)                                                                                          | `core/ops/policy.py` contains no `click` / `rich` / `sys.exit` / `print(`                                                                                                                                                                                                                                                             | new `tests/src/core/ops/test_policy_ops.py`                                               |
| A2-a: wrapper logs, primitive stays loud                                                  | `ProxyRegistryStore.read()` raises                                                                    | `recover_proxy_id_from_base_url` returns `None` + emits a `DEBUG` record (caplog); `find_by_base_url` still raises                                                                                                                                                                                                                    | new `tests/regression/test_bug_proxy_id_recovery_error_posture.py`                        |
| A2-b: no op-private import                                                                | n/a (static)                                                                                          | `rg "_scope_filters" src/forge/cli/` and `rg "_entry_is_live" src/forge/core/ops/gc.py` both empty                                                                                                                                                                                                                                    | `tests/src/cli/test_session_start_delete.py`, gc test                                     |

---

## Design-doc / memory sync

- [x] Note `core/ops/policy.py` as the supervisor-lifecycle op home in `design.md` §3.12; verify §3.5 ownership wording
  still holds (hooks write `confirmed`; ops are UI-agnostic).
- [x] **impl_notes candidate (human-review gate):** proxy-id recovery has one logged fail-open wrapper in `proxies.py`;
  `find_by_base_url` stays fail-loud — do not reintroduce a bare `except: pass` copy or merge the two postures.

## Closeout

- [x] A1-a/b + A2-a/b green; focused suites pass:
  `uv run pytest tests/src/core/ops/test_policy_ops.py tests/src/cli/test_policy_supervisor.py tests/src/cli/test_user_prompt_dispatcher.py tests/src/core/ops/test_session_ops.py tests/src/core/ops/test_gc.py tests/src/cli/test_session_start_delete.py tests/src/cli/test_session_fork.py tests/src/cli/test_session_list_show.py tests/src/cli/test_session_resume_review.py tests/regression/test_bug_proxy_id_recovery_error_posture.py -q`
  (390 passed);
  `uv run pytest tests/src/session/hooks/test_session_start.py tests/src/proxy/test_proxies.py tests/regression/test_bug_proxy_id_recovery_error_posture.py -q`
  (48 passed); `uv run pytest tests/src/cli/test_policy_shadow.py tests/src/cli/test_policy_supervisor.py -q` (90
  passed).
- [x] `make pre-commit` clean; touched-file `ruff`.
- [x] Integration run for the session-start recovery site (A2.1 touches `session_start.py`) —
  `./scripts/test-integration.sh` on the artifact/session-start path.
- [x] `change_log.md` entry per shipped slice.
- [x] Move card `doing/ → done/`.
