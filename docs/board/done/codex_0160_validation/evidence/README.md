# B2: Codex 0.161.0, 2026-10-09

The selected existing Forge contracts passed on the retained **0.161.0** executable. Advance the general probe ceiling
only. The blocking QA release pin stays **0.149.1**; its shared Claude/Codex validation date, revision, and probe
records stay unchanged. Proxy transport was not tested; its independent floor stays **0.141.0**. Live
subscription-exhaustion detection remains **unverified**: quota was not deliberately exhausted.

## Identity and method

- Source: `/opt/homebrew/Caskroom/codex/0.161.0/bin/codex`; retained complete package under
  `/private/tmp/forge-b2-20261009/runtime/0.161.0/` throughout the round.
- SHA-256: `12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de`.
- macOS 26.6.2, arm64; `gpt-6.1-sol`, low effort. The later 0.162.0 update notice did not change the subject.
- Forge revision `44e7590c` above B1 closeout `79563944`, with each invocation's source diff and harness hashes in
  [provenance.json](provenance.json) and [harness snapshots](harness-snapshots.json). `FORGE_DEV` and hook-side
  launcher/module captures prove checkout dispatch; Forge's version string alone would also match the pre-B1 global
  installation.
- One independent operator-completed file login, reused in place. The clean launcher strips API keys and disables
  dotenv. Doctor/preflight reports `chatgpt_tokens`, `codex_store`, `subscription_quota`, and `enrollment_gated`. Only
  the fixture's real project/hook ceremony counts as enrollment; stage 10's trust bypass is diagnostic.
- Nested Claude reviewers are admitted local **stubs**, with separate dispatch-entry markers. Real Claude calls:
  **zero**. No API-key inference route was used. Their usage records are synthetic, not measured subscription
  consumption.

The ceiling was **100 reserved Codex turns**, including six schema-rejection launches, failed attempts, retries,
subagents, Stop continuation, explicit enrollment, and the extra enrollment on each advisory launch/resume. The final
reservation ledger is in provenance. Reservations intentionally overcount actual completed turns.

Ordinary model cases have a 240-second outer timeout, TERM then KILL after five seconds, and an independent owner that
records detached survivors before sweeping them. Lifetime cases use 130 seconds; scripted TUI cases use 180 seconds. The
raw private captures remain outside Git. Published artifacts replace local paths and opaque encrypted subagent messages;
[source hashes](source-hashes.json) identify the original bytes. The [clean launcher](environment.sh.txt) records the
isolated environment. No credential store is included.

## Results and downstream decisions

| Row                         | Disposition                                                   | Evidence                                                                                       |
| --------------------------- | ------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| E1 Existing paths           | Pass                                                          | [Baseline](baseline.json), [product](product.json), [interactive](interactive-background.json) |
| E2 Allowed feedback         | Bare context delivered; explicit allow did not                | [Feedback](feedback.json)                                                                      |
| E3 Operator channels        | `systemMessage` visible; exit-zero stderr not visible         | [Interactive](interactive-background.json)                                                     |
| E4 Lifetime                 | Cleanup passed; interrupted attempts incomplete               | [Lifetime](lifetime.json)                                                                      |
| E5 Catch-all                | Observed names and measured costs; no polling hook            | [Coverage](coverage.json)                                                                      |
| E6 Background               | Live/next-turn delivery; no autonomous idle turn observed     | [Interactive/background](interactive-background.json)                                          |
| E7 Planning fork            | Pass for the tested short source                              | [Forks](forks.json)                                                                            |
| E8 Shared/concurrent source | One controlled boundary passed; no general snapshot guarantee | [Forks](forks.json)                                                                            |
| E9 Read-only/recursion      | Read-only and recursion passed; parent isolation failed       | [Forks](forks.json)                                                                            |
| E10 Plan events             | Unsupported in the exposed tool inventory                     | [Coverage](coverage.json)                                                                      |
| E11 Stop                    | One continuation within the same observed turn                | [Stop](stop.json)                                                                              |

