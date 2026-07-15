# Consolidate memory-passport CLI target preflight

**Status**: Proposed on 2026-07-15 from the `okf_compatible_memory_passports` post-closeout review.

## Goal

Extract the repeated Forge-root, path-safety, compatibility, resolution, and existence plumbing used by
`forge memory track` and `forge memory passport show|upgrade|remove` without changing any command's read/mutation or
stdout/stderr contract.

## Why this is separate

The blocks look similar but are not interchangeable:

- `show` is read-only and must not acquire the mutating commands' project-compatibility refusal;
- track/remove use established `ClickException` output;
- upgrade deliberately uses `forge.cli.output` recovery messages on stderr;
- existing commands use different missing-file wording that may already be consumed by tests or users.

Folding those differences into the correctness remediation would increase blast radius without fixing a current
behavioral defect.

## Acceptance shape

- Characterize rootless, unsafe, missing, incompatible, and successful paths for every affected leaf, including output
  stream placement.
- Extract a narrowly parameterized resolver that makes read-versus-mutation compatibility enforcement explicit.
- Preserve upgrade's actionable `Error`/`Tip` output and the existing `--json` stdout guarantees for read leaves.
- Keep reserved OKF official/shadow validation in the domain layer rather than hiding it in generic path containment.
- Run focused command-tree/output tests and the memory CLI suite; update CLI design guidance only if observable output
  intentionally changes.

## Non-goals

- Changing passport or envelope semantics.
- Standardizing all Forge CLI error text in one pass.
- Moving project-compatibility enforcement onto read-only commands.

## References

- `src/forge/cli/memory.py`
- `docs/developer/cli_style_guidelines.md`
- `docs/board/done/okf_compatible_memory_passports/checklist.md#reopened-remediation-2026-07-15` (deferred disposition)
