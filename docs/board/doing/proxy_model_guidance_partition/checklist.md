# Proxy/model guidance partition checklist

**Current focus:** Separate model release guidance from proxy operations without changing runtime behavior. Base:
`6c8d0999`. Branch: `codex/proxy-model-guidance-partition`. See [verification evidence](evidence.md).

## Ownership and preservation

- [x] Read the proposal, documentation policy and existing proxy/model-selection ownership.
- [x] Verify the current proxy count: 28,304 Opus tokens; the cached hash matches.
- [x] Inventory moved sections, model identities, provider caveats, command examples and inbound anchors.
- [x] Move API capability comparisons and model refresh notes into `model_selection.md`.
- [x] Keep proxy setup, lifecycle, snapshot ownership, transport and ZDR policy in `proxy.md`; consolidate the shared
  saved-proxy/backend upgrade procedure there.
- [x] Keep workflow worker inventory authoritative in `workflow.md`; replace duplicate inventories with links.
- [x] Preserve old upgrade anchors with forwarding sections and update living inbound links.
- [x] Verify the template-reset migration wording against its CLI implementation and correct it if needed.

## Acceptance evidence

| Concern              | Fixture                                            | Assertion                                                                                  |
| -------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| Model details        | Original guide sections on `6c8d0999`              | Model IDs, effort/sampling limits, provider caveats and upgrade requirements retained      |
| Link continuity      | Existing upgrade anchors and tracked inbound links | Old anchors forward; living links target the authoritative guide                           |
| Fresh setup          | Current CLI help and raw bundled templates         | Example commands are admitted and model mappings match                                     |
| Saved configuration  | Isolated saved proxy and custom template           | Reset affects template defaults only; saved config persists until explicit edit/recreation |
| Token headroom       | Formatted final guide bytes                        | Both guides below 23,000 Opus tokens; provider cache matches content                       |
| Documentation checks | Final staged documentation                         | Markdown, file-size, links and diff checks pass                                            |

## Verification and delivery

- [x] Verify representative commands and template/model mappings without inference or live proxy mutation.
- [x] Review the final partition for lost caveats, duplicate ownership and broken anchors.
- [x] Refresh authoritative counts for both final guides and update `.file-token-counts.json`: proxy 22,232; model
  selection 13,893.
- [x] Run `make pre-commit-md`, cache JSON hooks and staged diff checks.
- [x] Prepare the card's PR diff with verification evidence and final token counts.
- [ ] After merge, record closeout, repoint links and move the card to done.
