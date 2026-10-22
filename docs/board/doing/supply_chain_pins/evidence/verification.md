# Hardening verification

Source base: `93b558d2`. Verification date: 2026-10-22. No model inference or native agent turns were run. The approved
Anthropic token count covered only `docs/design_installation.md`: 24,230 tokens after review edits, below its
25,000-token target.

## Completed checks

- `make build`: wheel and sdist built with hash-enforced build constraints.
- `./scripts/test-wheel-runtime.sh`: fresh Python 3.13 environment, hashed runtime install, dependency consistency,
  packaged LiteLLM start, local health check and stop passed.
- A synthetic build with a fresh uv cache and deliberately incorrect build hashes refused with `Hash mismatch` before
  executing a build dependency.
- Actual offline constrained `uv tool install` in disposable tool/bin/state directories: all 85 applicable runtime pins
  matched; version/help and read-only extension doctor passed. No user hooks were installed. See
  [global-tool.json](global-tool.json) for the exact input hashes.
- Actual `setup.sh --local` in a disposable container passed, followed by user hooks and project extension enable. All
  85 applicable runtime pins matched; doctor reported a current dispatcher and healthy project registry. This used an
  existing image with uv 0.13.4, not the new hardened image. See [setup-container.json](setup-container.json).
- The hardened image's installer and exact-wheel QA integration tests passed: 26 tests. Ran
  `./scripts/test-integration.sh` for `tests/integration/docker/test_installer.py` and
  `tests/integration/docker/test_qa_release_artifact.py`, with `PYTHON_DOTENV_DISABLED=1`, `CLAUDE_VERSION=2.1.245` and
  `CODEX_VERSION=0.149.1`. This includes the offline wheel build and both runtime extension lifecycles. The image
  prepares hash-verified build dependencies explicitly; a separate online/offline build probe also passed.
- Review verification added three Docker tests: an unrelated project resolves its own local backend despite a version
  conflict with Forge's pins; Forge still builds offline using hashed backend artifacts; and the documented global wheel
  recipe installs and registers a durable launcher. The recipe refuses wrong wheel/runtime hashes, an existing
  installation directory and an occupied launcher path without replacing the previous launcher. The initial combined run
  passed 28 tests and failed the recipe's incorrect offline-cache assumption; with that test-only restriction removed,
  the recipe passed on its targeted rerun. All 29 targeted Docker tests now pass.
- `./scripts/test-wheel-runtime.sh --unconstrained` passed in a disposable container with no host mounts or forwarded
  credentials. Fresh metadata resolution installed a compatible graph and passed packaged LiteLLM start, local health
  and stop. The separate daily/manual workflow uses this mode with no PR trigger, persisted checkout credentials or
  provider secrets; its hosted scheduled execution starts after merge.
- Real Git regressions prove a rejected source candidate preserves HEAD, source, the editable environment and launcher,
  including a changed `FETCH_HEAD` during validation. Additional regressions cover a system Python lacking `tomllib`,
  invalid runtime overrides during unit collection, and separation of locked versus unconstrained smoke installation.
- Focused dependency-pin, environment-vocabulary and Pyright checks: 19 passed. The two publisher configuration checks
  also passed. Installer refusal fixtures include real local Git tag/branch selection and preservation of dirty files.
- `make test-regression`: all 2,152 tests passed after review fixes.
- `make test-unit`: 11,151 passed, 117 deselected, no failures.
- `make pre-commit`: all hooks passed, including file-size verification, formatting, type checks, secret scanning,
  documentation links and dependency-export drift.
- The optional native Claude toolchain built successfully. A network-disabled container reported Claude `2.1.245` and uv
  `0.9.18`; the native binary matched the repository-held platform checksum.
- `pip-audit==2.10.1` checked all 138 third-party lock entries, including build/development groups: no known
  vulnerabilities. No existing package version changed; the lock gained 12 build/hook packages. See
  [audit-summary.json](audit-summary.json).

## Scope of evidence

The approved unused build-cache cleanup preserved all six tagged images; container and volume inventories remained
empty. It cleared the disk-space blocker before rebuilding and testing the pinned image.

The full commit pins and uv download checksum were resolved from upstream sources; see
[resolved-refs.json](resolved-refs.json) and [uv-download.json](uv-download.json). The publisher's
manifest/configuration digests and explicit input defaults were checked against official sources; see
[publisher-image.json](publisher-image.json). An actual OIDC exchange, attestation signing and upload still require an
authorized release run.

The guarantees differ by path: uv's locked environment, default wheel smoke and optional verified global wheel recipe
use artifact hashes; uv 0.9.18 tool constraints enforce versions, not artifact hashes. Its project sync uses
`tool.uv.build-constraint-dependencies`, because it does not apply `UV_BUILD_CONSTRAINT` to that path. The image does
not export this variable into unrelated workloads. Once a source candidate is admitted, a dependency-sync failure can
still require rerunning setup; candidate validation is not an atomic environment replacement. Ordinary PyPI installs,
host runtimes, npm transitives, updating Debian repositories and deliberately selected compatibility versions remain the
documented boundaries in [dependency security](../../../../developer/dependency_security.md).
