# Patch the late-October dependency advisories

**Status**: Doing, accepted on 2026-10-29. Branch `codex/dependabot-security-followup`, based on `addf8f7e`. The owner
requested the two open Dependabot fixes and approved including the additional runtime findings from the full lock audit.
[PR #288](https://github.com/hapa1i/multi-forge/pull/288) contains the fixes. See [checklist](checklist.md),
[alerts](alerts.json) and [audit findings](audit-findings.json).

## Scope

| Package    | Previous lock | Patched selection | Findings | Ownership               |
| ---------- | ------------- | ----------------- | -------- | ----------------------- |
| Black      | 26.5.1        | 26.10.1           | 1        | Development             |
| virtualenv | 21.14.12      | 21.14.13          | 1        | Development             |
| dnspython  | 2.8.0         | 2.9.0             | 1        | Runtime, packaged floor |
| filelock   | 3.32.5        | 4.2.1             | 12       | Runtime, packaged floor |
| LiteLLM    | 1.102.0       | 1.102.2           | 1        | Runtime, exact pin      |

Black's bundled GitHub Action is not used here. Its upstream advisory lists a narrower affected range than the
Dependabot database; upgrading the development floor and lock resolves the alert without dismissing it. Virtualenv's
Bash activator must keep prompt text inert after enabling expansion or inheriting an exported `PS1` in a child shell.

The runtime updates cover DNS name decompression, file-lock safety and LiteLLM authentication. Filelock's major upgrade
requires compatibility checks through Hugging Face and virtualenv; their declared ranges admit 4.2.1. LiteLLM remains on
the 1.102 release line. Preserve existing model routes, saved configurations, FastAPI/Starlette bounds and build pins.

The earlier [dependency card](../dependabot_october_2026/card.md) retains the evidence for
[PR #279](https://github.com/hapa1i/multi-forge/pull/279). This card covers the newly reported alerts and audit
findings. No model-provider inference is part of this maintenance task.

## Acceptance

- Resolve the five reviewed patched releases and ship runtime security floors in wheel metadata.
- Reproduce the Bash prompt and existing-file lock defects with harmless local fixtures before updating; verify the
  patched packages and runtime metadata afterwards.
- Review the lock and generated exports; keep development tools out of wheel runtime requirements.
- Pass the complete dependency audit, unit/regression suites, focused proxy/backend integrations, full pre-commit, build
  and clean-wheel runtime smoke without paid inference.
- Sync the current LiteLLM contract and explain that existing processes must restart after upgrading their installation.
- Open one PR with evidence. Dependabot closure requires the merged default-branch graph; do not dismiss the alerts.
