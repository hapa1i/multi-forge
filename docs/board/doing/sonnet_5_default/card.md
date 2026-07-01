# Sonnet 5 support + default-tier flip

## Problem

Anthropic released **Claude Sonnet 5** (`claude-sonnet-5`) across all surfaces (first-party API and OpenRouter:
`https://openrouter.ai/anthropic/claude-sonnet-5`). Forge's model catalog and proxy templates do not know about it. The
maintainer also wants to run the newest models by default rather than opt-in.

## Scope (locked decisions)

1. **Sonnet 5 becomes the default `sonnet` tier** everywhere (catalog defaults, templates, Claude Code estimator pins).
   Sonnet 4.6 stays selectable via `--model`.
2. **Opus 4.8 becomes the default `opus` on both layers**: the proxy/session opus tier flips Fable 5 -> Opus 4.8 in all
   four anthropic-family templates, and the catalog default opus flips 4.6 -> 4.8 (this feeds the review quorum's
   `claude-opus` worker). Fable 5 and Opus 4.6 become opus `--model` alternatives.
3. **No Sonnet 5 review/quorum worker** in `review/models.py`.

## Design context

- Sonnet 5 shares the Opus 4.7/4.8 + Fable "new surface": adaptive-thinking-only, sampling overrides removed, native 1M
  context, denser tokenizer (`token_estimate_multiplier: 1.35`). It has a single canonical id (no `-1m` twin); the
  OpenRouter slug `anthropic/claude-sonnet-5` has no dot.
- Tier detection is prefix/substring based, so `claude-sonnet-5` auto-classifies as `sonnet` with no routing changes.
- The catalog `defaults:` block is the single pivot: `review/models.py`, template docs, and the catalog-load validator
  all derive from it via `get_default_model`, so the review quorum tracks the opus flip with no review-code changes.

## Intelligence-score rerank

Per the maintainer, Sonnet 5 sits between Opus 4.6 and Opus 4.8 and is a peer of Opus 4.7. Integer scores made strict
betweenness impossible at the old values (Opus 4.6 = 98, 4.8 = 99 were adjacent), so the opus ladder was re-ranked into
a clean monotonic progression:

- Opus 4.6: 98 -> 97, Opus 4.7: 99 -> 98 (previously 4.7/4.8 were tied at 99), Opus 4.8: 99 (unchanged), Fable 5: 100.
- Sonnet 5: 98 (between Opus 4.6 = 97 and Opus 4.8 = 99; peer of Opus 4.7). No review worker consumes the score.
- `default_timeout_seconds: 180` for Sonnet 5 (between Sonnet 4.6 = 120 and the heavy Opus siblings = 240).

## Risks

- **anthropic-passthrough `--model` regression**: the shared pin validator only accepts the tier default or a configured
  alternative. Passthrough has no `model_alternatives`, so flipping its tiers would reject `--model claude-fable-5` /
  `claude-opus-4-6` / `claude-sonnet-4-6` pre-launch — breaking the template's advertised "forward unchanged" behavior.
  Mitigation: a `wire_shape == "anthropic_passthrough"` exemption in `_proxy_supports_model_pin` (also fixes a latent
  inability to pin Opus 4.8/4.6 on passthrough today) + regression test.
- **Stale metadata/docs**: Opus 4.8's `opt-in` tag and several docs/comments assume 4.8/Fable are non-default. Must move
  with the flip.

Full execution plan: `checklist.md`. Approved plan snapshot: `~/.claude/plans/fancy-drifting-fountain.md`.
