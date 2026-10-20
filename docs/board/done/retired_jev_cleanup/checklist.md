# Retired Jev cleanup checklist

**Current focus**: Complete. [PR #277](https://github.com/hapa1i/multi-forge/pull/277) merged on 2026-10-20.

## Implementation

- [x] Create the cleanup branch from `39ba8cbb` and identify A1, experimental and mixed-code ownership.
- [x] Delete A2/A3 experiment scripts and private rule-pack modules with their dedicated tests.
- [x] Remove A2 consent integration from session inheritance, overrides and policy disable; preserve generic validation.
- [x] Update normative docs and instructions; retain immutable historical source references.
- [x] Verify historical JSON evidence is unchanged and no executable references remain.

## Verification

| Test                    | Fixture                                     | Assertion                                              | Evidence                                        |
| ----------------------- | ------------------------------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| Retained A1             | Judgment responses, probe manifests         | Types, transport, budgets and accounting still pass    | Focused tests                                   |
| Policy and sessions     | Ordinary overrides, inheritance and disable | No dangling imports; generic policy validation remains | Unit/regression and targeted Docker integration |
| Package contents        | Fresh wheel install                         | A1 imports; retired rule-pack modules are absent       | Clean install smoke                             |
| Historical preservation | Retired JSON evidence                       | Every tracked JSON has its original SHA-256            | Local hash comparison                           |

- [x] Run focused A1 checks, full unit/regression tests and applicable integration tests.
- [x] Build and verify the wheel in a clean environment.
- [x] Run Markdown links, file-size limits, full pre-commit and `git diff --check`.

## Closeout

- [x] Commit reviewable cleanup and open a PR with validation results.
- [x] After merge, update the change log and move this card to done.

## Merged closeout

PR #277 merged as `51c2d92c` on 2026-10-20. The merged tree is identical to reviewed head `e760648f`; all five GitHub
checks passed. The local verification below remains applicable to that shipped tree.

The cleanup card is done. A1 remains done, and the epic, A2 and A3 remain retired. Their historical JSON evidence is
unchanged, and the [source archive](../../retired/epic_jev_support/source-archive.md) retains the pre-removal revision.
The design map, architecture history, session ownership and end-user policy guidance were synchronized in the merged PR.

## Recorded verification

- Dependency audit found no remaining executable imports or references to removed modules/scripts. Both generic
  unknown-bundle and unknown-config-owner tests include `jev_rule_pack` and pass.
- All 45 historical A2/A3 JSON files are byte-identical to `39ba8cbb`; A1 implementation, probe, fixtures and card are
  unchanged. The Markdown audit passes for 734 tracked sources.
- Focused policy/session checks passed 346 tests; the preserved terminal-disable override test passed with its 12-test
  file.
- `make build` passed after fetching the missing `hatchling` build dependency; the initial offline-cache attempt could
  not resolve it. Wheel and sdist inspection excludes `policy/rule_pack` and retains all four A1 modules. A fresh wheel
  installation passed a synthetic ZDR judgment, CLI help, coding-standards file/diff checks and unsupported-bundle
  refusal, using a fixture transport and an isolated Forge home.
- Full pre-commit and diff checks pass. The owner-approved count for edited `docs/design.md` is 20,706 Anthropic tokens,
  within policy. The first unit run reached the cache assertion before that refresh completed: 10,961 passed and one
  stale-cache assertion failed. The refreshed rerun passed all 10,962 unit tests (117 integration tests deselected).
- `make test-regression` passed 1,891 tests. The first direct manager-integration attempt had Docker setup errors;
  integration verification uses the standard `make test` runner and its freshly rebuilt image.
- The first complete integration run passed 503 tests and failed 16 fast forced-tool rejection cases because their
  fixtures required live provider credentials. Those cases now use local fixture upstreams and assert zero forwarded
  requests. Production proxy behavior and the separately marked live-provider tests are unchanged.
- The corrected forced-tool matrix and existing offline health check passed through the standard integration runner: 17
  passed, 34 deselected, with provider credentials unset and retries disabled.
- Final `PYTHON_DOTENV_DISABLED=1 make test` passed: 10,962 unit tests (117 deselected) and 519 integration tests
  (13,009 deselected), with no failures or retries. The default integration selection excludes slow live-provider tests;
  no paid model captures or native trials were run.
