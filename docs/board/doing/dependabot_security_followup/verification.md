# Dependency security verification

Verified on 2026-10-29 from base `addf8f7e`, on macOS with Python 3.13.16. The clean-wheel smoke used Python 3.13.11.
The [card](card.md) records all five version changes; [alerts](alerts.json) and [audit findings](audit-findings.json)
retain the 16 advisory identities. No package was added to or removed from the lock, and no other locked version
changed.

## Advisory review

- [Black's upstream advisory](https://github.com/psf/black/security/advisories/GHSA-cg8m-r9f2-5wm2) names 26.9.0 and
  26.10.0 and its bundled GitHub Action's `use_pyproject` path. Dependabot's broader `<26.10.1` range flags our 26.5.1
  CLI dependency. This repository does not use that Action; the patched floor resolves the alert without dismissing it.
- [Virtualenv's advisory](https://github.com/pypa/virtualenv/security/advisories/GHSA-cx6f-vjhg-g3cc) applies to the
  previous 21.14.12 lock. Its upstream severity is moderate; the captured GitHub database alert labels it high.
- [Dnspython's advisory](https://github.com/rthalley/dnspython/security/advisories/GHSA-45c3-73f7-pv4m) is fixed by
  2.9.0. This dependency enters the runtime through email-validator.
- [Filelock 4.2.1](https://github.com/tox-dev/filelock/releases/tag/4.2.1) covers the twelve audited advisories. Hugging
  Face, virtualenv and python-discovery admit this release in their dependency metadata.
- [LiteLLM's advisory](https://github.com/BerriAI/litellm/security/advisories/GHSA-7hp6-4w63-5g45) covers authentication
  privilege escalation in 1.102.0. Version 1.102.2 is the patched release on the existing release line.

## Behavioral and packaging evidence

The three Bash prompt-transition cases fail on virtualenv 21.14.12 by executing a harmless temporary marker command; all
pass on 21.14.13. The existing-file regression fails on filelock 3.32.5 and passes on 4.2.1. The added dnspython,
filelock and LiteLLM metadata assertions fail before the runtime updates and pass afterwards.

Hugging Face's `WeakFileLock` acquires a fresh lock, refuses a second owner until timeout, releases and reacquires it
with filelock 4.2.1. Virtualenv seeds an isolated environment with `--no-download --no-periodic-update`, and its
`pip check` passes. Inspecting the built wheel confirms the dnspython/filelock floors and exact LiteLLM pin; Black and
virtualenv remain absent from runtime requirements.

A fresh Linux Python 3.12.15 test container, run with `--network none`, also confirms all three patched runtime
versions, existing-file preservation and Hugging Face lock contention/release behavior.

| Check                                                                                                                                                                                                                                                  | Result                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| `uv run --locked pytest tests/src/scripts/test_dependency_pins.py tests/regression/test_bug_virtualenv_bash_prompt_expansion.py tests/regression/test_bug_filelock_existing_target.py tests/regression/test_bug_wheel_dependency_floor_metadata.py -q` | 20 passed                                                                                    |
| Complete lock audit with pip-audit 2.10.1                                                                                                                                                                                                              | 138 third-party registry packages, zero known vulnerabilities, zero skips                    |
| `make build`                                                                                                                                                                                                                                           | Dependency exports match; wheel and sdist built with hashed build constraints                |
| `./scripts/test-wheel-runtime.sh`                                                                                                                                                                                                                      | Fresh hash-checked runtime install, dependency compatibility and LiteLLM start/health passed |
| Focused integration runner, four proxy/backend files below                                                                                                                                                                                             | 19 passed                                                                                    |
| `make test-unit`                                                                                                                                                                                                                                       | 11234 passed, 120 deselected                                                                 |
| `make test-regression`                                                                                                                                                                                                                                 | 2218 passed                                                                                  |
| `make pre-commit`                                                                                                                                                                                                                                      | All hooks passed, including file-size limits; no skips                                       |

Integration files: `tests/integration/proxy/test_litellm_streaming_cost_e2e.py`,
`tests/integration/proxy/test_finish_reason_e2e.py`, `tests/integration/backend/test_backend_cli.py`, and
`tests/integration/backend/test_proxy_backend_integration.py`. They ran through `scripts/test-integration.sh` with
`PYTHON_DOTENV_DISABLED=1` and provider API variables removed. The streaming fixture exercises the installed LiteLLM
mock response with outbound connections blocked. No model-provider inference was dispatched.

The final audit queried every registry package/version in `uv.lock` using
`uvx pip-audit==2.10.1 --no-deps --disable-pip --progress-spinner off -r <inventory> --format json`. Its inventory
SHA-256 is `f2b8f07eb073764f5c00f4c3c416afa0b90547f1f2827632907e2fe9a077aafc`; the reviewed lock SHA-256 is
`d8079b101d5af67cd22015b97cc99718bde45c5c09a12b8c7b6ffa4b458029e6`. This is a known-advisory check, not a claim that
upstream code has no defects.

The refreshed Anthropic counts are 23,461 tokens for `docs/design_telemetry.md` and 22,629 for `docs/end-user/proxy.md`;
both cache entries match the final document bytes. `AGENTS.md` records the owner's standing authorization for routine
token-count API calls and cache refreshes.

## After merge

The two Dependabot alerts remain open until the fixes merge and GitHub refreshes the default-branch graph. Existing
installations need an upgrade and process restart; merging the lock does not update running deployments.
