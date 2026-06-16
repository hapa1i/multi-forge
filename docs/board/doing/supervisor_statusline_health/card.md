# Supervisor Status-Line Health -- surface fail-open timeouts

**Status**: In progress (`doing/`; branch `supervisor_statusline_health`). The open questions below are resolved in
[`checklist.md`](checklist.md) ("Resolved design decisions") and retained here as the original framing. Spun out of the
`supervisor_shadow_sampling` investigation on 2026-06-14, after a supervised executor accumulated repeated supervisor
timeouts while the status line still showed only the normal active `SUP` posture.

**References**: `src/forge/cli/status_line.py::format_supervisor`,
`src/forge/cli/statusline/registry.py::_produce_supervisor`, `src/forge/core/ops/usage_summary.py::_policy_activity`,
and `docs/end-user/session.md` activity-summary examples.

## Problem

The status line currently answers "is a supervisor configured and enabled?" but not "is the supervisor actually
working?"

In the motivating incident, the child session had semantic supervision enabled, but every supervisor invocation timed
out after 45 seconds and failed open:

```text
Supervisor error: Timed out after 45s, failing open
```

The policy decision log and usage ledger contained the evidence, and `forge activity` could summarize it after the fact.
But the always-visible status line still rendered a healthy-looking `SUP`. That creates the wrong operator intuition:
the session appears watched, while in practice the watcher is repeatedly failing open.

## Proposal

Extend the supervisor status-line segment from a pure posture indicator to a compact health indicator. The primary
signal should be a structured failure kind recorded when the supervisor decision is written, not a status-line parser
that re-interprets human warning text later.

Examples:

```text
SUP                  # configured, enabled, no recent health warning
SUP!3 timeout        # 3 recent supervisor failures/timeouts
SUP!1 error          # one recent non-timeout supervisor failure
SUP(susp)!2 timeout  # suspended now, but recent timeout history still visible
SUP(off)!4 error     # policy disabled now, but recent fail-open history still visible
```

Exact glyph/color choices can follow the existing statusline palette:

- active/healthy: metrics color, current `SUP`
- warning/failure: yellow for recoverable fail-open warnings
- severe/stale: red only if the evidence indicates repeated recent fail-open infrastructure failures

The signal should be small and glanceable; detailed diagnosis remains in `forge activity` and hook/proxy logs. Scope the
first version to frontier supervisor fail-open events. Cascade tier-1 plan-check failures escalate to the frontier
instead of allowing the action, so they are not the "action proceeded without frontier review" case this segment is
trying to catch.

## Design sketch

### 1. Record structured failure kind at write-time

The supervisor already knows the failure shape when it fails open. Persist that fact in Forge-owned durable state while
writing the policy decision:

```python
PolicyDecision(
    decision="allow",
    policy_id="semantic.supervisor",
    warnings=["Supervisor error: Timed out after 45s, failing open"],
    failure_kind="timeout",  # timeout | auth | parse | error
)
```

Add `failure_kind: Literal["timeout", "auth", "parse", "error"] | None` to `PolicyDecision`, or an equivalent optional
field on the serialized decision dict if the implementation wants to keep the dataclass narrower. It must be additive:
older decisions without the field still load and render normally.

Write `failure_kind` at the supervisor failure sites:

- subprocess timeout -> `timeout`
- credential/authentication/proxy-auth failure -> `auth`
- supervisor output could not be parsed into a verdict -> `parse`
- other subprocess, provider, routing, or unexpected failure -> `error`

Human warning strings can stay useful for `forge activity`, but they should not be the status line's classification API.

### 2. Source status-line health from local structured evidence

Do not call providers or scan large logs in the status line hot path.

Preferred source:

- `manifest.confirmed.policy.decisions`, already capped by the policy store
- specifically the `semantic.supervisor` sub-decisions
- `failure_kind` on fail-open supervisor decisions

Optional secondary source:

- the usage ledger's `command="supervisor"` events, via a throttled/file-backed summary if decision-log evidence proves
  insufficient

Avoid reading hook logs directly; they are diagnostic files, not a stable status-line API.

