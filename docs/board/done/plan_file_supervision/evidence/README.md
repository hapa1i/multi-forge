# B1 verification, 2026-10-07

This evidence belongs to [B1](../card.md), on `feat/plan-file-supervision` after the documentation partitions at
`6529ff38`. The [merged closeout](../checklist.md#merged-closeout) records final verification and PR coordinates; B1
closed to `done/` on 2026-10-08.

The [2026-10-08 review correction record](2026-10-08-review-fixes.md) supersedes the version-admission, manifest-write,
and shadow-format statements below. This page preserves the original test results and dated runtime observations.

## Runtime and billing evidence

Versions: macOS host; Claude Code **2.1.291**, Codex **0.160.1**, Docker **29.8.2**. Docker native tests use explicit
API credentials in disposable identities. They do not demonstrate subscription billing. Codex enrollment recreates the
existing trusted hashes at the original absolute paths through `tests/fixtures/codex_enrollment.py`; it copies no
`auth.json` and does not reenroll the host.

The user confirmed account usage credits were disabled before the sole real-host subscription scenario. The
[compatibility capture](2026-10-07-read-only.json) and [production capture](2026-10-07-production-host.json) retain only
selected non-secret metadata and assertions. No invoice or quota decrement was measured.

The fixture was created by a separate direct subscription turn in `<probe-root>/planner`, with successful `Read`,
`Edit`, and harmless `Bash` calls. A Git worktree at `<probe-root>/executor` contained a different sentinel. The first
compatibility review resumed and forked the real UUID from the planner CWD with `--add-dir <probe-root>/executor`;
fixture creation was not counted as that probe. A fresh review followed. Both exposed exactly `Read,Glob,Grep`. The
resumed model actually attempted two `Edit` calls and one `Bash` call, which the runtime rejected as unavailable. Both
reviews read the executor sentinel, preserved the planner history, and left tracked/untracked checkout contents
unchanged. Permissive settings, CLAUDE.md, hooks, and an MCP write canary existed in both directories; none executed.

Production `run_supervisor_check` then completed fresh and resumed reviews in 5.17 and 6.12 seconds. Both recorded
`subscription_quota`, requested `sonnet`, and completed attempts. The compatibility stream observed `claude-sonnet-5-5`;
production now records observed model IDs separately when the runtime supplies them. Protected settings digests and
account identity matched afterward, and the same login remained usable. Ordinary CLI caches and organization metadata
refreshed; this is not a claim that every byte of `.claude.json` remained unchanged.

## Auth matrix and limits

[The auth capture](2026-10-07-runtime.json) from `test_supervisor_auth_isolation.py` uses a trusted Linux project,
disposable HOME, synthetic environment/dotenv/Forge credentials, permissive settings, and `apiKeyHelper`. Its positive
control reports the paid source; the cleaned child reports no login, calls no helper, and refuses before inference.
Active/default profiles, managed settings/MCP, server settings, gateway/cloud selectors, and alternate config paths are
rejected. The same final environment and binary are used for status and dispatch; it is not rebuilt after preflight.

Stored Console credential and expired/quota responses have test-double coverage, not a deliberately expired real
account. No separate macOS user/VM was available to prove alternate-Keychain isolation. Consequently B1 refuses
alternate Claude config directories, profile/managed/gateway cases, and unverified personal-account metadata. It admits
only the tested personal Pro/Max CLI-managed login on the pinned Claude version. No host logout, credential copy,
profile switch, or administrator-path mutation was performed. Parent-key stripping/hydration compatibility has unit and
Docker coverage; the successful real-host production calls had no parent API key.

## Enforcement and lifetime evidence

`test_native_plan_supervision.py` tests real aligned and divergent actions with both reviewer runtimes, including host
Claude `Write` and `Edit`, and Codex `apply_patch`. Assertions use both durable verdicts and actual file effects. A
separate Codex control writes with `workspace-write` and preserves the file with `read-only`. Docker's default seccomp
blocks Codex's bubblewrap user namespaces even with hooks disabled; the disposable test container therefore permits
those syscalls so Codex's own filesystem sandbox can run. It has no host filesystem mounts or privileged capability
grant. Tests do not bypass the reviewer's sandbox or use an authority marker to obtain read-only behavior.

The hook-timeout suite instruments only the disposable dispatcher's body, retaining registered command/timeout bytes. It
uses plain sleeping reviewer/grandchild processes as the baseline, then the independent watchdog under natural expiry,
hook-only SIGKILL, and hook-group SIGKILL. The reviewer ignores TERM. Traces at the nominal 60-second expiry show Claude
sending group TERM then KILL, and Codex sending hook PID/group KILL. The watched reviewer group receives TERM followed
by KILL after about 0.5 seconds, with no surviving reviewer or grandchild. Both runtimes can proceed with the requested
tool after hook failure. Some Codex runs, including the combined suite above, cancelled the turn before 60 seconds; the
separate traced natural-expiry capture reached 60 seconds and allowed the patch. Early-cancelled turns left the patch
unapplied and no reviewer alive; those runs are not used as proof of natural hook expiry. The test permits the bounded
cleanup grace after executor exit before declaring an orphan. macOS process tests additionally kill the watchdog itself
and verify the independent anchor deadline.

Production keeps the unchanged 60-second registrations, a 55-second whole-hook budget, a 1-45-second frontier limit, and
a 15-second checker limit. Files, auth checks, cascade stages, and format retries share the remaining deadline. An
interrupted hook leaves a durable start, projected as incomplete without inventing a verdict, usage, or zero cost.

## Verification commands

- Three defect reproductions fail against the pre-implementation tree `6529ff38`: unchanged-size/mtime plan content,
  unrestricted resumed review, and the second full retry timeout. They pass with B1.
- `make test-regression`: **1,335 passed**.
- `make test-unit`: **10,594 passed, 117 deselected**. Earlier token-cache and untracked-evidence link failures were
  corrected before this final run.
- `./scripts/test-integration.sh tests/integration/docker/test_native_plan_supervision.py tests/integration/docker/test_plan_file_supervision.py tests/integration/docker/test_supervisor_auth_isolation.py -q -s`:
  **19 passed**, including eight native enforcement/sandbox cases and eight lifetime cases.
  [Sanitized capture](2026-10-07-runtime.json).
- `./scripts/test-integration.sh tests/integration/docker/test_real_authority.py tests/integration/docker/test_supervisor_e2e.py tests/integration/docker/test_real_claude_supervisor.py tests/integration/cli/test_policy_cli_contract_integration.py tests/integration/sidecar/test_sidecar_hook_inject.py -q`:
  **22 passed**, including the authority suite using the extracted trust fixture.
- `make build`: wheel and sdist built. A clean installation without `.env` passed project extension setup, plan-only
  set/status/off/on/reload, all four consumers' lane set/show/clear, activity JSON, coding-standards file/diff checks,
  API/subscription/proxy billing controls, and a packaged watchdog subprocess.
- `make pre-commit`, Markdown links, token-cache refresh, and `git diff --check` pass. No final failures or skips remain
  in these runs; integration markers are deselected by the unit target.

Schema v3 reads v1/v2 without rewriting; the next write upgrades the manifest. Existing frozen `claude-max` bindings
keep inherited auth. New opt-in or frozen model/effort changes require remove/reconfigure. Older or incomplete shadow
records become unavailable without dispatch. Optional source-only feedback is deferred to B3. Shell writes and
deletion-only Codex patches remain outside the existing adapter's supervision boundary.

[Content-matched Opus counts](2026-10-07-document-counts.json) put every touched living design below 25,000 tokens;
`docs/end-user/session.md` is 24,981. Historical completed-card warnings are unchanged.
