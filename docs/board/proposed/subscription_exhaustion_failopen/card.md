# T7 -- Subscription-exhaustion fail-open (lane degradation on the quota wall)

**Epic**: `docs/board/doing/epic_consumer_lanes/` -- read the epic for the lane contract and the **"No fallback
(de-scoped)"** decision this card carves a single, deliberate exception into.

**Lane**: `proposed/` -- depends on T4 (no consumer is bound to a subscription lane until T4 ships, so there is nothing
to exhaust yet) and has one open core decision (sticky vs per-invocation, below). Promote to `todo/` once T4 lands.

**Proves**: the epic's own **"Why now"** scenario (a Claude Max 20x user hits the weekly quota wall) is actually
*handled*, not merely *motivating* -- closing the loop the epic deliberately deferred.

## Problem

The epic's motivation is the quota wall: aux `claude -p` work burns subscription quota; placing a consumer on a
`codex`/`chatgpt` subscription lane (T4) rides a subscription instead. But a subscription is finite -- spent
mid-session, a frozen lane has nowhere to go. The epic de-scoped this ("No fallback (de-scoped)"; "Out of scope:
mid-session failover"). The 2026-06-26 workweave/Avengers-Pro discussion showed the shape is real and narrow:
workweave's `usage.Snapshot.Exhausted()` reads provider rate-limit headers and fails over to a paid key. This card lifts
only the *narrow, one-hop* version.

## Goal

When a consumer's bound **subscription** lane is exhausted, degrade **once** to its **default** lane (the frozen
`claude -p` default), **sticky for the rest of the session**, fail-open. Not a re-route to an arbitrary cheaper model --
just "subscription spent -> default lane."

## Scope

- **Exhaustion detection.** Evaluate two signals: (a) does `codex_preflight` already expose `chatgpt_tokens` exhaustion,
  or (b) read provider rate-limit headers (workweave reads `anthropic-ratelimit-unified-*`; find the codex/chatgpt
  equivalent). Pick the cheapest reliable signal; do not invent a probe.
- **Degrade to the default lane**, sticky-once-exhausted (not per-request), fail-open -- consistent with
  `proxy_not_found` and the supervisor fail-open contract (design_workflows §1.2).
- **Observable (minimal, T7-owned).** Emit one degradation event (consumer, from-lane, to-lane, reason) on the existing
  usage/telemetry plane -- self-contained and tested here, **no dependency on T5**. The richer read surface of that
  event (status line, headroom) is T5's; T7 only emits.

## Open decision (resolve in this ticket)

- **Sticky-session vs per-invocation re-check.** Workweave re-checks every request (it is dynamic by nature). Forge's
  frozen-lane philosophy argues **sticky**: exhaust once -> degraded for the rest of the session, preserving
  determinism. *Recommend sticky; confirm before code.*

## Acceptance (definition of done)

| Test                            | Fixture                                                          | Assertion                                                        | Test File                                                              |
| ------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Exhausted subscription degrades | consumer on `codex`/`chatgpt` lane + simulated exhaustion signal | next dispatch resolves to the `claude -p` default lane           | `tests/src/policy/semantic/test_supervisor.py` (or lane-resolver test) |
| Degradation is observable       | exhaustion event                                                 | one degradation event (from/to lane + reason) on the usage plane | `tests/src/policy/semantic/test_supervisor.py`                         |
| Fail-open preserved             | exhaustion mid-hook                                              | policy hook never crashes; degrades, not raises                  | `test_supervisor.py`                                                   |
| One hop only                    | default lane also unavailable                                    | no chain; stays on default (no second failover)                  | lane-resolver test                                                     |
| Healthy subscription unchanged  | non-exhausted lane                                               | no degradation; byte-identical to T4                             | `test_supervisor.py`                                                   |

## Non-goals

- **Not general mid-session failover or capacity forecasting** (still out of scope -- epic "Out of scope").
- **Not headroom-based pre-emptive routing** (do not route by remaining quota before exhaustion; that is dynamic
  routing, which the epic rejects).
- **One hop only**: subscription -> default, no chains, no arbitrary cheaper-model re-route.
- Stays **the single exception** to the epic's "no general fallback".

## Depends on

T4 (a consumer actually bound to a subscription lane to exhaust). Benefits from T5 (richer read surfaces over the
minimal event T7 emits -- headroom, status-line). Related to T0: a future `claude-max` lane would extend the same
exhaustion-detection seam.