### 3. Summarize supervisor health

Introduce a small status-line helper that returns a compact health record:

```python
SupervisorHealth(
    recent_failures=3,
    last_kind="timeout",  # timeout | auth | parse | error
    last_seen_at="2026-06-14T22:54:16Z",
)
```

For legacy decisions written before `failure_kind` existed, keep a small best-effort fallback classifier isolated in the
reader. That fallback may inspect warning text or usage `failure_type`, but it is compatibility glue, not the v1 design.

### 4. Define the recency window

Status line should not permanently shame a session for one old outage.

Possible policy:

- count only the last N policy decisions, or decisions in the last M minutes
- clear the warning after a successful supervisor decision newer than the last failure
- keep a small count if failures are consecutive

The motivating case was consecutive timeouts, so consecutive-failure count is likely the highest-signal first version.
Tier-1 plan-check parse/provider failures should not increment this count unless the escalated frontier supervisor also
fails open.

### 5. Render without hiding posture

Keep the current posture semantics:

- no supervisor configured -> omit the segment
- policy disabled -> `SUP(off)`
- supervisor suspended -> `SUP(susp)`
- active supervisor -> `SUP`

Add health as a suffix, not a replacement, so the line can express both "configured posture" and "recent reliability."

### 6. Link the detailed view

When the status line shows a failure indicator, the matching detailed command should explain it:

```bash
forge activity <session>
```

Consider adding a short note to `docs/end-user/session.md` explaining that `SUP!N timeout` means supervisor checks are
failing open and actions may be proceeding without frontier review.

## Open questions

> Resolved in [`checklist.md`](checklist.md) under "Resolved design decisions"; retained here as the original framing.

- Should the status line show all recent warnings, or only infrastructure failures that caused fail-open behavior?
- Should a later successful supervisor check clear the indicator immediately, or should the last-failure count remain
  visible for a short window?
- Should repeated fail-open supervisor errors ever trigger policy escalation outside the status line?
- How should unicode vs ASCII glyph modes render the warning marker?

## Risks

- Over-warning can train users to ignore the status line. Keep the first version focused on fail-open supervisor errors,
  especially timeouts/auth/provider failures.
- Tier-1 checker health is still important, but it belongs to cascade quality/shadow-sampling surfaces. Mixing it into
  `SUP!N` would blur "cheap checker failed" with "frontier supervisor failed open."
- Decision-log evidence is capped; an old failure may disappear. That is acceptable for a recent-health signal, but not
  for audit history.
- Adding a field to persisted policy decisions is an additive schema change. Readers must tolerate old decisions without
  `failure_kind` and unknown newer fields according to the existing decision-log compatibility rules.
- Legacy string classification is still brittle. Keep it small, tested, and only for decisions written before the
  structured field existed.
- Status-line render must always exit 0. Health parsing must be fail-open and cheap.

## Acceptance sketch

- **Structured timeout recorded**: a supervisor subprocess timeout writes a `semantic.supervisor` decision with
  `failure_kind == "timeout"`.
- **Structured parse failure recorded**: an unparseable supervisor response writes `failure_kind == "parse"` while
  preserving the human warning.
- **Healthy supervisor unchanged**: an enabled supervisor with no recent structured failures renders the current `SUP`.
- **Timeout visible**: a recent `semantic.supervisor` decision with `failure_kind == "timeout"` renders a warning suffix
  with `timeout` and count.
- **Consecutive failures counted**: three newest supervisor decisions with structured timeout failures render count `3`.
- **Tier-1 failures excluded**: plan-check parse/provider failures that escalate successfully to the frontier do not
  increment `SUP!N`.
- **Success clears or ages warning**: a timeout followed by a successful supervisor decision clears or ages the warning
  per the chosen recency policy.
- **Disabled posture preserved**: policy disabled plus recent timeout history still shows `SUP(off)` with a health
  suffix.
- **Legacy warning fallback**: an old decision without `failure_kind` but with a timeout warning can still render
  `timeout` through the compatibility classifier.
- **Status line fail-open**: malformed decision-log entries render without traceback and omit bad health data.
