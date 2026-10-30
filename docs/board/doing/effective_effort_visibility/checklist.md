# Effective effort visibility execution

Started 2026-10-30 on `codex/effective-effort-visibility`, based on main `d32e7b1d`.

## Current focus

Implementation and local verification are complete; the card is ready for PR review. Effort resolution precedence and
the existing run-tree/provider correlation scope are preserved. The runtime reports Forge's outbound effort only;
provider-side remapping remains outside the claim.

Shared ownership: core effort records contain resolution and applied-wire facts without importing proxy code. Proxy
runtime exposes a tier-keyed `runtime.effort` map only for a validated launch query. The status line and session model
read surface consume those defensive runtime facts. Lifecycle launch/header code uses the routing commitment's existing
root run identity.

## Phase A

- [x] Render direct stdin effort in the model label, remove context suffix/deeper colors, and remove `think` from the
  default order while preserving the opt-in segment.
- [x] Emit the stderr launch hint only for confirmed translated managed Claude launches without explicit effort.
- [x] Cover start/resume/fork/incognito and silent direct/passthrough/no-launch/bare/unknown/explicit-effort paths.

## Phase B

- [x] Stamp launch identity for proven Forge proxy host and sidecar launches; scrub it from headless and direct paths.
- [x] Preserve resolution behavior while recording requested/applicable/derived/floor/pre-clamp/supported/resolved
  facts.
- [x] Observe final outbound parameters in streaming and non-streaming clients, including dropped effort and passthrough
  overrides; bound launch/tier observations in memory and scope the runtime query.
- [x] Share route prediction across model, drift and marking, respecting wire shape, projected tier and alternatives.
- [x] Render active-tier observed model/effort and unknown, stale or dropped states without adding source probes.
- [x] Add the shared terminal/direct-command effort explanation, using only a proven route commitment's launch ID.

## Verification and documentation

- [x] Probe pinned/latest Claude status-line stdin and request model identity with an isolated local upstream; record
  absent fields and version limits without paid inference.
- [x] Pass focused resolution/client/header/query/explain/status-line tests and routing regressions.
- [x] Run targeted proxy integration with a stub upstream and relevant session/Docker launch integrations.
- [x] Synchronize runtime/telemetry design, CLI reference, end-user status-line and launch-effort guidance.
- [x] Pass aggregate unit, regression, full pre-commit and board/link checks; record non-passing attempts and repairs.
- [x] Complete independent review and prepare the card PR with retained verification evidence.
- [ ] After merge, verify main and perform board closeout.

## Acceptance evidence

Native probe results and integration assertions are retained in [evidence/README.md](evidence/README.md) and
[evidence/native-probes.json](evidence/native-probes.json). Raw local logs are temporary, not archival evidence.

| Test                       | Fixture                                                                             | Assertion                                                                                        | Test file                                                                                              |
| -------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Direct and observed labels | stdin with/without effort; active/inactive tiers; changed model/effort              | Compact label, clamped/dropped/unknown/stale states, no context suffix, no extra fetch           | `tests/src/cli/statusline/test_statusline_effort.py`                                                   |
| Route prediction           | non-Claude projected Opus on Sonnet default; passthrough Opus 4.6 on advertised 5.5 | Model, marking and drift share the actual route; unproven routes stay unknown                    | `tests/regression/test_bug_statusline_effort_route.py`                                                 |
| Launch hints               | each lifecycle verb and wire shape, exact raw argv, malformed live response         | One stderr line only on qualifying launches; launch remains usable when hint data is unavailable | `tests/src/cli/test_session_effort_hint.py`                                                            |
| Final wire observation     | Argon/OpenRouter/GPT-5/native fixtures, stream and completion                       | Runtime applied effort matches captured outbound JSON after client mutations                     | `tests/integration/proxy/test_effort_observation_e2e.py`                                               |
| Launch isolation           | host/resume/direct and actual Docker sidecar launcher                               | Header and commitment share one run ID; fresh launch changes key; no header on direct            | `tests/integration/docker/test_session_routing.py`, `tests/integration/sidecar/test_launch_headers.py` |
| Explain lookup             | unmarked proven commitment, legacy/unproven launch, old/unreachable proxy           | Only proven commitment scopes observation lookup; unknown reasons remain explicit                | `tests/src/core/ops/test_session_model.py`                                                             |

Focused checks passed: 403 status-line tests, 195 explain tests, 379 launch/header tests, 229 proxy tests, 149 client
tests, and 29 final hint tests. These overlapping runs are diagnostic checks, not an additive suite total. Independent
read-only review of proxy/client observation and explain lookup found no actionable issues. A defensive wire-shape type
guard was added with malformed-response cases; the existing tuple membership did not reproduce a TypeError.

Final checks: `make pre-commit` passed, including repository size and Markdown link audits; `make test-unit` passed
11,418 tests in 82.78s; `make test-regression` passed 2,234 tests in 106.61s. All eight proxy integration cases passed;
the four Docker launch cases passed again after the hint-state extraction (31.93s). The documentation review's opt-in
wording finding was corrected. No known blocker remains; merge and board closeout remain pending.

[evidence/checks.json](evidence/checks.json) retains command results and hashes for the temporary full logs.