**E1.** Stages 00/05/10/60/61/81/84 retain the previous ceiling's baseline plus native resume and rollout identity.
Stage 88 adds actual Forge readiness, current user-scope dispatcher enrollment, and the verifier's observation receipt.
Cases 89/91/92 replace the older direct-command 85/86 recipes: product TDD deny prevents the file; an
implementation-first multi-file patch with its test passes; rewritten input changes the written bytes; absent hooks and
malformed output allow the controlled patch. Malformed output is **fail-open**, not a supported safety boundary.
Advisory shell writes are denied before semantic filtering, while producer and unmarked controls write. Managed hook
context reaches the model and reconciles to `session_start_hook`; suppressing hooks produces `NONE`, `hook_undelivered`,
and exit 1. Native token usage matches one correlated `codex_exec` / `codex_jsonl` event with subscription billing and
no dollar cost. TUI start, reattach with token recall, active-session refusal, and hook-delivered context were exercised
separately.

**B3 / E2–E3.** Empty stdout and `CodexHookResponder.allow_feedback()` with explicit `permissionDecision: "allow"` let
the patch run but did not deliver their nonce. This response delivered the hook-only nonce after the allowed patch:

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":"<hook-only nonce instruction>"}}
```

`systemMessage` appeared as a TUI `Hook` notice, but the model answered `NONE`. Exit-zero stderr did not appear in the
model answer, headless event output, or inspected TUI/warnings. These observations are channel-specific; B2 does not
change product feedback. Keep the authority guard when considering a narrower matcher.

The retained native rollouts independently support this distinction: bare context injected a developer-role message
tagged `hooks.additional_context`; the explicit-allow, observe, `systemMessage` and stderr nonces occur zero times.
[Feedback evidence](feedback.json) records the checks and injected message. The original custom-hook stdout, stderr and
exit status were not captured. Offline replay passes all five response arms and their helper hashes match the runs, but
it cannot establish the historical exit status. The corrected harness captures those outputs for future probes.

**E5.** The model used code-mode tool calls. Actual hook names were `Bash`, `apply_patch`, `mcp__b2__echo`,
`collaborationspawn_agent`, and `collaborationwait_agent`. Shell polling called `write_stdin` but produced no separate
PreToolUse payload. MCP initially reached the hook but failed tool approval; marking the local echo read-only gave a
completed control. `ALL_TOOLS` enumeration exposed neither `update_plan` nor `close_agent`. This is a limitation of this
binary/model/session surface, not a universal statement about all Codex environments. No plan-event payload or approval
rule can be inferred. The spawn message field was opaque encrypted content; only its shape is retained.

Dispatcher replay wall time includes instrumentation and process startup, excludes executor/model latency, and uses five
samples per tool in each condition. Supervision-off medians were 538–548 ms. Supervision-on non-patch medians were
531–550 ms with **zero** reviewer entries. The five patch samples had four stub calls and one verdict-cache hit:
uncached samples were about 684–693 ms; the cache hit was 539 ms. A separate cold-admission sample was 1,285 ms and its
warm verdict-cache control was 697 ms; [dispatcher samples](dispatcher-timings.json) retain both. These small samples
are not production latency percentiles.

**B4 / E4, E6, E11.** The ordinary unmodified B1 path terminated its admitted sleeping reviewer at about 44.85 seconds,
recorded `unavailable/timeout`, and allowed the patch under fail-open policy. The instrumented arm extended only
reviewer transport to 90 seconds; Codex's unchanged 60-second registration stopped it about 59.28 seconds after reviewer
entry. That action ran, while status derived `incomplete/deadline_elapsed` from the unfinished attempt. Hook-only
SIGKILL also allowed the action and left `incomplete/reviewer_owner_exited`; executor SIGINT cancelled the turn and
prevented the patch. All four arms had no surviving reviewer/descendant before emergency cleanup. Missing terminal
records or usage are not aligned verdicts or proof of zero cost. The [status/activity snapshots](lifetime-status.json)
retain these operational outcomes.

Background context was consumed during a live turn. In a persistent TUI it completed after the first Stop, did not start
an observed turn while idle, and reached the explicitly submitted next user turn. A headless executor that exited before
delayed completion left neither a completion marker nor a surviving child; the exact cancellation signal was not
established. Background results cannot enforce an already executed action.

The Stop control emitted `FIRST`, then `SECOND` after exactly one block. Both Stop payloads had the same thread and turn
IDs; `stop_hook_active` changed false to true. There was one `UserPromptSubmit`, one turn start, and one turn
completion. The block reason also entered the native context as a **user-role** message wrapped in
`<hook_prompt hook_run_id="stop:22:<fixture-config-path>">`. That is a hook-generated continuation with user authority,
not a second operator submission. B4 should retain this marker and control the reason text it supplies. This one case
does not establish `hook_run_id` uniqueness or stability across retries or launches; an idempotency rule needs those
checks and must handle edits after its reviewed snapshot. A no-block control emitted only one Stop.

**B5 / E7–E9.**
`codex exec --json --sandbox read-only -C <action> fork --ephemeral --output-schema <schema> <source> <prompt>` returned
valid structured output, a distinct fork ID, inherited a source-only planning sentinel, and left the quiescent source
rollout unchanged. No fork rollout was persisted. The fork read the action checkout and the runtime blocked its
attempted patch; workspace-write allowed the same kind of patch. The shared-source fork recalled both planning and later
implementation sentinels and selected the explicitly supplied approved plan in this one observation. That does not
establish reviewer independence or long-context retention.

With `FORGE_DEPTH=2` and `FORGE_COMMAND=supervisor`, hooks fired and nested reviewer calls were zero. However, their
policy decisions and `confirmed_at` mutated the **parent Forge manifest**. B5 must isolate that state before reuse;
depth suppression alone is insufficient. Native source identity itself did not change. The controlled concurrent case
forked while the source was in an observed `Bash` sleep: both processes completed, the fork saw the active marker,
source prefixes were preserved, and its prompt did not enter the source. This single boundary is not an atomic snapshot
guarantee; an earlier-turn selector and safe arbitrary concurrent review remain unverified.

## Non-passing attempts and repairs

- Stage 84's legacy EXIT trap removed the independent fixture auth. Five subsequent launches failed with 401 before a
  completion. They are not negative hook evidence. The operator logged into that fixture again; the corrected cleanup
  and login admission have regression coverage. The host login was never copied or logged out.
- Initial setup attempts failed on sandbox process inspection, Git signing, a missing clean-PATH `uv`/Docker, and a
  Docker storage error. Docker was restarted with no running containers; selected policy integrations then passed.
- The first concurrent detector expected `exec_command`, so its source had finished before forking. That attempt is
  inconclusive; the corrected `Bash` detector has a separate capture.
- Early terminal drivers could not submit input or exit cleanly. Those attempts remain separate from the completed TUI
  turns and clean reruns. An unreconciled interrupted session was refused on resume. Passing a prompt among Forge's raw
  resume arguments was parsed by Codex as a session ID; the final reattach probes use typed terminal input.
- The smoke integration initially inherited the test suite's empty `CODEX_HOME`. It now opts into the same
  `real_codex_home` fixture as the existing start/resume integration; that restores this round's independent home,
  without copying credentials. The curation call in the start/resume integration remains mocked.

## Validation and closeout

The [validation log](validation.md) records checks, artifact identity, and source-drift qualifications.
[PR #261](https://github.com/hapa1i/multi-forge/pull/261) merged as `2a15c087`; the
[2026-10-10 closeout](../checklist.md#merged-closeout) moves B2 to `done/`. The optional fresh stage 88/97 reruns were
not performed before merge. B3–B5 remain proposed under the active epic. No new warning, Stop-supervisor, native-fork
supervisor, release-pin, or proxy behavior ships here.
