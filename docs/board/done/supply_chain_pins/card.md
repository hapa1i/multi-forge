# Pin build and installation inputs

**Status**: Done. [PR #280](https://github.com/hapa1i/multi-forge/pull/280) merged on 2026-10-22 as `50472bee`. See the
[merged closeout](checklist.md#merged-closeout). Execution branch: `codex/harden-supply-chain`, based on `93b558d2`.

## Problem

The October 21 LiteLLM compromise did not match Forge's pinned 1.102.0 dependency, but the same protection does not
cover the whole build and installation path. CI bootstraps mutable tools and Actions, isolated builds resolve their own
dependencies, global installs ignore the project lock, and Docker defaults can fetch current runtime clients.

## Contract

- Keep the current LiteLLM pin and security floors. Derive runtime and build constraints from the reviewed project lock.
- Reject stale locks in standard CI/build/install paths. Verify dependency export drift before publishing.
- Pin CI Actions to full commits and bootstrap artifacts to explicit versions and hashes. Run Python pre-commit tools
  from the project lock instead of independent resolver environments.
- Constrain the source installer's global tool environment. Refuse an unavailable requested source revision without
  falling back to the default branch; preserve existing local work on update refusal.
- Pin Docker base/tool inputs and default Claude/Codex versions. Keep an explicit latest compatibility track.
- Document the remaining trust boundaries: ordinary unconstrained PyPI installs, host-owned runtimes, signed OS package
  repositories, and deliberately selected latest/custom toolchains.

Pins require reviewed updates; this change does not certify upstream code or retrospectively clear other environments.
No native model calls are needed for verification.

## Acceptance

The PR must include fixture-backed refusal and drift tests, clean wheel and constrained global-tool checks, targeted
Docker installer coverage, full unit/regression and pre-commit checks, and concise installation/update guidance.
