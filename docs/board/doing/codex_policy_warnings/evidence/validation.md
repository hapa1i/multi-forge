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
| Docker auth-isolation, explicit Claude 2.1.291     | 2 passed, no inference; the 2.1.294 Linux limitation below remains                                                       |
| `make build`, fresh clean wheel install            | Passed; source/off/deny use the review wheel identified above                                                            |
| TUI and wheel review replays                       | Four passing schema-2 controls; one earlier TUI setup failure retained                                                   |
| Evidence verifier                                  | 16 selected controls passed: 12 historical captures and four review replays; the prior single real review remains usable |
| Full `make pre-commit`                             | Passed, including types, links, formatting, sizes, and secrets                                                           |

The [initial assertion report](verification-initial.json) remains unchanged. The latest [report](verification.json)
records each selected case's identity schema. Neither report implies that historical schema-1 captures exercised the new
process check. The review replays consumed the remaining five reservations, including the failed TUI setup, for **32/32
Codex turns**. There was no additional real Claude inference.

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

Claude 2.1.294's Linux ARM executable crashed with a Bun bus error on `--version`, before the failing auth cases could
exercise Forge. A network-disabled direct reproduction exited 135; its [startup output](linux-claude-version.txt) is
retained. The explicit test-only version override installed 2.1.291 for those two cases; it is not an automatic fallback
or product pin. The reproduction and replay commands were:

```bash
timeout -k 3s 20s docker run --rm --network none --entrypoint /bin/sh \
  forge-claude-test:2.1.294-codex-0.162.1 -c 'uname -m; claude --version'

env -i HOME="$HOME" PATH="$PATH" PYTHON_DOTENV_DISABLED=1 COLUMNS=200 \
  FORGE_AUTH_TEST_CLAUDE_VERSION=2.1.291 \
  ./scripts/test-integration.sh tests/integration/docker/test_supervisor_auth_isolation.py -s
```

This establishes auth-setting isolation on Linux with 2.1.291, not 2.1.294. The actual macOS 2.1.294 subscription review
passed. No test was skipped to stand in for either result.

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
