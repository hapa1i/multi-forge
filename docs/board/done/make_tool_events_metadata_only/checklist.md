# Make tool-event diagnostics metadata-only checklist

Current focus: complete -- D035 shipped in PR #158 (`ce7eb1ec`) before D036 activation.

## Activation and reproduction

- [x] Start `fix/make-tool-events-metadata-only` from merged PR #157 at `a2fb0638`.
- [x] Close O037/O038/O042, move D035 from `todo/` to `doing/`, and advance the child-epic cursor without activating
  D036.
- [x] Add a marked D035 regression covering tool-result/schema plaintext, the ordinary client-failure warning, field
  bounds, and directory modes.
- [x] Confirm the retained regression fails on `a2fb0638` for the reproduced D035 behavior while its `0600` control
  passes.

## Metadata-only event contract

- [x] Replace free-form event `details` with one structurally allowlisted metadata shape and update every caller.
- [x] Retain stage/status plus bounded request, tool, parameter-name, count, flag, and enum metadata only.
- [x] Make the ordinary client-tool-failure WARNING metadata-only without changing failure detection.
- [x] Harden Forge log and `tool_events` directories to `0700` while retaining `0600` shards.
- [x] Preserve the explicit bounded `tool_failures` plaintext plane and existing global cleanup/retention ownership.

## Acceptance tests

| Test                        | Fixture                                                  | Assertion                                                                  |
| --------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------- |
| Tool-result confidentiality | failed Write/Read result with content and input canaries | JSONL and ordinary logs contain metadata but no canary                     |
| Schema confidentiality      | tool schema description/property canaries                | event records contain counts and bounded names only                        |
| Bounded schema              | oversized IDs, names, and parameter-name collections     | every retained string/collection is capped deterministically               |
| Filesystem hardening        | pre-existing permissive log directories and shard        | directories become `0700`; shard remains `0600`                            |
| Opt-in failure control      | `log_tool_failures=true` with a large Write payload      | existing bounded plaintext failure record still writes                     |
| Global cleanup control      | old tool-event shard and configured `log_retention_days` | existing cleanup discovers/removes it; no second retention policy is added |

## Verification and closeout

- [x] Run the marked D035 regression and focused proxy logging/converter/server tests.
- [x] Run CLI log-clean controls and a targeted translated-proxy Docker integration.
- [x] Run the full unit and marked regression suites.
- [x] Review normative/operator docs; the clean-break debug record is internal, so no operator/design schema changes are
  required.
- [x] Synchronize branch evidence without recording D035 as shipped or advancing the cursor to D036.
- [x] Run board link/size checks, diff checks, and `make pre-commit`.
- [x] Receive independent review and merge before activating D036 (PR #158, `ce7eb1ec`).
