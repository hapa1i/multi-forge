# Smoke Test

Read-only health check for Forge installation. Runs a fixed set of probes (CLI availability, file existence, version
checks) and prints a pass/fail table. No intentional writes; sensitive paths are snapshotted before and after to assert
no side effects.

## Execution

Greet the user: "Running a read-only Forge smoke test -- no files will be written, no system changes."

Execute the bundled smoke-test invocation and show its output. The compiled invocation identifies the selected runtime
for the script:

{{forge:packaged_script:scripts/smoke-test.sh}}

Check the exit code: 0 = all pass, 1 = failed checks, 2 = unsupported runtime selection. Report accordingly.

For a more thorough runtime-specific verification, follow the Forge manual-testing guidance for the selected runtime.
