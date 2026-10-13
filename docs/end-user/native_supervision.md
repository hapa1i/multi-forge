# Review from a native Codex planning thread

Native supervision forks an immutable copy of a Codex planning thread for each review. It preserves native history,
including supported compaction records, and runs the reviewer in the action checkout with a read-only sandbox. An
explicit approved plan overrides recalled conversation instructions.

This opt-in mode has a narrow, measured support matrix. Ordinary Claude conversation review and fresh plan-file Codex
review keep their existing behavior. See [policy supervision](policy.md#semantic-supervisor-advanced) for those modes.

## Prerequisites

- macOS and the verified Codex 0.162.1 executable. Admission checks the executable hash, so another build or an update
  refuses native supervision even if it reports the same version. Forge's general runtime pin is unchanged.
- A host Claude or Codex executor; sidecars, cascade, shadow review and manual `supervisor evaluate` are unsupported.
- A completed source created by `codex exec` 0.162.1 with paginated history, the tested default instructions, OpenAI
  provider, recorded ChatGPT account identity and supported model history. TUI/app source histories, custom base
  instructions, unknown response formats and histories without account provenance refuse before inference.
- A root source or one native fork generation with its original ancestor present. Total selected history must fit
  1,827,328 bytes and its largest reported source context input must not exceed 163,002 tokens. These are measured
  admission limits, not model capacity promises.

These source limits apply to history copied into the reviewer. A separate managed Codex executor can be interactive and
have a larger transcript: Forge checks its identity and fork ancestry from bounded metadata headers, without reloading
its body. Executor ancestry checks accept at most 128 headers of 256 KiB each. This does not admit a TUI history as the
planning source. Configured `CODEX_HOME` and `FORGE_HOME` may be symlinks; links within the selected native store or
Forge-owned reviewer directories remain refused.

For short sources, use `gpt-6.1-sol` or `gpt-6-sol`, with `--supervisor-effort low`. Both source and reviewer model must
belong to this pair. Long sources (over 80,549 selected bytes), compacted histories and the active executor source
require subscription `gpt-6.1-sol` throughout their recorded model history. Larger/deeper sources need new compatibility
evidence; changing a limit locally does not establish support.

## Prepare a dedicated reviewer login

Disable extra usage in the ChatGPT account before running:

```bash
forge policy supervisor auth login --runtime codex --confirm-extra-usage-off
forge policy supervisor auth status --runtime codex --json
```

Complete the device login with the same account recorded in the source thread. Forge creates a private, marked
`$FORGE_HOME/reviewers/codex/` and uses its own independently obtained login. It never copies or links ordinary Codex
credentials. The flag records your assertion about extra usage; Forge cannot verify that account setting. Status is a
local readiness check without inference and exposes no credentials or account IDs.

All subscription reviewers sharing this Forge home serialize their use of that store. Reviews wait for its lease within
their existing review deadline; waiting reduces the time left for inference. An expired wait records unavailable review
without starting a model. Readiness checks do not require the lease, and status distinguishes `ready` from `busy`.
Login/logout refuse while the store is busy and advise retrying after completion. The lease survives hook death until
reviewer cleanup completes. Do not delete its lock file to bypass contention.

```bash
forge policy supervisor auth logout --runtime codex
```

Logout refuses an active lease, logs out only the dedicated store and removes its marked copied inputs. Supervisor `off`
preserves both configuration and the shared reviewer login. Removing a supervisor also leaves that login intact.

## Configure a separate completed source

From the executor session, name a managed session with confirmed Codex identity or give its full native thread ID:

```bash
forge policy supervisor set <planner-name-or-full-thread-id> \
  --source-runtime codex --runtime codex --model gpt-6.1-sol \
  --supervisor-effort low --auth-mode subscription-only
forge policy supervisor status --json
```

This defaults to PreToolUse. The source must be complete and independent of the executor. Each review resolves and
checks the original source again, copies only its selected ancestry, records prefix hashes and starts with fresh native
SQLite indexes. Missing, ambiguous, replaced, partly written or unfinished sources make review unavailable; Forge does
not select the newest matching thread or fall back to a rendered transcript. Managed-source setup does not adopt it.

Add `--plan ./approved-plan.md` to make a nonempty UTF-8 file authoritative. A configured file that becomes unavailable
does not fall back to the conversation. `%policy supervisor set` accepts the same setup options through shared
operations; login commands belong in the terminal.

## Review shared or active context at Stop

Shared thread IDs or recorded fork ancestry require a host Codex executor and an approved plan:

```bash
forge runtime preflight codex --verify-enrollment
forge policy supervisor set <planner-name-or-full-thread-id> \
  --source-runtime codex --runtime codex --model gpt-6.1-sol \
  --supervisor-effort low --auth-mode subscription-only \
  --trigger stop --plan ./approved-plan.md
```

Enrollment uses a native turn. Configure from a completed source before resuming it. When copying the active executor as
the source at Stop, Forge verifies its turn, final answer and complete native prefix. For a separate source, the
installed hook and Stop journal establish the executor turn, while metadata headers establish its identity and ancestry.
Unknown or unfinished source boundaries refuse before review. Every native Stop review requires a plan, including
separate sources, preserving Stop's existing plan gate and single review/correction journal. Stop reviews work already
performed; a correction is not a rollback or a second review. Shared context has reduced independence even when the
reviewer gets a new thread ID.

Each review reloads the selected history. Long sources therefore cost more input and can take longer, especially when
reviewing every edit. Consider Stop for a long separate source too. Reviewer timeouts remain 1–45 seconds; Stop also
subtracts evidence-capture time and a 10-second completion reserve from its 55-second internal hook budget. Registered
hooks remain at 60 seconds. A timeout is unavailable review, never an approval claim.

## Auth and billing

| Reviewer mode         | `inherit`                   | `subscription-only`                | `api`                                               |
| --------------------- | --------------------------- | ---------------------------------- | --------------------------------------------------- |
| Native Codex source   | Refused, including omission | Dedicated matching ChatGPT login   | Explicit Codex API key; short supported source only |
| Fresh plan-file Codex | Existing runtime auth       | Refused                            | Refused; use existing inherited API configuration   |
| Claude reviewer       | Existing direct/proxy auth  | Existing direct `claude-max` login | Refused; use existing inherited API configuration   |

For explicit native API review, configure `--auth-mode api` with `CODEX_API_KEY` in the environment or
`~/.forge/credentials.yaml`. Environment takes precedence and `.env` is unnecessary. Forge supplies the key only to a
fresh private child home, forces API auth and ephemeral credential storage, and removes competing provider/proxy
selectors. It does not fall back to a subscription login. Unknown source account provenance remains unsupported,
including API-created histories that omit it. API review is paid; authorize its use separately from subscription review.

Subscription children strip API keys and executor identities and force ChatGPT auth on the native `fork` command.
Neither route claims to measure invoice changes. `forge telemetry activity <session>` records each new review once.
Native terminal counters contain inherited history usage: Forge subtracts the selected source's comparable event
baseline and records both counters in attempt evidence. Missing, decreasing or incomparable counters remain unknown.

## Status, limits and recovery

- `status --json` separates native source identity, reviewer lane/model/auth, billing classification and latest attempt.
  In-session `%policy status` and `%policy supervisor` also show the native thread ID. Copied-prefix hashes identify
  selected input; they do not prove that the model retained every source detail.
- Native verdict caching, sticky fallback, alternate reviewers and retries are disabled. Quota errors, malformed output
  and unavailable sources remain visible fail-open outcomes. A valid high-confidence cited divergence blocks a pending
  tool; low confidence warns. Source-only feedback includes only quotations verified against an explicit approved plan,
  so conversation-only citations are not forwarded as approved quotations.
- Use `off`, `on`, `remove` and `reload --from <plan>` as with other supervisors. Active `on`/`reload` recheck admission
  before acquiring the session lock; a concurrent configuration change asks you to repeat the command. Generic policy
  set/reset validates configuration without requiring a ready reviewer, so unavailable login/source state cannot prevent
  `forge session set policy.enabled false`. Disabled policy also skips reviewer launch preflight. Source bindings
  require `remove` then `set`; frozen model/effort/auth changes do too. A failed replacement preserves the old
  configuration.
- Repair a missing original rollout or select another complete source. For a replaced binary, use the verified build or
  wait for a Forge version with new native evidence. Login cannot make an unsupported binary or source compatible.
- Interrupted subscription inputs are recovered by the next lease holder. Marked abandoned API homes are recovered by
  the next API attempt only after their lease is free; unmarked, unsafe or active stores remain untouched.
- Native source configuration requires manifest schema v5. Existing configurations keep their v2/v3/v4 encoding.
  Preserve a backup before downgrading to a Forge version without v5 support.
