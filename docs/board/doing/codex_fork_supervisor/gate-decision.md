# B5 runtime gate decision for review

The [evidence](evidence/README.md) supports a bounded native-fork implementation on retained macOS Codex 0.162.1.
**Recommend proceeding after review of the dedicated login and trigger limits below.** The original plan cannot use
ordinary login state or the shipped watchdog unchanged, and cannot emit native terminal usage directly. This supplement
specifies the replacement contract. Product work has not started.

## Proposed contract

1. **Select immutable native input.** Copy the selected complete prefix and each paginated ancestor prefix it needs.
   Preserve native IDs/metadata and hash each artifact. Reuse rollout discovery; reject ambiguity, missing parents,
   cycles and unrecognized lineage. Initially admit a root or one fork generation; deeper paginated ancestry needs new
   native evidence. Bound total copied bytes and verify native ordinal/byte boundaries. Reject unfinished tool exchanges
   before inference. Do not import a rendered transcript.
2. **Own a dedicated reviewer home.** Subscription review uses an independently logged-in, Forge-owned reviewer home;
   setup must explain and verify that login. No copying/symlinking ordinary `auth.json`. API review uses an explicit
   child-environment key and ephemeral credentials. Restrictions go on the `fork` leaf; mismatches never fall back.
   Setup and lifecycle use the proposed commands and ownership below.
3. **Protect copied inputs for the whole attempt.** A bounded lease serializes source copies in a subscription reviewer
   home. The watchdog retains that lease if the hook dies until descendants are cleaned up. Contention means review
   unavailable, never overwriting an active input or spending twice. API attempts may use separate ephemeral homes. This
   is artifact ownership, not a second review budget. Give every attempt a fresh `sqlite_home`; a reused native index
   refused an earlier complete Stop prefix as a shrunken rollout. Stage only the selected ancestry in the reviewer home
   so background discovery cannot import unrelated copies.
4. **Use demonstrated trigger boundaries.** Recommend PreToolUse only for a separate source with complete, verifiable
   native history. Active/shared-executor review uses Stop and an approved plan. Admission verifies executor/turn,
   absence of pending calls and the captured prefix before selecting the copy. Unknown boundaries refuse before
   inference. Choosing Stop-only for the first release would require explicitly revising host-Claude/PreToolUse
   acceptance instead of quietly leaving it unimplemented.
5. **Cancel before termination.** Extend the shared watchdog with a Codex-specific SIGINT stage based on the
   experimental control. Preserve the independent deadline, parent-death handling, owned anchor, escalation and
   completion reserve. Product tests must include detached native tools and retained leases.
6. **Attribute new review usage once.** Terminal counters include source usage. Bind a comparable baseline to immutable
   input, preserve raw counters and emit verified new-turn usage through the existing invoker. Missing, decreasing or
   incomparable counters remain unknown. In the compacted copied-source control, the comparable source baseline was
   `event_msg.token_count.info.total_token_usage`; the source's `token_usage_record.thread_token_usage` differed. The
   child's terminal counter matched its own thread counter. Preserve those roles explicitly and add a regression for
   inherited-token double counting; do not infer invoice/quota changes.

The tested matrix covers the two short-source models and auth switches in the evidence. Long/compacted and active
admission initially covers subscription `gpt-6.1-sol` within the measured envelope. Unknown historical provenance,
larger contexts, other accounts/models/platforms/versions and executable-customization origins need refusal or further
evidence. Feature admission must not raise Forge's general runtime ceiling or release pin.

Copies identify selected input, not complete model retention. Preserve approved-plan precedence, reduced independence
for shared/unknown ancestry, no native verdict cache, no cascade/shadow, fail-open unavailable outcomes, and B4's single
dispatch/correction journal. Only verified approved-plan quotations may enter B3 source-only feedback.

## Proposed login and storage lifecycle

Add `forge policy supervisor auth login|status|logout --runtime codex`. The three leaves own a supervisor credential
store, distinct from a session's supervisor configuration. This is a proposed surface, not an installed command.

- `login` creates a marked, private `$FORGE_HOME/reviewers/codex/` and invokes native device login with file-backed,
  forced ChatGPT authentication. It requires the operator's extra-usage-off confirmation and records that as a user
  assertion, not a verified account setting. It refuses an unmarked or symlinked target. It does not enroll hooks or
  copy ordinary login state. Both fixture logins followed the equivalent native flow.
- `status --json` reads dedicated-store readiness without inference and reports the selected binary identity, auth
  route, confirmation state, ownership and lease availability. It exposes no credentials. Supervisor setup reports an
  actionable `auth login` command when this prerequisite is absent; hooks never initiate login.
