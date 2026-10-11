# B4 Stop-review evidence — 2026-10-11

The opt-in product and installed-wheel controls pass on **Codex 0.162.1**. Candidate `c4354a9c` provides a durable
one-review allowance per explicit turn, one consumed correction, and visible outstanding work after the correction. The
round closed at **32 reserved Codex turn units**, one real Claude subscription-only review, and no API inference. The
documentation count gate is resolved; [validation.md](validation.md) records the final checks and qualifications.

[product.json](product.json) indexes every product attempt, including failures, wheel reports, reservations and
teardown. The wheel's Python files match the candidate byte-for-byte; its SHA-256 is
`874fe07b8a0e2000b9f5bdd720bf68e9c12a47a36ad436e5ee080d80875d88c1`.

## Product controls

| Capture                                                                                                                                  | Result                                                                                                                                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [13: exact event enrollment](product/13-product-enrollment.json)                                                                         | One read-only probe delivered SessionStart plus all four Stop-review events.                                                                                                                                                                            |
| [14: aggregate failure](product/14-product-aggregate.json), [15: carry](product/15-product-aggregate-carry.json)                         | Absolute native patch paths initially made coverage incomplete with no dispatch. After normalization, two patch writes and a shell write across the pending scope received one review.                                                                  |
| [16: source-only correction](product/16-product-source-correction.json), [17: next-turn carry](product/17-product-correction-carry.json) | One verified plan quote reached user-authority Stop context with summaries off; raw reviewer nonce did not. One automatic correction received no second review. The next explicit turn reviewed and cleared its outstanding delta.                      |
| [18: real aggregate](product/18-real-aggregate.json)                                                                                     | One subscription-only `claude-sonnet-5-5` dispatch completed a retained native aggregate; usage reported `subscription_quota`. This ran outside the native hook and did not clear later operational state.                                              |
| [19: deadline](product/19-product-deadline.json), [20: hook SIGKILL](product/20-product-hook-kill.json)                                  | Both started one admitted sleeping stub. The deadline stayed spent/unavailable; hook death stayed spent/incomplete. No pre-sweep survivors.                                                                                                             |
| [21c: TUI child](product/21c-product-tui-child.json)                                                                                     | Structured transfer bootstrapped fresh policy. Configuration in the idle TUI preceded the first supervised prompt; that prompt produced one review and a rendered operator notice.                                                                      |
| [22: executor cancellation](product/22-product-executor-cancel.json)                                                                     | Killing Codex left its detached Stop owner alive; harness cleanup was required. The subsequent parent-death guard passes a real-process regression, including a TERM-resistant reviewer and child. Native cancellation was not repeated after that fix. |
| [23: wheel enrollment](product/23-wheel-enrollment.json), [24: wheel correction](product/24-wheel-correction.json)                       | Independently enrolled exact hooks, then resumed the TUI child headlessly through the clean wheel with no `FORGE_DEV`. One reviewer, two Stops, one native turn ID; GOOD replaced BAD and remained visibly unreviewed.                                  |

Normal completed stub review took 0.760 seconds in capture 15; the wheel's first Stop took 0.970 seconds and its
continuation Stop 0.570 seconds. These are individual samples, not a latency distribution. The source-only control
covers the block reason; `systemMessage` remains an operator channel, without a claim of non-blocking model receipt.

The cap counts frontier reviewer dispatches, not token consumption or provider-internal HTTP requests. Stub calls are
synthetic. The real control verifies route and output quality for one retained aggregate, not an invoice or quota
change. Codex subscription exhaustion did not occur naturally and remains unverified.

## Runtime gate (before product implementation)

**Go for Codex 0.162.1**, with the constraints below. This permits product implementation; it does not close B4's
product acceptance rows. No product configuration, schema, CLI, or installed-handler changes preceded this gate.

The retained native binary has SHA-256 `74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`. The private
round is `/private/tmp/forge-b4-20261011`; it has an independent Codex login, stripped environment, disabled dotenv,
dedicated homes, and a retained complete Homebrew package. Forge hooks resolve to the checkout at planning commit
`44b14e89`; each capture records the dirty source digest and helper hashes. At this gate, no API inference or real
Claude review had run. Thirteen of the 32 Codex turn units are reserved, including the inference-free enrollment TUI and
two automatic correction continuations. The one real Claude subscription review was reserved for the later product
control.

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

The committed harness post-dates these first controls. During preparation, formatting changed; project-anchor setup was
added after its initial refusal; the recorder gained process-parent verification and guarded lifetime arms; the driver
gained a two-second cleanup observation interval. Earlier ordinary event/response captures do not claim to have used
those additions. The initial empty-module project setup also refused before any inference. Failed setup records are
retained. Product controls must use and record the final helpers; a representative native control will also be repeated
from the committed helper revision.

Reproduction uses the new round's `run` wrapper for every command. Prepare with `b4-fixture.py`, obtain the fixture's
own login, run `b4-gate.py <round> setup`, perform the native trust ceremony, then capture
`forge runtime preflight codex --verify-enrollment --json` and seal that successful result with `b4-gate.py ... seal`.
`b4-cases.py` owns managed start/resume/TUI controls, `b4-validate-stub.py` checks admission without inference,
`b4-verify-gate.py` checks the named gate captures, and `b4-export.py` publishes sanitized evidence without filtering
failed captures. Preparation refuses an existing or enrolled fixture; it never copies or resets auth.

## Publication provenance and cleanup

Execution helpers for the final wheel controls were committed in `c4354a9c`. Later changes only add the offline
wheel-byte verifier and split exported JSON into smaller case files. The exporter and verifier are not part of hook or
reviewer execution. Earlier captures used earlier product/helper bytes: every run retains its revision, dirty diff hash
where `FORGE_DEV` applied, and source snapshot. Wheel captures instead use
[explicit installed-wheel provenance](product/wheel-provenance.json) and their hook-side module paths.
[harness-snapshots.json](harness-snapshots.json) lists every mismatch and added helper against the publication tree; no
earlier capture is relabelled as a run of the final sources.

The initial TUI helper failed on the legitimate `supervisor: null` result. Its interrupted child lacked a saved native
thread ID, so the successful control used a separate child; both failed attempts remain indexed. Codex also incremented
a `[tui]` notice counter: product enrollment now excludes that presentation table while keeping other configuration,
exact definitions and the executable fingerprint. A new enrollment turn verified the revised identity.

`b4-product.py`, `b4-tui-child.py`, `b4-fault.py`, `b4-real-review.py`, and `b4-wheel.py` own the product controls.
`b4-verify-product.py` validates retained assertions without inference; it does not reconstruct historical exit codes.
`b4-export.py` owns redaction/publication and `b4-close.py` owns teardown. All are included in
[helper-sources.json](helper-sources.json), alongside the gate helpers and stub-admission checker.

Teardown found no live recorded processes and removed only the fixture's Codex login. The retained package and private
captures remain available; the closed round cannot launch another probe. Recorded host config hashes matched, which says
nothing about remote token validity or revocation. The real Claude login belongs to the operator and was preserved.
