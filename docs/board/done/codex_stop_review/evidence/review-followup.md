# B4 PR review follow-up — 2026-10-11

The original checklist did not explicitly cover lost Stop delivery, bounded recovery from incomplete carry, receipt
replacement, or inactive hook startup cost. Ten added regression cases failed against `62c06562` before the fixes. The
revised checklist names these acceptance cases; the original native captures remain unchanged.

Unfinished turns and work after an earlier approval now retain their prior baseline across prompts and thread changes.
Incomplete scope stays unreviewed, with carry capped at 32 recorded turns and an explicit `carry_limit` diagnostic.
`forge policy supervisor reset-review` previews an exclusion; `--yes` records it as unreviewed and requires a later
explicit prompt for a fresh baseline. The current allowance and the latest observed turn watermark survive resetting.
Git index stat refreshes and denied requests no longer manufacture evidence gaps.

Failed enrollment probes preserve the previous receipt; successful complete probes replace it atomically. The digest
binds hook definitions, trust and feature switches, including relevant profile settings. Unrelated model, MCP and TUI
preferences do not invalidate proof. Existing receipts from the initial B4 implementation need one new verification.

Stop reserves ten seconds for completion and persists the returned verdict before freshness checks. A failed check
preserves a deny as audit evidence without delivering an unverified correction. Signal-exit reasons remain valid journal
records. First-write crashes retain a complete checkpoint, and missing markers cannot refund a spent review. Follow-up
correction notices report unreviewed work; turns without a reservation report `dispatched: false`.

Known admission/readiness refusals also report `false`; an interrupted dispatch remains `null`. Human supervisor status
shows the distinction. The reset preview's apply command preserves the selected session.

| Regression owner                                                                                | Covered failure                                                                                                             |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| [Turn recovery](../../../../../tests/regression/test_bug_b4_turn_recovery.py)                   | Missing Stop, new thread, post-review changes, capped carry/reset, configuration changes, no-dispatch and cap/verdict races |
| [Evidence gaps](../../../../../tests/regression/test_bug_b4_evidence_false_gaps.py)             | Index stat refresh and denied requests                                                                                      |
| [Enrollment refresh](../../../../../tests/regression/test_bug_b4_enrollment_refresh.py)         | Failed/incomplete probes, failed replacement and irrelevant preferences                                                     |
| [Journal initialization](../../../../../tests/regression/test_bug_b4_journal_initialization.py) | First-write crash and missing marker without a refunded allowance                                                           |
| [Completion](../../../../../tests/regression/test_bug_b4_stop_completion.py)                    | Signal exit, completion reserve, saved deny after capture failure and correction follow-up notice                           |
| [Inactive dispatcher](../../../../../tests/regression/test_bug_b4_turn_hook_fastpath.py)        | Effective overrides, live enable, unmanaged sessions and enrollment exception                                               |

## Validation

| Check                                | Result                                                                                                                                             |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make test-unit`                     | 10,672 passed, 117 deselected                                                                                                                      |
| `make test-regression`               | 1,519 passed                                                                                                                                       |
| Targeted integration runner          | 30 passed, one slow real-inference control deselected                                                                                              |
| `make pre-commit`                    | Passed all hooks, including formatting, types, size limits, secrets and links                                                                      |
| `make build` and clean wheel install | Passed; all 380 product Python files and the packaged QA hook checklist matched the checkout                                                       |
| Wheel hook lifecycle                 | Enable, doctor, sync, status, recovery help and disable passed; all five hooks registered once with 60-second timeouts; unrelated config preserved |

The integration command was:

```bash
PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh \
  tests/integration/core/test_codex_stop_recovery.py \
  tests/integration/docker/test_installer.py::TestCodexHooksModule \
  tests/integration/docker/test_installer.py::TestCrossRuntimeSkillLifecycle \
  tests/integration/docker/test_installer.py::TestHookDispatcherRuntime \
  tests/integration/cli/test_stop_verification_integration.py \
  tests/integration/docker/test_supervisor_auth_isolation.py \
  tests/integration/docker/test_supervisor_e2e.py -m 'not slow'
```

The new integration owner exercises preview, reset and the next explicit turn through real CLI processes and durable
session state; its reviewer is a local stub. The remaining 29 controls use Docker. No real inference ran in this
follow-up. The closed 32-unit native round was not reused, and its native cancellation and quota-exhaustion limitations
remain. These results do not claim new native hook-delivery evidence for the follow-up source.

## Installed dispatcher cost

The three opt-in turn hooks read the current effective policy in the stdlib dispatcher. Unmanaged, disabled and ordinary
per-edit sessions avoid full CLI startup. Enrollment probes and uncertain manifests still dispatch normally, and
enabling Stop in an idle running session is observed without relaunching it.

The [measurement](followup-dispatcher-cost.json) contains 15 fresh-process samples per command from the clean wheel:

| Command                                   | Median elapsed time |
| ----------------------------------------- | ------------------- |
| `codex-turn-start`                        | 20.828 ms           |
| `codex-turn-tool`                         | 20.362 ms           |
| `codex-stop`                              | 20.058 ms           |
| Direct full-CLI `codex-turn-tool` control | 618.782 ms          |

These are local process timings under concurrent test load, not native Codex hook latency or universal performance
guarantees. The lightweight dispatcher still starts once per hook. Neither arm ran a model call or used a normal login.

[Wheel verification](followup-wheel.json) records the candidate hash, source inventory digest, exact commands and
preserved configuration assertions. The lifecycle used a version-reporting Codex stub for binary discovery only;
`FORGE_DEV` was absent. Both helpers removed their temporary homes. Their exact sources are
[hashed here](followup-helper-sources.json). Run them with the clean wheel's Python:

```bash
python scripts/experiments/codex-hooks/b4-dispatcher-cost.py --forge /path/to/wheel-env/bin/forge
python scripts/experiments/codex-hooks/b4-wheel-followup.py --checkout /path/to/multi-forge --wheel /path/to/candidate.whl
```
