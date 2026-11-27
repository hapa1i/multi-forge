# Managed Codex proxy routing execution checklist

[Card](card.md) · Branch `codex/codex-session-proxy-routing` · Base `455412ca` on `main`.

## Current focus

Verify model selection across an in-TUI switch and identify the last completed foreground turn after a failed switch.
The native header probes below cover start and resume in disposable homes. The managed CLI floor also depends on the
remaining model and enrollment evidence.
[Predecessor probes](../../done/codex_openrouter_responses/probe-results.md#tool-use-and-compaction)

## Native evidence

- [x] Verify native headless start and resume with per-launch run headers. Codex 0.141.0 and 0.172.0 completed all eight
  turns across the local and OpenRouter Responses templates with a synthetic upstream. Each resume kept its thread and
  sent the first answer in its history. The proxy recorded the expected run/root pair and a 10,000-micro-USD fixture
  charge for each create. No Forge header reached the upstream. [Headless receipt](evidence/headless-header-matrix.json)
- [x] Verify TUI start and reattach in separate PTY processes on 0.141.0 and 0.172.0 through the OpenRouter Responses
  template. Each reattach sent the first answer and recorded the second completion in the original rollout. Forge
  recorded distinct launch IDs and stripped its headers upstream. On 0.172.0 an extra title request produced three proxy
  attempts for two completed user turns. [TUI receipt](evidence/tui-header-matrix.json)
- [ ] Capture completed, failed and ambiguous turns after explicit headless and in-TUI model changes. Distinguish a
  completed user turn from title and tool requests. Record the requested and dispatched slugs on each route.
- [ ] Probe executor hooks, proxy-only advisory enrollment and the admitted feedback and Stop-review versions.

## Implementation

- [ ] Refuse alias-only adoption before binding, including the recheck after planning. Preserve ordinary direct adoption
  and cover the existing misclassification with a regression.
- [ ] Select native or proxy preflight on all four launch paths. Verify the recorded listener, apply its live policy,
  scrub credentials and stamp managed identity. Keep direct as the default and route flags creation-only.
- [ ] Version the proxy-backed manifest and journal payload. Record exact slugs and update the completed-turn model only
  for the bound thread and current session instance. Exercise old formats and downgrade refusal.
- [ ] Replay the last proven selection. Refuse drift in the ZDR mapping before sending history. Surface these facts in
  launch banners, session details, model reports and journal history.
- [ ] Attribute headless tokens and proxy charges once and resolve TUI spend through the instance's own launches.
  Exercise identically named sessions across projects and after recreation.

## Acceptance fixtures

| Fixture                                                                               | Observable result                                                                                           | Driver                                    |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Empty native login store, synthetic proxy credential, approved plan file              | Four managed launches work with matching auth facts. A hook-triggered review uses its own credentials.      | Real Codex, fake upstream and reviewer    |
| Same port and template, different proxy ID                                            | Both resume forms refuse before a create or journal commit. Restoring the recorded instance permits resume. | Managed entry points and proxy fixture    |
| Gemini turn, changed default, explicit switch and failed switch                       | Bare resume follows the last completed turn. Changed fallback and ambiguous completion send zero creates.   | Native exec and PTY reattach              |
| Two creates in one headless turn, two projects with the same session name             | One JSONL token total, exact per-project spend, shared cap enforced on the next create.                     | Proxy, telemetry CLI and session journals |
| Historical direct and Claude sessions, proxy-backed session with an uncatalogued slug | Existing formats round-trip, new reads preserve the slug, older Forge rejects the new state.                | Manifest store, journal and CLI reports   |

## Closeout

The activation baseline on `455412ca` passed 132 existing tests covering Codex session operations, interactive launches,
adoption and routing journals.

- [ ] Run the relevant Docker-backed integration files as each slice lands. Verify through the normal Forge entry points
  and retain the native evidence required by the [card](card.md#integration-acceptance).
- [ ] Sync the [design and user docs](card.md#scope) and the verification guide with shipped behavior.
- [ ] Run unit, regression, pre-commit and Markdown link checks on the integrated branch. Record the shipped outcome and
  move the card to `done/` when verified.
