# Supervisor Status-Line Health -- surface fail-open timeouts

**Status**: Done (`done/`) -- shipped to `main` (2026-06-16). **Re-cut 2026-06-16** to a minimal scope: v1 reads the
outcome the **usage ledger already records** and renders a marker -- no new durable-state field. The original
structured-`failure_kind`-on-`PolicyDecision` design, and the clean two-ledger model it implied, are deferred to the
[`upstream_downstream_ledgers`](../upstream_downstream_ledgers/card.md) proposed card (see "Relationship"
below). Spun out of the `supervisor_shadow_sampling` investigation on 2026-06-14, after a supervised executor
accumulated repeated supervisor timeouts while the status line still showed only the normal active `SUP` posture.

**References**: `src/forge/cli/status_line.py::format_supervisor`,
`src/forge/cli/statusline/registry.py::_produce_supervisor` (+ the `forge_cost` throttle precedent:
`read_or_compute_session_cost`, `sum_forge_added_cost`), `src/forge/core/ops/usage_summary.py`,
`docs/end-user/session.md`.

## Problem

The status line currently answers "is a supervisor configured and enabled?" but not "is the supervisor actually
working?"

In the motivating incident, the child session had semantic supervision enabled, but every supervisor invocation timed
out after 45 seconds and failed open:

```text
Supervisor error: Timed out after 45s, failing open
```

The policy decision log and usage ledger contained the evidence, and `forge activity` could summarize it after the fact
(`supervisor 24/24 errors`). But the always-visible status line still rendered a healthy-looking `SUP`. That creates the
wrong operator intuition: the session appears watched, while in practice the watcher is repeatedly failing open.

## Proposal (v1 -- minimal, on-model)

The supervisor already records each `claude -p` run's outcome -- including the observed timeout/subprocess fail-opens --
in the usage ledger: a timeout emits `status="timeout"` / `failure_type="timeout"` (`emit_usage_for_session_result`,
`supervisor.py:496`), which is why `forge activity` already shows the 24/24. And the status line already reads the
ledger, throttled, for the `forge_cost` segment. So v1 is a **read + render**, not a schema change:

- a throttled, fail-open `supervisor_health` reader over the ledger (`command="supervisor"`, newest-first consecutive
  `status in {error, timeout}`, reset on the first `status="success"`);
- a posture-preserving `SUP!N <kind>` suffix.

Examples:

```text
SUP                  # configured, enabled, no recent health warning
SUP!3 timeout        # 3 recent supervisor failures/timeouts
SUP!1 error          # one recent non-timeout supervisor failure
SUP(susp)!2 timeout  # suspended now, but recent timeout history still visible
SUP(off)!4 error     # policy disabled now, but recent fail-open history still visible
```

Colors: YELLOW for 1-2 consecutive, RED for `>=3` (mirrors `format_spend_cap`). Literal ASCII `!` (no unicode glyph).
Detailed diagnosis stays in `forge activity` and hook/proxy logs.

**Deliberately NOT in v1:** a `failure_kind` field on `PolicyDecision`. That would patch the policy decision log -- the
*accidental* outcome record -- instead of the real one. v1 reuses the ledger's existing `status`/`failure_type`; the
principled fix is the ledger refactor below.

## What v1 covers and defers

| Fail-open kind             | v1 (ledger read)             | Deferred to `upstream_downstream_ledgers` |
| -------------------------- | ---------------------------- | ----------------------------------------- |
| timeout / subprocess error | yes (ledger `status`)        | --                                        |
| parse fail-open            | no (ledger logs a *success*) | yes (needs upstream-at-verb-entry emit)   |
| auth / proxy-not-found     | no (emits no ledger event)   | yes                                       |
| reset precision            | next successful **call**     | exact (needs no-call outcome records)     |

The observed incident was 24/24 **timeouts** -- fully covered by v1. parse/auth fail-opens are unobserved; v1 ships the
on-model marker now and lets the refactor generalize later.

## Relationship to `upstream_downstream_ledgers`

This card is the forcing function that surfaced a deeper issue: the usage ledger records **both** a call's cost/tokens
(downstream evidence) and its `status`/`failure_type` (upstream outcome) on one record, wrapped at the subprocess call
-- so it cannot cleanly answer "did this verb succeed?" for no-call operations, which is why supervisor health drifted
toward the policy decision log. The clean model splits them into a **downstream** model-interaction ledger (today's cost
\+ audit unified) and a first-class **upstream** outcome ledger wrapped at each operation boundary, with **asymmetric
correlation**: upstream records carry `session` + `run`/`root` id; downstream records carry `request`/`run`/`root` ids
and are session-blind; readers select upstream by `session` and join downstream through the run tree. Captured in
[`upstream_downstream_ledgers`](../upstream_downstream_ledgers/card.md). v1 here is the minimal on-model
step; that card is the principled completion.

## Risks

- Over-warning trains users to ignore the bar. v1 is scoped to supervisor fail-opens (the observed timeouts).
- A ledger read on the status-line hot path -- mitigated by reusing the `forge_cost` throttle (time-bounded, fail-open;
  `status_line()` must always exit 0).
- Reset is coarse (next successful call, not next cached allow) until the ledger refactor. Acceptable for a
  recent-health marker.
- The read window is a recent-health signal, not an audit trail; `forge activity` remains the full record.

## Open questions

- RED-vs-YELLOW threshold (proposed `>=3` / 1-2) -- confirm in Phase 2.
- Whether to surface non-supervisor verb health (memory-writer, panel) now or wait for the upstream ledger -- lean
  **wait** (the refactor makes it uniform; doing it per-feature now is the trap this card just stepped out of).
