# B3 validation and provenance

## Source and artifact identity

The main feedback implementation is `2cb840ed`. Capture helpers were committed before their final uses in `c819f9f2`,
`bd9e71dc`, `b4502b7e`, and `d2a537ea`. The current-login compatibility fix is `9ea12b6a`. PR review corrections are
`fb26b011`; the delayed-terminal probe repair is `ab055ede`. Per-case `command.forge_revision`, source-diff hash, and
`command.harness_files` preserve the actual capture facts. Wheel commands have no `FORGE_DEV` and therefore no
checkout-revision claim; their retained wheel hashes, recorded launcher, doctor result, and hook-side module paths
identify the installed artifact.

The initial wheel predates the login compatibility fix. Its three controls remain in the index as historical evidence;
`wheel-final-*` repeated them on `9ea12b6a`, and `wheel-review-*` repeats them on `fb26b011`. The review wheel SHA-256
is `f73b829b96dfbde45ed2d360b8d1903e6ff0635de14191412c289c1f29886e8d`. All sets use the same enrolled homes and stable
dispatcher command. The helper temporarily points `runtime.json` at the selected wheel launcher and restores its
original bytes in `finally`. Registration, dispatcher, and trust configuration hashes agree before/after.

The launch identity records the quota wrapper actually selected by Forge. That wrapper separately verifies the retained
native Codex executable's SHA-256 before launch and the outer owner checks it again after the run. Do not mistake the
wrapper hash for the native executable hash. The editable checkout still reports package version 1.0.2, so provenance
uses the Git revision/module path, not `forge --version` alone.

## PR review corrections

`fb26b011` preserves the selected launcher basename and resolves relative PATH entries against the child worktree. Only
fingerprinting resolves symlinks, and hashing streams the executable. Failed version checks still launch the selected
path. Headless and TUI regressions exercise Volta/mise/aqua-style symlinks with successful and failed probes; bridge
fixtures use their own executable and assert identity stamping instead of reading the host binary.

Schema-2 identity ties a hook's invoking process to the recorded Forge launch parent. The inherited record therefore
does not admit an independently nested Codex; Claude children also discard it. The OS-process regression uses synthetic
runtime versions, not a real older Codex binary. Forking wrappers, extra shell process layers, failed parent lookup, and
old schema-1 records suppress new model/operator fields conservatively; launch and the existing deny wire still work.
This is compatibility admission, not an authentication boundary. The live review controls exercise the normal direct
dispatcher chain with schema 2.

Blocking output again carries the full shared project-owner note or unresolved-review guidance. Resolved tier-1
escalations stay in audit without labeling the final allowed action unreviewed. Source-only stop-and-ask text belongs
only to an unquoted reviewer finding, not a deterministic rule or verified quotation. The regression exercises actual
`codex-policy-check` stdout, including the absence of an explicit allow decision.

The review TUI attempt `tui-review-combined` pasted after a fixed eight seconds while Forge was still starting; no
policy hook or action ran. It exited 125 with an empty descendant sweep and counts against the turn budget. `ab055ede`
waits for Codex's bracketed-paste terminal mode before the resume-settling delay. A real-PTY regression covers delayed
startup and a readiness sequence split across reads. The retry is retained separately as `tui-review-final`.

The first review regression run had 1,439 passes and one B1 deadline-fixture failure; the isolated rerun reproduced it.
Cold version/help admission consumed the one-second budget before dispatch. The repaired test admits its local stub
before timing format negotiation, asserts both dispatch attempts in each fresh process, and checks their shared
two-second deadline. No product timeout was changed or failing test skipped.

Review validation used product code `fb26b011` and harness/test repair `ab055ede`:

| Gate                                               | Result                                                                                                                   |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `COLUMNS=200 make test-unit`                       | 10,640 passed; 117 integration tests deselected                                                                          |
| `COLUMNS=200 make test-regression`                 | 1,441 passed after the fixture repair                                                                                    |
| Targeted Docker hook and manual-policy integration | 32 passed                                                                                                                |
| Docker auth-isolation, explicit Claude 2.1.291     | 2 passed, no inference; the image failure was subsequently diagnosed below                                               |
| `make build`, fresh clean wheel install            | Passed; source/off/deny use the review wheel identified above                                                            |
| TUI and wheel review replays                       | Four passing schema-2 controls; one earlier TUI setup failure retained                                                   |
| Evidence verifier                                  | 16 selected controls passed: 12 historical captures and four review replays; the prior single real review remains usable |
| Full `make pre-commit`                             | Passed, including types, links, formatting, sizes, and secrets                                                           |

