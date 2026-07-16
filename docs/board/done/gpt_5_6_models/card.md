# GPT-5.6 model family and Sol defaults

Completed: 2026-07-16

## Goal

Add GPT-5.6 Sol, Terra, and Luna to Forge's model catalog and promote Sol wherever bundled OpenAI proxy defaults
currently select GPT-5.5.

## Accepted behavior

- Keep GPT-5.5 available for compatibility.
- Keep the OpenAI haiku default on GPT-5.4 Mini.
- Set OpenAI sonnet and opus defaults to GPT-5.6 Sol.
- Update every shipped OpenAI template whose tier mapping currently selects GPT-5.5.
- Promote the default OpenAI workflow worker to Sol without leaving its provider reference on GPT-5.5.
- Treat Sol's 100 and Terra's 98 intelligence scores as intentional coarse peer buckets, not benchmark equivalence.
- Preserve user-owned proxy and backend configuration; document explicit upgrade steps instead of rebasing it.

## Deferred

- GPT-5.6 `max` reasoning effort and `reasoning.mode: pro` need a separate effort-contract change.
- Automatic migration or rebase of materialized proxy/backend configuration.
