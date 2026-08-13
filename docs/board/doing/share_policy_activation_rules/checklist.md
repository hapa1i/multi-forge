# Share policy activation rules checklist

Current focus: implementation and required verification are complete on the execution branch; keep O044 in `doing/`
through review and merge, then perform the board-only closeout before activating order 3.

## Phase 1 -- Characterize and activate

- [x] Close O043 on `main` at `2a08f009`, branch from that exact commit, and activate only O044.
- [x] Recheck both writers: terminal `enable|disable` mutates `intent.policy`; `%policy enable|disable` mutates
  `overrides.policy`.
- [x] Run the unchanged core-op, terminal, direct-command, and ownership-regression slice: 108 passed.
- [x] Keep O044 bounded to activation vocabulary, input validation, and values; exclude session resolution, mutation,
  rendering, effective-intent precedence, and D056/O097 stream work.

## Behavior matrix

| Case                                  | Terminal `forge policy`        | Direct `%policy`                              | Invariant                                     |
| ------------------------------------- | ------------------------------ | --------------------------------------------- | --------------------------------------------- |
| enable `tdd`, default mode            | writes intent; success text    | writes overrides; JSON block                  | enabled=true, bundles=`tdd`, fail mode=`open` |
| enable multiple, closed, permissive   | writes intent; success details | writes overrides; JSON block                  | order retained; TDD config is `strict=false`  |
| permissive without `tdd`              | writes no bundle config        | writes no bundle-config override              | permissive affects only TDD                   |
| bare enable                           | stderr error + tip, exit 1     | usage JSON block, exit 0                      | no mutation                                   |
| invalid bundle                        | Click choice error, exit 2     | unknown token ignored; usage if none valid    | surface parser/error shape retained           |
| invalid fail mode with a valid bundle | Click choice error, exit 2     | invalid value ignored; default remains `open` | surface parser/error shape retained           |
| disable                               | sets intent enabled=false      | sets override enabled=false                   | unrelated owner fields preserved              |
| direct command with no session        | not applicable                 | silent exit 0                                 | D034 no-session contract retained             |

## Phase 2 -- Shared rules

- [x] Add typed, UI-free activation values and input errors to `forge.core.ops.policy`, derived from the deterministic
  bundle registry and the `FailMode` vocabulary.
- [x] Make both surfaces call the shared activation/deactivation builder after retaining their existing syntax parsing.
- [x] Keep terminal mutation limited to the four bundle-owned intent fields and direct mutation limited to override
  fields; do not introduce one shared state writer.
- [x] Add exact core-op and surface regressions for the matrix, including permissive configuration and invalid-input
  behavior.
- [x] Derive the terminal recovery tip and direct-command usage string from the shared bundle vocabulary.
- [x] Document that each activation result owns a freshly allocated mutable bundle-config dict which its one surface
  writer receives by reference.
- [x] Update `docs/design.md` command-core ownership; verify end-user policy documentation needs no change because the
  commands, state ownership, output, and errors remain stable.

## Phase 3 -- Verify and close

- [x] Run focused core-op, terminal policy, direct-command, and ownership-regression tests: 125 passed.
- [x] Run `./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py`: 22 passed.
- [x] Run `make test-unit` (9,022 passed, one skipped, 122 deselected), `make test-regression` (898 passed), and
  `make pre-commit` (clean after Markdown normalization).
- [x] Resolve board links/fragments and run `git diff --check`: all 853 local links across 329 board Markdown files and
  all three fragments from the seven changed board documents resolve. The 34-member Wave 7 graph is exactly one `done/`,
  one `doing/`, and 32 `todo/` members with valid epic backlinks.
- [ ] After review and merge, record the shipped outcome, move this member to `done/`, and leave order 3 parked until
  the closeout lands.
