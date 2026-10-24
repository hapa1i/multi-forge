# October models checklist

Current focus: final verification and PR review; all three models passed live tool round trips.

- [x] Verify the shortlist against current provider metadata and published model cards.
- [x] Create the execution branch from refreshed `origin/main`.
- [x] Add catalog identities, routes, template alternatives, and workflow workers.
- [x] Verify reasoning controls, sampling, streaming tools, usage, and cache accounting.
- [x] Verify fresh realization and preservation of pre-existing snapshots.
- [x] Update model selection and runtime documentation.
- [ ] Run applicable unit, regression, integration, pre-commit, and clean-wheel checks.
- [x] Review the complete diff and prepare the single PR.
- [ ] After merge, record closeout and move the card to done.

| Fixture / path                         | Acceptance                                             |
| -------------------------------------- | ------------------------------------------------------ |
| Exact catalog IDs and aliases          | Distinct snapshot identities; canonical route coverage |
| Family templates and workflow registry | Selectable alternatives; unchanged defaults            |
| OpenRouter SDK request capture         | Correct effort and sampling controls                   |
| Translated tool round trip             | Streaming tool call and valid continuation             |
| Existing proxy snapshot                | Byte-preserved configuration after reload              |
| Clean wheel resources                  | Same catalog and routes outside the checkout           |
