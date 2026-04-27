---
name: forge:smoke-test
description: Read-only Forge installation health check. No writes, no test repo needed.
disable-model-invocation: true
allowed-tools: Bash
---

# Smoke Test

Read-only health check for Forge installation. Runs a fixed set of probes (CLI availability, file existence, version
checks) and prints a pass/fail table. No intentional writes; sensitive paths are snapshotted before and after to assert
no side effects.

## Execution

Greet the user: "Running a read-only Forge smoke test -- no files will be written, no system changes."

**Run the smoke test script and show the output:**

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/smoke-test.sh"
```

Check the exit code: 0 = all pass, 1 = failures. Report accordingly.

Tip: "For a more thorough test, use `/forge:walkthrough` (interactive install/uninstall verification) or `/forge:qa`
(Docker QA — requires `forge extension enable --profile full`)."
