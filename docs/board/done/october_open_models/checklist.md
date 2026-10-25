# October models checklist

Current focus: completed; [PR #281](https://github.com/hapa1i/multi-forge/pull/281) merged on 2026-10-25.

- [x] Verify the shortlist against current provider metadata and published model cards.
- [x] Create the execution branch from refreshed `origin/main`.
- [x] Add catalog identities, routes, template alternatives, and workflow workers.
- [x] Verify reasoning controls, sampling, streaming tools, usage, and cache accounting.
- [x] Verify fresh realization and preservation of pre-existing snapshots.
- [x] Update model selection and runtime documentation.
- [x] Run applicable unit, regression, integration, pre-commit, and clean-wheel checks.
- [x] Review the complete diff and open the single PR.
- [x] Address review feedback on worker docs, release QA, capability coverage, and fixture ownership; rerun affected
  checks.
- [x] Verify reported workflow/auth integration failures, helper transport regressions, and final package/check gates.
- [x] After merge, record closeout and move the card to done.

Guide-size cleanup is tracked separately in the
[proxy model guidance partition proposal](../../proposed/proxy_model_guidance_partition/card.md).

| Fixture / path                         | Acceptance                                             |
| -------------------------------------- | ------------------------------------------------------ |
| Exact catalog IDs and aliases          | Distinct snapshot identities; canonical route coverage |
| Family templates and workflow registry | Selectable alternatives; unchanged defaults            |
| OpenRouter SDK request capture         | Correct effort and sampling controls                   |
| Translated tool round trip             | Streaming tool call and valid continuation             |
| Existing proxy snapshot                | Byte-preserved configuration after reload              |
| Clean wheel resources                  | Same catalog and routes outside the checkout           |

## Merged closeout

- PR #281 merged as `30ad379b` on 2026-10-25. Its tree is identical to reviewed head `d1edbed9`.
- [Pre-commit Checks](https://github.com/hapa1i/multi-forge/actions/runs/40213959002) and
  [Tests](https://github.com/hapa1i/multi-forge/actions/runs/40213959153) both passed on that head.
- [Evidence](evidence.md) records model metadata, six live tool round trips, fresh/saved snapshot checks, 2,158
  regressions, the 16-case workflow/auth selection, clean-wheel checks, and the corrected local unit-inventory failure.
- Runtime, subprocess, installation, proxy, workflow, policy, and QA documentation reflect the shipped behavior.
  Guide-size cleanup remains in the separate proposal linked above.
