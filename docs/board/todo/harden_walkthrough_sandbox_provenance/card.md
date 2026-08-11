# Harden walkthrough sandbox provenance

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending a fail-first regression.

**Finding**: O036.

## Goal

Resolve the walkthrough target canonically and prove its marker before sourcing target-controlled shell code.

## Evidence and Authority

On `246aaff1`, `run-in-repo.sh` uses `abspath` for its denylist and sources `.forge/walkthrough/env.sh` before checking
the provenance marker. The bundled walkthrough skill declares the wrapper as the mandatory safety boundary.

## Acceptance Criteria

- Canonical real paths (including symlinks) are checked against the denylist.
- The marker and required structure are validated before `env.sh` can execute.
- A valid generated walkthrough repo still exports its isolated homes and runs commands unchanged.
- Retain shell-level malicious-env and symlink regressions; verify the built wheel contains the corrected script.

## Compatibility and Exclusions

Do not change the default test-repo location, the six post-provenance isolation checks, or setup/reset behavior.
