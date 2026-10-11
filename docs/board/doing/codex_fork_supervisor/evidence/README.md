# B5 runtime and product evidence

Product verification, 2026-10-11: [installed and clean-wheel evidence](product.json) completes the ledger at **60/60
native starts, 3/4 API starts**. Six product reviewers each emitted one attributed usage delta. Separate-source allow
and deny, active shared-source Stop with one correction, source-only feedback and global-ignore composition passed. The
[product report](product.md) records exact timing, wheel identity, scope and qualifications. No further inference is
authorized by the exhausted ledger. [Teardown](product-teardown.json) removed both fixture logins and copied product
inputs, verified process cleanup, and closed the private round. The earlier gate captures below remain unchanged.

At the gate handoff on 2026-10-11, the allocated runtime cases had run on retained **Codex 0.162.1**, on macOS. Product
implementation was gated on the subsequently approved [contract decision](../gate-decision.md). The captures establish
useful native context and candidate isolation controls, while exposing lifetime and accounting work omitted from the
original dispatch plan.

**Gate handoff: 48/60 starts reserved; 3/4 authorized API starts used.** The [ledger](ledger.json) includes failed
starts, setup, parents and reviewers. The remaining twelve P1/P2 product slots are recorded in
[product evidence](product.json). Before G14, the unused G0 setup slot was explicitly reallocated to the fresh-index
control; the total ceiling and API authorization did not change. A mistakenly counted `doctor --json` diagnostic remains
charged to G0. No Claude inference ran. The user confirmed extra usage is off and independently completed both fixture
logins. No ordinary Codex login secrets were copied.