The [initial assertion report](verification-initial.json) remains unchanged. The latest [report](verification.json)
records each selected case's identity schema. Neither report implies that historical schema-1 captures exercised the new
process check. The review replays consumed the remaining five reservations, including the failed TUI setup, for **32/32
Codex turns**. There was no additional real Claude inference during those review replays. The later Docker follow-up
below records the two separately authorized Haiku API cases.

The host configuration comparison failed on the first review verification attempt. Host `config.toml` now differs from
the 14:57 baseline; its recorded modification time is 17:12:33 +02:00, before the review replays began at 19:33. The
cause is not established, and the host file was not restored. Host `hooks.json` remains absent. The verifier now records
both hashes and modification time separately from product assertions instead of stopping before publishing them. The
initial 16:11 verification's unchanged-host result remains dated evidence; no unchanged-host claim is made for the full
extended round. Isolated fixture registration/trust hashes still agree before and after the wheel runs. This
reporting-only verifier change post-dates the live captures and is included in the published helper inventory.

## Helper changes and earlier attempts

[Helper sources](helper-sources.json) lists the final publication inventory. Per-capture inventories remain separate;
they are not rewritten to pretend every historical file matched the final tree.

- Enrollment preparation predates `2cb840ed`. The first TUI attempt did not forward keys correctly and was terminated
  with exit `-15`; the descendant sweep was empty afterward. `enrollment-2` completed the real trust ceremony and its
  `--verify-enrollment` receipt confirms SessionStart delivery. Both attempts and the verification turn count against
  the budget. No hook-trust bypass was used.
- The initial `tui-off` capture proved delivery but needed separate operator Escape/EOF keys to close. The driver now
  separates those keys in time, with a real-PTY regression. `tui-off-final` and `tui-combined` use that committed fix
  and exit automatically. The original capture is retained, including its operator-key record.
- `real-claude` and `real-claude-final` were setup refusals: the helper initially omitted the explicit Sonnet lane, then
  selected the direct backend instead of `claude-max`. `real-claude-quote` was refused before inference because the CLI
  was not logged in and its metadata lacked the legacy personal-account field. These records say unavailable, with zero
  dispatches; they are not failed model turns or quote-quality evidence. The guard correction plus user login enabled
  `real-claude-authenticated`, whose global exclusive dispatch marker prevents a second inference attempt.
- The observer, stub reviewer, and `b3-run.py` used by the product captures retain their capture-time hashes. The
  model-only arm uses a separate, explicitly mutating observer; it saves the original product wire before removing
  `systemMessage`. It does not masquerade as the observation-only path.
- Publication changed from one large JSON file to one file per case. Later exporter/verifier edits select the measured
  native metadata tag, include operator terminal bytes and final artifact records, and narrow host-state claims.
  Raw-file manifests pair explicit `path` and `sha256` fields so keyboard-event filenames cannot make their digests look
  like API keys to the secret scanner. These edits do not rewrite runtime behavior. The exporter and verifier are
  committed source, and originals retain independent SHA-256 hashes. No private uncommitted export/cleanup/admission
  helper owns the published results.

The initial standard-runner attempts lacked Docker and then `uv` on the clean PATH; both failed before pytest/model
dispatch. Adding `/usr/local/bin` and `/Users/habib/.local/bin` after the stub/retained-binary directories let the
normal runner operate. No API credential was added. Docker's expected no-Gemini warning is irrelevant to the selected
tests; API-inference reviewer tests were deliberately not selected.

## Commands and gates

Use the owned launcher created by [`b3-fixture.py`](../../../../../scripts/experiments/codex-hooks/b3-fixture.py),
followed by an independent device login, user-scope hook enrollment, and
`forge runtime preflight codex --verify-enrollment --json`. Preserve the resulting `ENROLLED` marker; `b3-run.py`
refuses changed trust configuration. Stub reviewer admission is version/flag compatible; the timeout capture includes
its actual dispatch-start marker.

The live integration command used the clean launcher, the Docker socket, and the explicit PATH additions above:

```bash
scripts/test-integration.sh tests/integration/core/test_codex_policy_feedback.py -x
```