- `logout` acquires the same bounded lease, invokes native logout only in the owned store and removes owned copied
  inputs. It refuses while a review holds the lease. Turning a supervisor off does not log out other supervisors, and
  logout does not delete configured sources or the ordinary Codex home.
- Each subscription attempt acquires the lease before copying. It removes only previous marked input artifacts, stages
  the exact source/ancestor closure, verifies its hashes, creates fresh per-attempt SQLite state, and retains ownership
  through watchdog cleanup. A failed or interrupted review leaves recoverable marked artifacts for the next lease
  holder. No existing lease is broken based on PID or elapsed time alone. API attempts use a fresh private home and the
  same cleanup rules, with a resolved API key supplied only through the child environment.

The independently logged-in account must match any recorded source ChatGPT account. Compare native metadata locally; do
not publish account identifiers in audit evidence. An absent account identifier does not establish cross-account
compatibility. Historical auth/model provenance that cannot be checked remains unsupported until a concrete admission
rule has evidence; do not infer it from the currently selected reviewer. The product gate must demonstrate useful setup
for real native sources, not only fixture manifests.

## Trigger and support decision

| Source/boundary                                          | Proposed admission                                                    |
| -------------------------------------------------------- | --------------------------------------------------------------------- |
| Separate completed source, host Claude or Codex executor | PreToolUse; approved plan optional only when independence is verified |
| Shared thread or shared ancestry, host Codex executor    | Stop with an approved plan and trusted current-turn boundary          |
| Separate source, host Codex executor at Stop             | Approved plan required by B4                                          |
| Active source at PreToolUse, unknown boundary, sidecar   | Refuse before inference                                               |

Start with the recorded model/auth cells and source formats. Short sources have both model directions and auth-route
switches proved. Long/compacted sources and active Stop have subscription `gpt-6.1-sol` evidence only. The largest
selected prefix measured was 1,827,328 bytes; the largest reported source context input was 163,002 tokens. These are
conservative admission ceilings for this round, not inferred model capacity. Keep the 1–45 second reviewer ceiling,
Stop's elapsed-time subtraction and 10-second completion reserve. A slow or unavailable review remains unavailable.

This preserves both trigger families without promising active PreToolUse support. Choosing Stop-only or admitting
deeper/larger sources would change the reviewed scope. The accepted
[checklist](checklist.md#proposed-contract-for-review) requires: “Record and review that scope decision before
implementation.”

## Gate evidence and product obligations

- The offline selector replays the real short, compacted and one-generation ancestry fixtures, recognizes the observed
  Stop payload/final answer, and refuses the unfinished PreToolUse prefix. Sixteen tests cover boundary mismatch,
  missing/ambiguous/cyclic ancestry, byte/ordinal disagreement, input limits, symlinks and missing required plans. See
  [admission evidence](evidence/admission.json). It is a prototype; trusted hook identity and race-resistant installed
  copy ownership still require product tests.
- Two real-process lease tests prove descriptor retention after owner death and after owner plus watcher death. The
  contender acquires only after the synthetic reviewer is gone. They do not replace the separate native detached-tool
  cleanup capture in [lifetime evidence](evidence/lifetime.json).
- The compacted persistent fork loaded a refreshed copy while its original was unavailable. Its terminal baseline delta
  exactly matched 162,211 new input, 80,896 cached input and 163 output tokens. Both source and copy stayed unchanged.
  Two short persistent controls also distinguish inherited counters from new turn usage. See
  [usage evidence](evidence/usage-counters.json).
- R's final start refused a Stop copy because the reused index had already projected a longer version of that thread.
  G14 then loaded the exact same prefix with fresh SQLite state and unrelated copies held aside. The current Stop
  marker, all three planning markers and COBALT survived. The old SQLite files were unchanged. This repeats a captured
  live Stop boundary; P1 must still test installed capture/copy/dispatch within the actual hook. See G14 in the
  [fork evidence](evidence/forks.json). `sqlite_home` is a documented control in the
  [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference); the native repeat, not
  the documentation alone, establishes this result.
- Implementation must integrate cancellation, immutable input leases, comparable usage baselines and dedicated login
  lifecycle through shared owners. Then P1/P2 must prove installed allow/deny, refusal, Stop composition and clean-wheel
  behavior. Experimental helpers and fixture stubs cannot satisfy those product acceptance items.

Keep B5 in `doing/`. Product, wheel, aggregate verification, PR and closeout remain outstanding.
