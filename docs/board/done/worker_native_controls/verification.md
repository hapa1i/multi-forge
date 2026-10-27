# Worker native-control verification -- 2026-10-26

The review fixes were verified with clean `multi_forge-1.1.3-py3-none-any.whl` installations under `/opt/forge-qa`.
[Machine-readable evidence](evidence/native-worker-controls-20261026.json) records the wheel SHA-256, fixture hashes,
exact arguments, native tool outcomes and source-transcript hashes. The release-QA image installs hash-checked locked
dependencies; probes use fresh homes, synthetic credentials, a deterministic localhost upstream and `--network none`.

The pinned track uses Claude **2.1.245** and Codex **0.149.1**. Its guarded helper-backed reviewer uses Claude
**2.1.248**, the minimum admitted reviewer version. The compatibility track uses Claude **2.1.304** and Codex
**0.164.0**, including the guarded helper path. Both tracks use the same wheel bytes.

## Native evidence

| Probe                                                 | Observed result on both tracks                                                                                                                                                  |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Claude proposal controls, fork-context Skill          | Skill admitted and a native child transcript created; denying Agent alone does not close this path.                                                                             |
| Claude review and consumer workers                    | Injected Agent, Workflow, SendMessage or Skill unavailable; no native child transcript. Hostile inherited settings cannot restore the auto-memory prompt.                       |
| Guarded Claude reviewer with inherited `apiKeyHelper` | Actual guarded dispatch succeeds with one settings payload, one slash-command disable, the helper indirection and fixed worker settings; Skill remains unavailable.             |
| Claude API-key bare worker                            | Compatible launch and rejected Skill. Bare mode already excludes Skill without the profile, so this case does not establish causal isolation.                                   |
| Two parallel Claude reviews of one source             | Distinct worker session IDs; the original transcript's before/after SHA-256 values match.                                                                                       |
| Codex ordinary root                                   | Native spawn succeeds. Version 0.149.1 discovers the namespace through tool search; 0.164.0 advertises it directly.                                                             |
| Codex fresh and resumed workers                       | Neither discovery nor direct advertisement exposes native spawn; an injected namespaced call is rejected. Both memory controls and the multi-agent feature disable are emitted. |

The unit/regression checks also snapshot subscription authentication and dispatch independently: environment, working
directory and control arguments match. They verify that helper projection preserves non-environment profile settings,
that retries retain the composed controls, and that managed root launches retain their normal configuration. Shared test
builders and wheel/image helpers replace the cross-test imports and repeated packaging setup.

Claude memory evidence covers the auto-memory prompt under hostile settings. Codex memory evidence covers emitted
configuration; it does not establish historical non-use. Existing conversation text is retained. Native controls do not
govern external programs invoked through Bash or MCP, and this card does not add a managed-root delegation policy.
Native Codex fork reviewers retain their hook/plugin/app and authentication restrictions.

## Validation

- Focused worker, auth, invoker and managed-session tests: **197 passed**. Strengthened regressions first reproduced
  five failures before the fixes.
- `make test-unit`: **11,173 passed, 120 deselected**.
- `make test-regression`: **2,168 passed**. The first aggregate run found two test callers missing the newly required
  worker argument; those callers were updated, their focused rerun passed, and the full rerun is clean.
- `make build`: **passed** for wheel and sdist. The built wheel SHA-256 matches both native evidence tracks.
- Targeted Docker native, auth-isolation, native-fork and release-artifact tests: **16 passed**. The final wheel's
  pinned native probes and current-version compatibility probes then passed **2 tests each**, retaining 22 native
  admission cases and two parallel-resume checks in the evidence.
- Additional live Docker reviewer-auth, old-runtime refusal and headless cost checks: **4 passed** on Claude 2.1.304.
- `make pre-commit`: **passed**, including type checks, secret scanning, Markdown links and file-size limits. Initial
  type-inference and import-format failures were corrected before the passing run. The approved workflow document count
  is **27,346 tokens**, above the 25,000 target and below the 30,000 hard limit.
- `forge workflow list-models --available --json`, `forge runtime preflight codex --json` and blind Codex/mixed panels:
  **passed**. Codex preflight and the Codex-only panel ran with `PYTHON_DOTENV_DISABLED=1`; the mixed panel used the
  existing configured credentials. Every worker returned `WORKER_OK`. Earlier no-dotenv Claude verification refused
  missing credentials with an actionable diagnostic; no authentication configuration was changed.

The targeted Docker command was:

```bash
CLAUDE_VERSION=2.1.245 CODEX_VERSION=0.149.1 PYTHON_DOTENV_DISABLED=1 env -u GEMINI_API_KEY \
  ./scripts/test-integration.sh \
  tests/integration/docker/test_worker_native_controls.py \
  tests/integration/docker/test_supervisor_auth_isolation.py \
  tests/integration/core/test_codex_fork_supervisor.py \
  tests/integration/docker/test_qa_release_artifact.py \
  tests/integration/docker/test_walkthrough_release_artifact.py -q -s
```

The additional live tests selected `tests/integration/docker/test_reviewer_compatibility.py` and
`tests/integration/docker/test_real_claude_headless_cost.py` with the existing Anthropic credential,
`CLAUDE_VERSION=2.1.304 CODEX_VERSION=0.164.0 PYTHON_DOTENV_DISABLED=1`, and Gemini unset.

The final native reruns selected only `tests/integration/docker/test_worker_native_controls.py`. The compatibility run
set `CLAUDE_VERSION=2.1.304 CODEX_VERSION=0.164.0 FORGE_AUTH_TEST_CLAUDE_VERSION=2.1.304` with the same no-dotenv
isolation. Docker setup downloads the pinned packages; the actual native probes run offline without provider inference.

[Initial implementation evidence](evidence/native-worker-controls-20261025.json) remains available as a historical
snapshot; the 2026-10-26 evidence above supersedes its launch arguments and coverage.

## CI portability follow-up (2026-10-27)

[CI run 40374223892](https://github.com/hapa1i/multi-forge/actions/runs/40374223892) failed one unit test on Ubuntu
26.04: the detached-process cleanup probe rejected the runner's uutils `timeout` before launching its fixture. GNU
timeout is available there as `gnutimeout`. Both probe entry points now check `timeout`, `gtimeout` and `gnutimeout` for
a successful GNU version response, preserving the refusal when no GNU implementation is available.

- Eight new regression cases cover all three names and refusal with only non-GNU implementations. Five failed before the
  fix; all eight now pass.
- Script unit tests plus the timeout, login-admission and operator-environment regressions: **201 passed**.
- The six existing probe unit tests and eight new regressions: **14 passed** in a clean Ubuntu 26.04 container with
  Python 3.11.14 and locked project dependencies. The image exposes uutils 0.10.0 as `timeout` and GNU coreutils 9.7 as
  `gnutimeout`; tests ran with networking disabled and a read-only checkout. Temporary fixture executables require an
  executable `/tmp` mount.

The local script checks used:

```bash
PYTHON_DOTENV_DISABLED=1 .venv/bin/pytest tests/src/scripts \
  tests/regression/test_bug_b2_probe_login_admission.py \
  tests/regression/test_bug_b2_probe_operator_environment.py \
  tests/regression/test_bug_probe_gnu_timeout_selection.py -q
```
