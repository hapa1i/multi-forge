# B5 merged closeout verification

2026-10-13: [PR #265](https://github.com/hapa1i/multi-forge/pull/265) merged as `de3efca8`, with the same tree as tested
head `e222c575`: `e2e6b529d8a652dfcb2c0d882364a7442ecf93fe`. All five PR checks passed.
[Merged-main CodeQL](https://github.com/hapa1i/multi-forge/actions/runs/38421774043) also passed both analyses. The user
requested closeout and commits on `main`. Reviewed follow-ups still local at merge were carried intact onto that tree
and committed separately as `f0d1d52c` before the board closeout.

## Final source validation

| Check                                          | Result                                                                          |
| ---------------------------------------------- | ------------------------------------------------------------------------------- |
| `make test-unit`                               | 10,774 passed; 117 integration cases deselected                                 |
| `make test-regression`                         | 1,618 passed                                                                    |
| Targeted integration runner below              | 16 passed; no native inference cases selected                                   |
| `make pre-commit`                              | All hooks passed, including lint, types, secrets, size and Markdown links       |
| `make build`                                   | Wheel and source distribution built                                             |
| Clean installed wheel                          | 66 offline tests passed; 386 Forge Python files and eight bundled scripts match |
| Deterministic policy CLI, file and diff inputs | Both passed for `coding_standards`                                              |

The board audit confirms all B1-B5 members are done, with no open B5 or epic checklist items. The Markdown link audit
passes for 666 source files; historical captures and earlier changelog entries are preserved.

The integration runner used Docker and production invoker/watchdog code with explicit local stub reviewers:

```bash
PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh \
  tests/integration/core/test_codex_fork_supervisor.py \
  tests/integration/docker/test_plan_file_supervision.py::test_plan_only_configuration_and_hook_review \
  tests/integration/core/test_codex_stop_ignores.py \
  tests/integration/core/test_codex_stop_recovery.py -q --tb=short
```

The [wheel report](closeout-wheel.json) records the candidate and source hashes. A clean Python 3.13 environment
resolved dependencies from wheel metadata, independently of `uv.lock`. Tests and fixtures were copied outside the
checkout; Forge imports came from the installed wheel. The selected files were `test_bug_b5_api_home_claim.py`,
`test_bug_b5_dispatcher_native_predicate.py`, `test_bug_b5_direct_help_json.py`, `test_bug_b5_reviewer_contention.py`,
`test_codex_reviewer_home.py`, and `test_native_supervisor.py`. They cover publication ownership, dispatcher admission,
JSON help and refusal before mutation, lease deadlines, immutable copied inputs, and configuration/recovery. This used
synthetic credentials and histories, without native/API starts.

## Evidence and scope disposition

- Live product evidence remains at `1b0f01cf`; the later executor admission, queueing, lifecycle and CLI repairs have
  deterministic, process, integration and installed-wheel coverage. They have no repeated native inference claim.
- The approved macOS Codex 0.162.1 executable and source envelope remain enforced: exec-origin paginated source, tested
  instructions/model/auth, at most one fork generation, 1,827,328 copied bytes and 163,002 reported context input
  tokens. Separate TUI/long executors use bounded header identity; this does not admit TUI planning sources.
- Separate completed sources support PreToolUse. Shared/active sources require Stop, an approved plan and a verified
  boundary. Source copies identify input, not complete retained model context; shared ancestry has reduced independence.
- One independently obtained subscription login remains serialized within existing deadlines. Contended acquisition
  preserves the measured remaining-time floor, including after a successful late retry. API homes acquire ownership
  before exposing their marker. Readiness never acquires a lease or blocks structural policy disable/reset.
- B1-B4's live qualifications remain: quota exhaustion is not empirically verified; B4 cancellation was not repeated
  natively after its cleanup repair. The earlier unexplained ordinary Codex config hash change also remains unresolved.
  Automated failure-path tests do not replace those measurements.
- The native ledger remains **60/60 starts, 3/4 authorized API starts**. Both fixture logins were removed and the round
  was closed. No additional native turn, account login or paid probe ran for closeout.

The [epic closeout](../../epic_codex_supervisor/checklist.md#merged-closeout) reconciles the integrated outcome. The
session-execution, subprocess, workflow, telemetry and native-supervision user guides describe the shipped contracts. No
new implementation-note promotion was needed: the approved constraints already have normative homes.
