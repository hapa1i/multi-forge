# Hardening verification

Source base: `93b558d2`. Verification date: 2026-10-22. No model-provider calls or native agent turns were run.

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
- Focused dependency-pin, environment-vocabulary and Pyright checks: 19 passed. The two publisher configuration checks
  also passed. Installer refusal fixtures include real local Git tag/branch selection and preservation of dirty files.
- `make test-regression`: all 2,132 tests passed. All 29 focused installer tests also passed after the final help edits.
- `SKIP=file-size-limits make pre-commit`: all other hooks passed, including formatting, type checks, secret scanning,
  documentation links and dependency-export drift.
- The optional native Claude toolchain built successfully. A network-disabled container reported Claude `2.1.245` and uv
  `0.9.18`; the native binary matched the repository-held platform checksum.
- `pip-audit==2.10.1` checked all 138 third-party lock entries, including build/development groups: no known
  vulnerabilities. No existing package version changed; the lock gained 12 build/hook packages. See
  [audit-summary.json](audit-summary.json).

## Pending verification

The final `make test-unit` run reported 11,150 passed, 117 deselected and one failure:
`test_shipped_provider_cache_matches_exact_file_bytes`. It requires fresh provider-count evidence for the edited
`docs/design_installation.md`; that document-only transmission is awaiting approval. The earlier environment-vocabulary
and negative build-pin fixture failures were corrected and pass the full rerun.

File-size verification remains pending the document count; formatting changes from the hooks have been reviewed.

The targeted Docker installer/QA run reached image export but failed with `no space left on device` before tests began.
Even starting a container from the exported tag required layer extraction and failed for the same reason. This task's
disposable native probe image was removed, but enough cache remains referenced to block extraction. Broader unused
build-cache cleanup is awaiting approval. The separate installer smoke above passed in an already-unpacked image, but
does not replace verification of the new image.

## Scope of evidence

The full commit pins and uv download checksum were resolved from upstream sources; see
[resolved-refs.json](resolved-refs.json) and [uv-download.json](uv-download.json). The publisher's
manifest/configuration digests and explicit input defaults were checked against official sources; see
[publisher-image.json](publisher-image.json). An actual OIDC exchange, attestation signing and upload still require an
authorized release run.

The guarantees differ by path: uv's locked environment and the default wheel smoke use artifact hashes; uv 0.9.18 tool
constraints enforce versions, not artifact hashes. Its project sync uses `tool.uv.build-constraint-dependencies`,
because it does not apply `UV_BUILD_CONSTRAINT` to that path. Ordinary PyPI installs, host runtimes, npm transitives,
updating Debian repositories and deliberately selected compatibility versions remain the documented boundaries in
[dependency security](../../../../developer/dependency_security.md).
