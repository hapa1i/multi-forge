# Managed Codex proxy routing execution checklist

[Card](card.md) · Branch `codex/codex-session-proxy-routing` · Base `455412ca` on `main`.

## Outcome

Managed proxy routing shipped on `main` on 2026-11-28. The CLI matrix passed on Codex 0.141.0 and 0.172.0 using
disposable homes and loopback upstreams. Successful proxy-backed Stop review remains unverified.

## Native evidence

- [x] Verify native headless start and resume with per-launch run headers. Codex 0.141.0 and 0.172.0 completed all eight
  turns across the local and OpenRouter Responses templates with a synthetic upstream. Each resume kept its thread and
  sent the first answer in its history. The proxy recorded the expected run/root pair and a 10,000-micro-USD fixture
  charge for each create. No Forge header reached the upstream. [Headless receipt](evidence/headless-header-matrix.json)

- [x] Verify TUI start and reattach in separate PTY processes on 0.141.0 and 0.172.0 through the OpenRouter Responses
  template. Each reattach sent the first answer and recorded the second completion in the original rollout. Forge
  recorded distinct launch IDs and stripped its headers upstream. On 0.172.0 an extra title request produced three proxy
  attempts for two completed user turns. [TUI receipt](evidence/tui-header-matrix.json)

- [x] Confirm successful and rejected model switches through bare reattach on the original thread. A native completion
  marker alone also appeared on rejected turns. Matching the foreground thread and turn to the proxy dispatch excludes
  title requests. Ambiguous evidence refuses replay. [Native TUI receipt](evidence/managed-tui-model-replay.json)

- [x] Verify proxy-only advisory enrollment, hook denial, PreToolUse feedback on the next native request, and an
  independently authenticated Messages reviewer on 0.161.0 and 0.162.1. The Docker sandbox refused the underlying file
  write after the permissive hook. [Enrollment and reviewer receipt](evidence/managed-proxy-hook-enrollment.json)

- [ ] **Deferred live verification.** On an operator-enrolled 0.162.1 home, confirm proxy-backed preflight reports
  `stop_review_enrolled: true`, then record a foreground turn, its Stop reviewer dispatch, and session status and
  activity. The available fixture trusted only SessionStart and PreToolUse. Forge refused Stop configuration before
  dispatch. [Enrollment receipt](evidence/managed-proxy-hook-enrollment.json) ·
  [Verification procedure](../../../developer/verification.md#codex-runtime-consumer-lanes-and-supervision)

- [x] Run headless and TUI start and resume through the ordinary Forge CLI on the floor and newer binary. Each
  continuation kept the original thread and verified listener. [Managed CLI matrix](evidence/managed-cli-matrix.json)

- [x] Replay opaque reasoning after an explicit cross-model failure. Both versions surfaced the synthetic upstream's
  HTTP 400 and reused the original model on the next bare resume.
  [Cross-model receipt](evidence/managed-headless-cross-model.json)

## Implementation

- [x] Refuse alias-only adoption before binding, including the recheck after planning. Preserve ordinary direct adoption
  and cover the existing misclassification with a regression.
- [x] Select native or proxy preflight on all four launch paths. Verify the recorded listener, apply its live policy,
  scrub credentials and stamp managed identity. Keep direct as the default and route flags creation-only.
- [x] Version the proxy-backed manifest and journal payload. Record exact slugs and update the completed-turn model only
  for the bound thread and current session instance. Exercise old formats and downgrade refusal.
- [x] Replay the last proven selection. Refuse drift in the ZDR mapping before sending history. Surface these facts in
  launch banners, session details, model reports and journal history.
- [x] Attribute headless tokens and proxy charges once and resolve TUI spend through the instance's own launches.
  Exercise identically named sessions across projects and after recreation.
- [x] Retry a delayed dispatch through the public resume command. The first retry sent zero requests. Once the record
  was visible, the same command continued the original thread. Verify that two resumes planned from one predecessor can
  publish only one new commitment.
- [x] Show unavailable routing and activity evidence in human and JSON reports. Verify that a v2 downstream reader still
  counts charged attempts carrying the Codex turn reference.
- [x] Refuse occupied session names before starting a template proxy, show the bound proxy in advisory enrollment
  guidance, and cover failure of the live enrollment probe.

Direct native resume counters need a separate measurement.
[Proposed follow-up](../../proposed/codex_native_resume_usage/card.md)

## Acceptance fixtures

| Fixture                                                                               | Observable result                                                                                           | Driver                                    |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Empty native login store, synthetic proxy credential, approved plan file              | Four managed launches work with matching auth facts. A hook-triggered review uses its own credentials.      | Real Codex, fake upstream and reviewer    |
| Same port and template, different proxy ID                                            | Both resume forms refuse before a create or journal commit. Restoring the recorded instance permits resume. | Managed entry points and proxy fixture    |
| Gemini turn, changed default, explicit switch and failed switch                       | Bare resume follows the last completed turn. Changed fallback and ambiguous completion send zero creates.   | Native exec and PTY reattach              |
| Two creates in one headless turn, two projects with the same session name             | One JSONL token total, exact per-project spend, shared cap enforced on the next create.                     | Proxy, telemetry CLI and session journals |
| Historical direct and Claude sessions, proxy-backed session with an uncatalogued slug | Existing formats round-trip, new reads preserve the slug, older Forge rejects the new state.                | Manifest store, journal and CLI reports   |

## Closeout

[PR #311](https://github.com/hapa1i/multi-forge/pull/311) merged into `main` as `e2bddf24` on 2026-11-28. The final head
passed 12,126 unit tests, 2,755 regressions and all pre-commit hooks. The Python 3.11 and 3.13 CI lanes and wheel checks
passed. [Test run](https://github.com/hapa1i/multi-forge/actions/runs/46143053202) ·
[Pre-commit run](https://github.com/hapa1i/multi-forge/actions/runs/46143053203)

The managed CLI, reports, Responses proxy and transfer fixtures passed all 53 Docker-harness tests. The metered headless
fixture also verified two cost records for one tool turn, per-launch JSONL tokens, and a rejected create after reaching
the shared cap.

The separate Claude 2.1.245 adoption control missed its second Stop artifact on both this branch and unchanged `main` at
`455412ca`. The native client returned its second answer on both revisions.

- [x] Run the relevant Docker-backed integration fixtures through Forge and retain native receipts.
- [x] Sync the design and operator guides with the implementation and verification procedure.
- [x] Record the merge and the outstanding live Stop check in the
  [change log](../../change_log.md#route-managed-codex-sessions-through-a-forge-proxy).
