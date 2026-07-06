# ops_policy_seam -- complete the core/ops split for the policy surface

**Lane**: `done/` -- split from the `ops_seam_completion` batch (2026-07-06) per its own acceptance guidance (two member
cards, no epic). Sibling: [`proxy_tier_resolvers`](../../doing/proxy_tier_resolvers/card.md) (Seam B). They share a
theme, not a load-bearing contract, and ship independently.

**Type**: behavior-preserving refactor + one **small defect fix** (A2: converge the drifted proxy-id-recovery error
posture -- two copies silently swallow, two log -- to a single logged fail-open posture per coding_standards §5).

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`, area core-ops). The
routing-override / proxy-id-recovery twins were adversarially verified (auto-refuter SURVIVES); the policy `%direct`
supervisor duplication is auditor first-pass evidence with strong anchors (re-verify at A1).

**References**: `docs/design.md` §3.12 (command-core ops -- the normative pattern), §3.5 (ownership);
`docs/developer/cli_style_guidelines.md` (ops UI-agnostic; CLI owns rendering); archetype
`docs/board/done/session_op_layer_extraction/card.md`.

---

## Why

`design.md` §3.12 makes `core/ops/` the home for logic shared between `forge …` and `%…`; `session_op_layer_extraction`
proved the pattern. Two laggards never got mirrored to it:

- **Supervisor lifecycle duplicated.** The `%policy supervisor <target>`/off/on/remove/reload/**cascade** mutations in
  `cli/hooks/direct_commands.py` (`_handle_policy_supervisor:753`, cascade branch `:938`, bare-target set `:1026`)
  duplicate the same `SupervisorConfig` mutations in `cli/policy.py` (`set:1184`, off/on/remove/reload at
  `:1370/:1395/:1415/:1444`, `cascade` at `:1488`; degrade clears `:1340/:1430`) instead of both delegating to a
  `core/ops/policy.py` op -- the exact anti-pattern §3.12 exists to prevent.
- **Three ops-boundary leaks travel with it:** CLI/ops routing-override twins (`core/ops/claude_session.py:909` vs
  `cli/session.py`); proxy-id recovery copy-pasted 4× and **drifted on error posture** (see Defect); and two contract
  asymmetries -- `cli/session_manage.py:437` imports the op-private `_scope_filters`, and `core/ops/gc.py:424` reaches
  into `ActiveSessionStore._entry_is_live`.

## Surfaced defect (A2)

Proxy-id recovery from base_url exists 4× with **drifted** error handling (verified 2026-07-06):

- `core/ops/claude_session.py:1205` (sidecar) → `except Exception: pass` -- silent
- `session/hooks/session_start.py:335` (hook) → `except Exception: pass  # Fail-open` -- silent
- `core/ops/claude_session.py:1389` (host) → `logger.debug(...)` -- logged
- `core/ops/session_context.py:484` → `_log.debug(...)` -- logged

Converge to the **logged fail-open** posture (coding_standards §5: best-effort must log, never silent). Regression test
required (testing_guidelines Regression Test Mandate).

## Target shape

| Op (new/changed)                                                      | Replaces                                                                      |
| --------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `core/ops/policy.py::supervisor_{set,off,on,remove,reload,cascade}`   | direct_commands.py:753/938/1026 + cli/policy.py:1184/1370/1395/1415/1444/1488 |
| `resolve_effective_proxy` / routing-override in ops only              | claude_session.py:909 + cli/session.py twins                                  |
| `recover_proxy_id_from_base_url(...)` -- best-effort wrapper (see Q3) | claude_session.py:1205/1389; session_context.py:476; session_start.py:335     |
| `list_sessions_older_than(ctx, scope)` (match sibling contract)       | cli/session_manage.py:437 importing `_scope_filters`                          |
| `ActiveSessionStore.is_live` (public)                                 | gc.py:424 reaching `_entry_is_live`                                           |

**Q3 decision (recovery-helper home).** `proxy/proxies.py`, beside `find_by_base_url` -- **not** `core/ops/proxy.py`.
`core/ops/proxy.py:1` is command-core for user-facing `forge proxy`/`%proxy` operations; the recovery helper is
lower-level registry recovery used by session launch/context/hooks. Keep `find_by_base_url` fail-loud as the primitive
(it does `self.read()`, which propagates registry corruption -- callers like `%proxy show` want that loud); add a
**separate** best-effort wrapper that catches, logs at debug, returns `None`. Do not bury the try/except in the
primitive.

## Non-goals / must-not-break

- **No behavior change** except the A2 posture convergence, which only *adds* a debug log where two copies were silent.
  Same `%direct` block/allow JSON.
- **Rendering stays in the CLI.** `core/ops/policy.py` returns structured results + typed errors (cascade's eager
  plan-resolution failure is a typed error, not a `sys.exit`); `cli/policy.py` and the `%` responder own all printing /
  hook JSON.
- Ops import no `click`/`rich`/`sys.exit` (grep-guarded).

## Phased plan

| Slice | Scope                                                                                                                                           | Exit signal                                                                            |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| A1    | `core/ops/policy.py` supervisor lifecycle (set/off/on/remove/reload/cascade); repoint `cli/policy.py` + `%direct`.                              | every supervisor mutation lives once; both surfaces delegate; no Click/print in the op |
| A2    | Routing-override + `recover_proxy_id_from_base_url` (single logged posture, wrapper in proxies.py) + `_scope_filters`/`is_live` contract fixes. | CLI imports no op-private symbol; proxy-id recovery has one logging posture            |

## Blast radius

- `core/ops/policy.py` is new; `cli/policy.py` (1795 LOC) + `direct_commands.py` (1540 LOC) repoint.
- **Test coupling is fully-qualified `monkeypatch.setattr("forge.cli.policy.<symbol>")`**, not
  `patch("forge.cli.policy.…")` strings (0 of those): e.g. `test_policy_supervisor.py:773,789,1134`,
  `test_policy_shadow.py:56,63,66`. `cli/hooks/direct_commands.py` has **no** fully-qualified monkeypatch sites. If A1
  relocates a symbol a test patches at `forge.cli.policy.<symbol>`, keep it referenced/importable there or repoint the
  `setattr` target. A1.0 enumerates the set. (An earlier draft claimed an `ln` module alias -- that was a bad-grep
  artifact, `rg -r ln`; no `ln` alias exists.)

## Risks

- Ops must return structured data (no Click) or they violate §3.12 -- grep the new module.
- The A2 wrapper must not change `find_by_base_url`'s fail-loud primitive posture (Q3).

## Metric / falsifiable prediction

A supervisor-lifecycle change (including a cascade tweak) touches **1 op, not 2 command surfaces**; a proxy-id-recovery
fix lands **once**. Confirm on the next supervisor-UX PR.

## Closeout

Shipped 2026-07-06 on `refactor/ops-policy-seam`.

Verification:

- Focused unit/regression suites: 390 passed, 48 passed, and 90 passed across policy ops/supervisor, `%direct`,
  session/gc contract, proxy recovery, session-start hook, and policy-shadow coupling coverage.
- Integration: `./scripts/test-integration.sh tests/integration/cli/test_hooks_integration.py -k TestSessionStartHook`
  (7 passed, 9 deselected).
- Hygiene: touched-file `uv run ruff check`; `make pre-commit`.
