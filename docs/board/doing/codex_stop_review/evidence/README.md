# B4 runtime gate — 2026-10-11

**Go for Codex 0.162.1**, with the constraints below. This permits product implementation; it does not close B4's
product acceptance rows. No product configuration, schema, CLI, or installed-handler changes preceded this gate.

The retained native binary has SHA-256 `74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`. The private
round is `/private/tmp/forge-b4-20261011`; it has an independent Codex login, stripped environment, disabled dotenv,
dedicated homes, and a retained complete Homebrew package. Forge hooks resolve to the checkout at planning commit
`44b14e89`; each capture records the dirty source digest and helper hashes. No API inference or real Claude review has
run. Thirteen of the 32 Codex turn units are reserved, including the inference-free enrollment TUI and two automatic
correction continuations. The one real Claude subscription review remains reserved for the product control.

## Observations and implementation constraints

| Capture                    | Observed result                                                                                                                                                                                                               |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `01-enroll-tui`            | Accepted folder trust and the seven exact hook definitions through the native TUI. No model prompt submitted.                                                                                                                 |
| `02-enrollment`            | Forge preflight and ChatGPT subscription readiness passed. Empirical SessionStart receipt retained; fixture UserPromptSubmit and Stop also observed.                                                                          |
| `03-managed-start`         | Structured transfer from a synthetic parent; UserPromptSubmit preceded two apply_patch calls. Both calls and Stop shared its turn ID.                                                                                         |
| `04-managed-resume`        | Same native thread, new turn ID, unchanged file hashes, one UserPromptSubmit and one Stop.                                                                                                                                    |
| `05-tui-multiple`          | Two prompts in one resumed TUI produced distinct turn IDs. Apply-patch and shell changes followed their respective baseline event. Stop systemMessage appeared in the notices panel and was absent from the retained rollout. |
| `06-stop-correction`       | One UserPromptSubmit, two Stop events, one turn ID; stop_hook_active changed false to true. The continuation created corrected.txt after the first Stop snapshot.                                                             |
| `07-stop-source`           | Fixed source-only fixture guidance and a synthetic approved-plan quotation reached the continuation with optional summary omitted. This is wire evidence, not product quotation verification.                                 |
| `08-stop-native-expiry`    | At the registered 60-second expiry, Codex killed the hook but a deliberately detached, unguarded sleeping reviewer survived. The outer harness terminated it; no remaining processes.                                         |
| `09-stop-guarded-deadline` | B1 admission and guarded transport dispatched one local stub; the three-second deadline ended the review. Hook elapsed 3.68 seconds; no pre-sweep survivors.                                                                  |
| `10-stop-guarded-expiry`   | Deliberately extended the guarded transport to 90 seconds to reach native Stop expiry. The watchdog terminated the reviewer on hook death; no pre-sweep survivors after a two-second cleanup observation interval.            |

Use **UserPromptSubmit** to establish a baseline, scoped to the verified managed launch, native thread, and user turn.
SessionStart alone cannot distinguish TUI prompts. The tested automatic corrections kept the turn ID and did not issue a
new UserPromptSubmit. These observations support a durable one-dispatch reservation; concurrency, crashes, pruning, and
stale replay still require product tests. Replaying recorded payloads will not be reported as native retry evidence.

The Stop block reason entered native context as a **user-role** message wrapped in
`<hook_prompt hook_run_id="stop:6:<fixture-config>">`; its rollout metadata had `client_authored: false` and the same
turn ID. Control all reason text under B3's provenance and source-only rules. Do not use the wrapper's numeric hook ID
as a global turn key. The second Stop must report changes after the reviewed snapshot as unreviewed and cannot buy a new
review or correction. Operator systemMessage visibility does not establish model receipt.

Keep the exact Stop registration at **60 seconds**, start the whole hook budget before setup/capture, reserve five
seconds for completion, and retain the **1–45-second reviewer limit**. Use B1's parent-death watchdog. Native expiry
alone does not bound detached descendants. The 90-second transport is labelled fault instrumentation; it is not a
proposed product timeout. Both guarded controls counted dispatch only after the stub's dispatch_started record.

Feature admission is limited to **0.162.1 with a verified invoking launch parent**. The guarded probes recorded the
existing B3 process-parent check passing. Inherited environment records alone must not admit a nested runtime. The
general QA ceiling, release pin, and shared QA provenance are unchanged.

## Evidence and reproducibility

[native-gate.json](native-gate.json) contains sanitized observations, exact hook outputs, rollout hook messages,
receipts, cleanup outcomes, setup failures, and turn reservations. Raw captures and terminal streams remain private.
[harness-snapshots.json](harness-snapshots.json) records every captured helper hash and drift against the exported tree;
[helper-sources.json](helper-sources.json) records the final helper set, including fixture preparation, admission,
verification, and export code.

The committed harness will post-date these first controls. During preparation, formatting changed; project-anchor setup
was added after its initial refusal; the recorder gained process-parent verification and guarded lifetime arms; the
driver gained a two-second cleanup observation interval. Earlier ordinary event/response captures do not claim to have
used those additions. The initial empty-module project setup also refused before any inference. Failed setup records are
retained. Product controls must use and record the final helpers; a representative native control will also be repeated
from the committed helper revision.

Reproduction uses the new round's `run` wrapper for every command. Prepare with `b4-fixture.py`, obtain the fixture's
own login, run `b4-gate.py <round> setup`, perform the native trust ceremony, then capture
`forge runtime preflight codex --verify-enrollment --json` and seal that successful result with `b4-gate.py ... seal`.
`b4-cases.py` owns managed start/resume/TUI controls, `b4-validate-stub.py` checks admission without inference,
`b4-verify-gate.py` checks the named gate captures, and `b4-export.py` publishes sanitized evidence without filtering
failed captures. Preparation refuses an existing or enrolled fixture; it never copies or resets auth.
