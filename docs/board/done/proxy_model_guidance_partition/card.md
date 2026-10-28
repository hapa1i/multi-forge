# Separate model refresh guidance from proxy operations

**Status**: Done on 2026-10-28. [PR #285](https://github.com/hapa1i/multi-forge/pull/285) merged as `fb803b92`, matching
reviewed head `c52faac9`. Follow-up from review of [PR #281](https://github.com/hapa1i/multi-forge/pull/281). See the
[merged closeout](checklist.md#merged-closeout) and [verification evidence](evidence.md).

## Problem

At PR revision `0ec43a15`, `docs/end-user/proxy.md` contains 28,313 Opus tokens, above the repository's 25,000-token
target and close to its 30,000-token hard limit. The October model refresh added about 700 tokens. Repeating that growth
will exhaust the remaining space after a few refreshes.

The current base has 28,304 Opus tokens with a matching cached hash; the partition retains the 23,000-token acceptance
limit for both guides.

## Scope

Move per-refresh model capabilities, alternatives, and upgrade notes into
[model_selection.md](../../../end-user/model_selection.md). Keep proxy setup, lifecycle commands, configuration
ownership, transport behavior, and ZDR policy authoritative in [proxy.md](../../../end-user/proxy.md). Link between the
two guides where a model-specific upgrade requires a proxy operation.

Preserve model identities, caveats, migration steps, and working command examples. Check inbound links before moving
sections; retain short forwarding sections when existing anchors are still used. Keep the explicit workflow-worker
inventory authoritative in [workflow.md](../../../end-user/workflow.md).

## Acceptance

- Each topic has one authoritative home, with links replacing duplicated explanations.
- Existing upgrade and model-selection links still lead to the applicable instructions.
- Both resulting guides fit within 23,000 Opus tokens, leaving room below the repository target for later refreshes.
- Refresh `.file-token-counts.json` after formatting and pass the Markdown, file-size, and link checks.
- Verify representative fresh-setup and saved-proxy upgrade examples against current CLI help and template output.

This follow-up changes documentation organization only; it does not change model defaults, routing, or proxy snapshots.
