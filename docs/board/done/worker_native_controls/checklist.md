# Worker native controls checklist

**Current focus:** Completed. [PR #282](https://github.com/hapa1i/multi-forge/pull/282) merged on 2026-10-27 as
`ef6a41e1`; its tree matches the verified head `81586905`. See [verification](verification.md).

M0 shipped independently. Managed-root delegation and memory policy, child capture and other epic members remain outside
scope.

## Contract and implementation

- [x] Inspect the proposal, epic boundaries, shared launchers and current worker call sites.
- [x] Verify the pinned Claude/Codex admission controls, including fork-context skills, using isolated fixtures. The
  proposal cites Claude 2.1.258/Codex 0.153.4; blocking QA pins are 2.1.245/0.149.1. Native Codex fork reviewers already
  disable agents and executable customizations; preserve those stronger restrictions.
- [x] Add regressions for inherited delegation/memory settings and late environment removal. The initial review-worker
  regression run failed all three cases before implementation. Seven Claude cases also failed before adding the
  `--settings` override that prevents inherited settings from re-enabling native memory.
- [x] Apply the explicit profile to review workers, semantic/team supervisors, memory writer and shadow curation.
- [x] Preserve restrictions across JSON-format retries, resume/fork requests, all auth paths and Codex consumer lanes.
- [x] Keep managed root exec/resume and interactive launches outside the worker profile.
- [x] Record emitted controls, runtime/wheel identities and verified behavior without claiming historical non-use. See
  [verification](verification.md) and [native evidence](evidence/native-worker-controls-20261026.json).

## Acceptance

| Test              | Fixture                                                      | Assertion                                                              | Test home                                            |
| ----------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------- | ---------------------------------------------------- |
| Worker selection  | Review and all supported consumer lanes                      | Every worker opts in; managed roots retain their configuration         | Review, consumer and Codex session tests             |
| Claude ordering   | Hostile inherited settings, caller overrides and late unsets | Tool and environment restrictions reach the child                      | Reactive env/session runner and Claude invoker tests |
| Retry/resume      | JSON rejection and existing worker conversation              | The durable base request retains the profile                           | Claude invoker/session runner tests                  |
| Codex controls    | Fresh, resumed and native-fork workers                       | Delegation and both memory controls remain disabled                    | Codex invoker and native supervisor tests            |
| Native admission  | Real pinned binaries and isolated local upstream             | Delegation tools and fork-context skills cannot create native children | Targeted Docker/workflow integration tests           |
| Installed package | Clean wheel and both runtime paths                           | Packaged code emits the same controls; evidence names exact versions   | Workflow integration and clean-wheel checks          |

## Review fixes

- [x] Fork resumed panel workers and prove parallel workers preserve the original transcript.
- [x] Compose worker and auth-helper settings once; verify subscription auth against the final dispatch configuration.
- [x] Require explicit Claude worker selection, remove duplicate flags and add the Codex feature disable.
- [x] Add admitted read-only/helper runtime coverage, label bare-mode compatibility evidence accurately and support both
  directly advertised and discovered Codex tools.
- [x] Extract shared test builders/assertions and wheel/image helpers; correct the acceptance-table test locations.
- [x] Run focused and relevant Docker tests, aggregate checks, build and live panel checks for the revised head. Unit:
  11,173 passed. Regression: 2,168 passed. Targeted Docker: 16 synthetic/packaging and 4 live tests passed; final
  pinned/current native probes passed 2 tests each. Full pre-commit, build and live panels passed.
- [x] Repair GNU timeout discovery after the Ubuntu 26.04 CI runner update. Script/probe checks: 201 passed locally;
  focused cleanup and timeout regressions: 14 passed in a clean Ubuntu 26.04 container.

## Initial validation (2026-10-25)

- [x] Run focused unit/regression tests and applicable Docker integration tests: final pinned probes and native fork
  composition, 11 passed; final live mixed panel, both workers succeeded.
- [x] Update workflow/memory design and end-user guides; update subprocess contracts if ownership changes.
- [x] Run aggregate regression (2,167 passed), build, clean-wheel and board/link checks.
- [x] Finish aggregate unit and full pre-commit gates. Unit run: 11,172 passed, one stale-cache failure. After explicit
  user approval, refresh `docs/design_workflows.md` with Anthropic (27,121 tokens, below the 30,000 hard limit); its
  cache-consistency rerun passed. Full `make pre-commit` passed, including file-size limits.
- [x] Record limitations and review the final diff. The pre-existing `AGENTS.md` edit is unchanged and unstaged.
- [x] Prepare the reviewed implementation and verification for the standalone PR.

## Closeout

- [x] After merge, verify the merged tree and CI, record closeout and move the card to done.

## Merged closeout

- PR #282 merged as `ef6a41e1` on 2026-10-27. Its tree is identical to reviewed head `81586905`.
- All five GitHub checks passed on that head. [Tests](https://github.com/hapa1i/multi-forge/actions/runs/40425656855)
  passed 11,173 unit tests (120 deselected), 2,176 regressions, dependency pins and clean-wheel LiteLLM runtime checks.
  [Pre-commit](https://github.com/hapa1i/multi-forge/actions/runs/40425656883) and
  [CodeQL](https://github.com/hapa1i/multi-forge/actions/runs/40425652702) passed too.
- [Verification](verification.md) retains the pinned/current native-runtime evidence, guarded authentication and
  parallel-resume checks, live panels, and the Ubuntu timeout repair.
- Workflow, memory, subprocess and end-user documentation reflect the shipped worker boundary. The broader epic and its
  remaining members stay proposed; M0 is removed from the optional future batch.
