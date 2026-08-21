# Graduate WorkflowPolicy to a real CLI preset surface (retired)

> **RETIRED -- REFERENCE ONLY. DO NOT IMPLEMENT.**

**Outcome**: `invalidated`

**Retired**: 2026-08-21

**Replacement**: [`remove_experimental_workflow_policy`](../../done/remove_experimental_workflow_policy/card.md).

**Lane**: `retired/`. The graduation premise was invalidated after the supervisor cascade and explicit
`forge workflow ... --check` gate became the supported semantic-review paths. Reinspection also found that the concrete
divergence preset could deny from unverified model-generated citations without receiving any repository or normative
project context. The replacement removes the experimental manifest surface and makes stale configuration fail actionably
instead of silently becoming a no-op.

## Historical proposal

This proposal split from `accidental_complexity_cleanup` Phase C, which demoted the `workflow` bundle to experimental,
manifest-only status rather than graduating or deleting it. The material below preserves the July 2026 proposal; it is
not normative architecture or an implementation plan.

## Historical problem

The `workflow` bundle can only be activated by hand-editing the session manifest:

```yaml
policy:
  bundles: ["workflow"]
  bundle_config:
    workflow:
      workflows: [...]
```

There is no `forge policy enable --workflow <preset>`, it is absent from `forge policy list`, and `get_all_bundles()`
(the only place it was advertised) was test-only and has been removed. So the capability exists but is undiscoverable
and unusable without reading the source.

## Historical implementation snapshot

- `forge.policy.workflow` pipeline: tagger → filter → checker → reviewer stages.
- `build_divergence_config(**overrides)` (`policy/workflow/divergence.py`) — builds a `WorkflowConfig` but is **not**
  wired to any CLI.
- `get_bundle_policies("workflow", config=...)` registry path (dynamic `workflow.<name>` policy IDs).
- Manifest activation via `policy.bundles` + `policy.bundle_config.workflow`.

## Historical graduation scope

- A real `--workflow <preset>` (or similar) CLI UX on `forge policy enable`, with named presets that map to
  `build_divergence_config(...)` overrides.
- Discovery: surface `workflow` (and its presets) in `forge policy list` once it has a real surface.
- Wire `build_divergence_config` from the CLI path (today it is only reachable by constructing config dicts).
- Docs: promote the `docs/end-user/policy.md` `workflow` section from "experimental, manifest-only" to a documented
  command surface.
- Tests: CLI enable/list coverage + a preset → `WorkflowConfig` mapping test.

## Historical risks / open questions

- **Preset vocabulary**: what are the shipping presets (e.g. `divergence`), and are they user-extensible or a closed
  set? This decides whether `--workflow` takes a preset name, a config path, or both.
- **Cost surface**: the reviewer stage calls an expensive model. A discoverable CLI toggle needs guardrails/opt-in so a
  user does not enable per-change LLM review unaware of cost.
- **Overlap with the review engine** (`forge.review`): confirm the workflow bundle is the right home for this UX rather
  than folding it into the existing multi-model review surface.

## Historical references

- Demote decision + rationale: [`accidental_complexity_cleanup`](../../done/accidental_complexity_cleanup/checklist.md)
  (Phase C, "WorkflowPolicy: DEMOTE").
- The original `design.md` §4.1.2 schema reference was already stale when this card retired.