It passed both TDD and stub-supervisor cases. The remaining product arms use
[`b3-run.py`](../../../../../scripts/experiments/codex-hooks/b3-run.py) with distinct labels. The source-only arms share
a fresh seeded thread, with a new private source/prose marker on each turn; the off arms use a separate fresh thread.
The latest wheel helper uses `--prefix wheel-review --installation wheel-env-review --wheel-directory wheel-review`,
with `FORGE_DEV` removed and the installed wheel's Python/Forge first on PATH. The single real review uses
[`b3-real-review.py`](../../../../../scripts/experiments/codex-hooks/b3-real-review.py) and the user's real Claude login
home, keeping private Forge telemetry and stripped auth selectors.

The final replay-only assertion/export commands are:

```bash
"$ROUND/run" "$CHECKOUT/.venv/bin/python" "$CHECKOUT/scripts/experiments/codex-hooks/b3-verify.py" \
  --real-case real-claude-authenticated --wheel-prefix wheel-review --tui-combined-case tui-review-final
"$ROUND/run" "$CHECKOUT/.venv/bin/python" "$CHECKOUT/scripts/experiments/codex-hooks/b3-export.py" \
  "$ROUND" "$CHECKOUT/docs/board/doing/codex_policy_warnings/evidence"
```

Initial publication checks used product source at `9ea12b6a`, plus evidence and the test-only repairs described below.

| Gate                                                                        | Result                                                                                                 |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `COLUMNS=200 make test-unit`                                                | 10,640 passed; 117 integration tests deselected                                                        |
| `COLUMNS=200 make test-regression`                                          | 1,416 passed                                                                                           |
| Targeted Docker hook, manual-policy, auth-isolation, and old-reviewer tests | 33 passed; 2 auth-isolation cases failed before Forge admission because Claude 2.1.294 could not start |
| Auth-isolation replay with `FORGE_AUTH_TEST_CLAUDE_VERSION=2.1.291`         | Both metadata-generation cases passed; synthetic auth only, no inference                               |
| Trusted Codex integration                                                   | 2 passed on `2cb840ed`; final wheel repeated source-only/off/deny after the auth fix                   |
| `make build`, clean wheel install, final wheel controls                     | Passed; artifact identity is in `wheel-final-verification.json`                                        |
| Evidence verifier                                                           | All 16 selected controls and the single real quotation check passed                                    |
| Full `make pre-commit`                                                      | Passed, including types, links, sizes, formatting, and secrets                                         |

The Docker command was:

```bash
env -i HOME="$HOME" PATH="$PATH" PYTHON_DOTENV_DISABLED=1 COLUMNS=200 \
  ./scripts/test-integration.sh \
  tests/integration/docker/test_policy_hooks.py \
  tests/integration/cli/test_policy_cli_contract_integration.py \
  tests/integration/docker/test_supervisor_auth_isolation.py \
  tests/integration/docker/test_reviewer_compatibility.py::test_old_blocking_pin_refuses_without_inference
```

The exported image's Claude 2.1.294 Linux ARM executable crashed with a Bun bus error on `--version`, before the failing
auth cases could exercise Forge. A network-disabled direct reproduction exited 135; its
[startup output](linux-claude-version.txt) is retained. The explicit test-only version override installed 2.1.291 for
those two cases; it is not an automatic fallback or product pin. The reproduction and replay commands were:

```bash
timeout -k 3s 20s docker run --rm --network none --entrypoint /bin/sh \
  forge-claude-test:2.1.294-codex-0.162.1 -c 'uname -m; claude --version'

env -i HOME="$HOME" PATH="$PATH" PYTHON_DOTENV_DISABLED=1 COLUMNS=200 \
  FORGE_AUTH_TEST_CLAUDE_VERSION=2.1.291 \
  ./scripts/test-integration.sh tests/integration/docker/test_supervisor_auth_isolation.py -s
```

That replay established auth-setting isolation on Linux with 2.1.291 only; it did not establish a general 2.1.294
compatibility failure. The actual macOS 2.1.294 subscription review passed. No test was skipped to stand in for either
result. The later image investigation below corrects the earlier diagnosis.

Earlier failures were repaired rather than skipped: launch mocks assumed the literal `codex` basename, the environment
inventory lacked the new internal key, and B2's historical explicit-allow fixture imported the now-corrected product
helper. That fixture now emits its dated shape literally. An existing session-display assertion failed when Rich wrapped
`file missing` across lines as temporary paths grew; its two presence/absence checks now normalize whitespace. The next
unit run had 10,639 passes and one link-check failure because new evidence files were not staged yet. Staging the
complete publication resolves that candidate-Git-state check. Initial pre-commit failures were Markdown formatting and
the two SHA-256 false positives addressed by explicit hash fields above.