The later [PR #265 review fixes](review-fixes.md) have separate validation evidence. Original live product captures
remain attributed to `1b0f01cf`; the closed native round was not rerun for those fixes.

## Results

| Concern                  | Observed result                                                                                                                                                                                                                                        | Evidence                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| Transport                | B2's argv composition passed; a 105,503-byte stdin prompt returned structured output. The large-prompt repeat combined actual argv observation with copied input, isolation and the candidate watchdog; no prompt text entered argv.                   | [Forks](forks.json), [ledger](ledger.json)                                  |
| Models/auth              | Both short-source model directions, subscription-to-API, API-to-subscription and one combined switch retained the source marker.                                                                                                                       | [Forks](forks.json), [ledger](ledger.json)                                  |
| Billing controls         | Root auth overrides were ignored by `exec`; `exec` overrides were ignored by `fork`. Leaf overrides plus ephemeral API credentials refused missing-key execution instead of using stored ChatGPT login.                                                | [Negatives](auth-negatives.json)                                            |
| Wrong stored auth        | Forced ChatGPT mode refused a synthetic API-only store and logged it out, deleting its dummy auth file. Ordinary-home reuse therefore has an ownership concern.                                                                                        | [Negatives](auth-negatives.json), qualifications below                      |
| Context                  | Repeated long/compacted reviews retained all three distributed markers. Two real compaction records survived, and the newer COBALT plan controlled.                                                                                                    | [Context](context.json), [forks](forks.json)                                |
| Hook ownership           | Depth-only controls changed the parent's observation receipt. Isolated G7 forks changed no project/global Forge files, emitted no native hooks, and stripped parent identity from reviewer subprocesses.                                               | [Forks](forks.json), [provenance](provenance.json)                          |
| Read-only/customizations | Patch/shell writes failed in source, action and outside directories; the writable control created all six files. The configured MCP server did not start. `agents.enabled=false` disabled delegation; feature flags alone left `list_agents` callable. | [Sandbox](sandbox.json), [ancestry](ancestry.json), G11 [forks](forks.json) |
| Copied input             | A complete copy loaded with its original unavailable. A paginated child alone failed without its copied ancestor; child plus ancestor loaded with both originals unavailable.                                                                          | G8/G11/R [forks](forks.json), [ancestry](ancestry.json)                     |
| Boundary                 | A newline-complete prefix with an unfinished tool call still loaded. Real PreToolUse also had a pending call. Real Stop had none and retained the current marker.                                                                                      | [Boundaries](boundaries.json), G8 [forks](forks.json)                       |
| Plan authority           | Current COBALT approval overrode inherited amber approval and unapproved LIME implementation reasoning, including through copied ancestry.                                                                                                             | G10/G11 [forks](forks.json)                                                 |
| Lifetime                 | The shipped watchdog left one detached native descendant for the outer harness to sweep. A cancellation-first experimental watchdog left none.                                                                                                         | [Lifetime](lifetime.json)                                                   |
| Usage                    | Terminal usage matched the inherited thread counter. Two short persistent controls and a compacted copied-source control matched new-turn usage to request records.                                                                                    | [Usage counters](usage-counters.json)                                       |
| Local admission          | The prototype admits the captured completed/Stop prefixes and refuses active PreToolUse, malformed ancestry and missing required plans. It performs no native dispatch.                                                                                | [Admission](admission.json)                                                 |
| Native indexes           | A reused index rejected the earlier Stop prefix as a shrunken rollout. G14 loaded the exact prefix with fresh SQLite state and unrelated copies held aside; old SQLite files were unchanged.                                                           | R/G14 [forks](forks.json), [ledger](ledger.json)                            |

The short-source model pair is `gpt-6.1-sol` and `gpt-6-sol`. The combined switch used a subscription-created
`gpt-6-sol` source and an API `gpt-6.1-sol` reviewer. This is route evidence, **not independently verified cross-account
compatibility**. Long, compacted and active cases used subscription `gpt-6.1-sol` only. No broader model, provider,
account, OS or version support follows from these cells.

## Context, timing and counters

The long source had 1,206,767 rollout bytes and last reported context input of 163,002 tokens. Native compaction
produced two `compacted` records; that source had 1,792,560 bytes and last reported input of 80,700. The reported
context window was 258,400, rather than the catalog's advertised size. Markers test selected retention, not every
original message or opaque model item.

| Case              | Native reviewer seconds | Raw terminal input | Raw cached input |
| ----------------- | ----------------------: | -----------------: | ---------------: |
| Long, first       |                   13.51 |            652,507 |          338,048 |
| Long, repeat      |                   13.88 |            652,507 |          501,120 |
| Compacted, first  |                   12.84 |            649,316 |          292,736 |
| Compacted, repeat |                   13.70 |            649,314 |          361,088 |
| Active PreToolUse |                   12.71 |            648,661 |          279,936 |
| Active Stop       |                   15.61 |            974,583 |          615,296 |

These are **raw native counters**, not newly incurred review tokens or billed amounts. One persistent fork reported
43,818 input tokens: its new requests used 29,560, and its parent contributed 14,258. Another reported 27,587 against
13,329 new input and the same parent baseline. The final compacted copied-source control reported 974,814 input tokens;
subtracting its 812,603-token source baseline gave exactly 162,211 new input. Cached-input and output deltas also
matched the new request records. The comparable source baseline came from
`event_msg.token_count.info.total_token_usage`. The source's older native thread counter was 1,056,476 input tokens and
was not a valid baseline for this reload. The child's terminal usage matched its own native thread counter. Missing or
incomparable counters remain unknown. No invoice or quota-charge assertion is made.

That last control loaded the refreshed 1,827,328-byte completed source in the second independently logged-in home, with
the original unavailable. All three markers and COBALT approval survived; both original and copy were unchanged.

The subsequent exact-Stop-prefix repeat exposed native index reuse: replacing the copied completed source with its
348-byte-shorter Stop prefix failed before `thread.started` with `durable rollout shrank before projection`. G14 used
the same independently logged-in home, a fresh `sqlite_home`, and only the selected source copy. It returned the current
Stop marker and all planning markers with COBALT approval in 16.65 seconds including fixture settling. Original and copy
were unchanged, no hooks ran, no child rollout persisted, and previous SQLite files were untouched. Unselected copies
and the original were restored. This is a replay of a captured live boundary, not an installed product Stop test.

The active cases used real registered callbacks and a checkout with 500 additional synthetic files. Stop setup/capture
used about 0.45 seconds, leaving 44.55 seconds after the 55-second internal deadline and 10-second completion reserve.
The watchdog received the absolute remaining deadline; the observer hook finished in 17.02 seconds. Source bytes stayed
unchanged while it blocked, then the parent completed. Stop evidence recorded `changes_without_observed_actions`: this
measures native boundary and capture cost, not B4's integrated action journal or product admission.

## Lifetime controls

G13 killed only the review owner after a real fork started `sleep 30`. The shipped watchdog left one descendant for the
outer fixture to sweep. The candidate requested SIGINT, allowed one second for native cleanup, then retained TERM/KILL
escalation. Its real native descendants were gone before the outer sweep. Observed processes included
`codex-code-mode-host` and a separate-session `sleep`.

A synthetic reviewer passed existing capability/subscription admission without credentials or inference. Timeout,
synchronous cancellation and owner death exercised sleeping descendants. Empty output, malformed JSON and exit-zero
quota-shaped events exercised the shared Codex invoker; a parsed stream envelope alone is not a semantic verdict.
Candidate timeout/cancellation passed too. Its first owner-death check waited only for reviewer/grandchild and sampled
the watcher during its grace period. The corrected repeat also waited for watcher/anchor and needed no outer sweep; the
earlier capture is retained as a harness qualification.

Two further local tests pass a real file-lock descriptor to the candidate guard and close it in the synthetic reviewer.
The lock remains held after owner death, including when the watcher is also killed, until the reviewer is gone. These
tests prove guard descriptor retention; product copy serialization and cleanup remain to be implemented.

## Provenance and limits

- [Provenance](provenance.json), [helper hashes](harness-snapshots.json) and [raw-source hashes](source-hashes.json)
  identify the executable, commands, Forge revision/diff, config and helper versions. Binary SHA-256:
  `74c6a6d263f40d65f99c27a815275f5b4ed0bcc2baecc396b4cf3255498bdfc0`. Product `src/` stayed unchanged from `0aca9c7e`.
  Intermediate untracked helpers have hashes but were not all in the captured Git patch; final helper contents were not
  used for every earlier case.
- [Preflight](preflight.json) predates inference. Later enrollment delivered all five hooks at 60 seconds. Its separate
  `stop_review_enrolled=false` is not product Stop verification.
- Dummy auth-file deletion was observed in this execution chat; exported stderr records logout and the raw fixture
  retains the missing file. No ordinary auth file was used. Remote refresh/account effects beyond subsequent successful
  fixture calls remain unknown.
- The missing-ancestor negative failed before a thread started. All held originals were restored. Copies identify
  selected bytes, not everything retained after native compaction.
- The legacy-executor reserve retry is **inconclusive**. It timed out before a tool started. The operator also
  overlapped its final source check with the copied-lineage quarantine, causing that check to fail. Originals were
  restored; no slot was refunded. This does not establish whether legacy execution fixes lifetime.
- [Preservation](preservation.json) records an ordinary Codex config hash change at 14:21:29 UTC after the 14:15:36
  initial snapshot. It contains no fixture path/B5 observer reference; the cause is unverified and it was left
  untouched. Ordinary hooks remained absent. Earlier prose claiming unchanged ordinary settings is superseded by this
  comparison. Ordinary login validity was not tested through another model call.
- Raw captures, retained package and independent homes remain in the open private round
  `/private/tmp/forge-b5-20261011-r1`. Credentials, opaque history, account IDs and account balances are not exported.
  Probe processes are cleaned up. Owned login teardown follows the eventual product/gate decision.

## Checks

Thirty-nine offline admission/harness/watchdog checks and seventy existing Codex invoker/stream checks pass. The first
local rerun could not execute `ps` in the outer sandbox; the authorized process-inspection rerun passed all 39. Four
targeted real-process Stop recovery/global-ignore integration checks pass with reviewer stubs through
`scripts/test-integration.sh`. Final pre-commit and board/link checks are recorded in the card's execution record before
commit.