The real quote-quality check is a single controlled example, not a reliability estimate. It returned two exact
quotations, with raw response, reviewed snapshot digest, verified offsets, actual `claude-sonnet-5-5` model, and
subscription telemetry retained. Failed auth/config setup did not consume an inference retry. General account billing
and quota exhaustion are not inferred from this result.

## Docker image repair

The reported installer failures shared a crashing executable, not a missing Claude installation. In the exported
`forge-claude-test:2.1.294-codex-0.162.1` image, Claude was 213,909,504 bytes; a fresh installation of the same 2.1.294
package was 252,108,792 bytes and started successfully. The first differing byte was 100,663,297, where the exported
file began returning zeros. Its SHA-256 was `3d700099759f2ad80e936440b612831c0fb6836c645344b80bf744b8ed13b608`; the
working installation and repaired export both had SHA-256
`e5d2df19f30a6d63bf11188121f7edb2775249b57352a69269509a4b1496e763`. The repaired export's
[size, hash, and startup output](linux-claude-repaired.txt) are retained beside the original failure.

Rebuilding the npm toolchain without cache passed the in-build version check but reproduced the broken export. A fresh
install followed by `cp --reflink=never`, replacement of the launcher, and `sync` preserved the working bytes through
export. The Dockerfile now applies that combination. These experiments do not isolate copying from flushing as the cause
of success or establish a general Docker hardlink defect. Neither runtime version nor product admission changed.

Both integration entry points now check CLI startup in the exported image without networking or mounted credentials.
Failures retain the exit status and CLI output, stop before shared infrastructure or tests, and name the rebuild path.
The shell runner also uses pytest's dirty-content fingerprint; its former constant `-dirty` suffix could reuse an image
after further uncommitted fixes. Eight regression cases cover healthy/crashing/missing runtimes, timeout cleanup, cached
and newly built image refusal, and dirty-cache invalidation before the shell guard.

The two inherited-auth cases passed on Claude 2.1.294 using the user's explicit exception for two Haiku API calls. They
ran once with `--reruns 0`, with only the Anthropic credential in the clean child environment; dotenv and other provider
credentials were disabled. Their `slow` marker keeps the default fast lane from starting paid inference. These calls are
separate from the single subscription quote-quality review. The Codex round remains at 32/32 turns, and no additional
Codex or Jev inference was run.

The affected Docker files passed **31 tests**: 29 without inference, then the two authorized API cases. This includes
all reported failures, both exact-wheel checks, and both auth-isolation cases on 2.1.294 without a version override. The
default `GEMINI_API_KEY` warning was expected; these cases do not use LiteLLM. No selected case was skipped or
automatically retried.

```bash
env -i HOME="$HOME" PATH="$PATH" PYTHON_DOTENV_DISABLED=1 COLUMNS=200 \
  ./scripts/test-integration.sh \
  tests/integration/docker/test_installer.py \
  tests/integration/docker/test_qa_release_artifact.py \
  tests/integration/docker/test_walkthrough_release_artifact.py \
  tests/integration/docker/test_supervisor_auth_isolation.py \
  tests/integration/docker/test_reviewer_compatibility.py \
  -m 'integration and not slow' --reruns 0

# Separate authorized run: clean child environment with ANTHROPIC_API_KEY only.
# The secret was passed in the process environment, never command arguments.
./scripts/test-integration.sh \
  tests/integration/docker/test_reviewer_compatibility.py::test_inherited_auth_settings_can_complete_read_only_review \
  --reruns 0 -v
```

The paid run used exported image `sha256:a27217291bfdac2915ee1b4dea4ed9bbf7add5c034f3d1185aa76d7b61f89662`, labelled
`b5c1e18894585e2da52bc79bd45f2e199aef36fd-dirty-de9a51c47ac3`. The product source was unchanged from `b5c1e188`; the
dirty tree contained the Docker/test repair. The later documentation edits were not part of the image. All fixture
containers were removed after the runs.

The aggregate regression suite passed 1,449 tests. The first unit run passed 10,638 tests and caught two documentation
integrity checks while this evidence was still being added: an unstaged link target and the design document's old
token-count hash. The evidence was staged and the required count refreshed before the final run. Initial pre-commit
failures were that stale cache and Markdown formatting; no code check was bypassed.

The final `COLUMNS=200 make test-unit` rerun passed **10,640 tests**, with 117 integration tests deselected. Full
`make pre-commit` passed after the cache and formatting fixes. Together with the 1,449 regressions and 31 affected
Docker cases, this completes the integration follow-up gates.
