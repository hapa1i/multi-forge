# Graduate WorkflowPolicy to a real CLI preset surface

**Status**: Proposed (parked). Split off from `accidental_complexity_cleanup` (Phase C), which **demoted** the
`workflow` bundle to explicitly experimental / manifest-only rather than graduating or deleting it.

**Origin**: During the accidental-complexity audit, the `workflow` policy bundle was found to be a fully built pipeline
with **no product surface** — a classic "half-shipped abstraction" that reads as accidental complexity. The cleanup card
deliberately did **not** delete it (the pipeline is sound and intended) and did **not** graduate it (out of a cleanup
card's scope). It demoted it and filed this card for the real graduation work.

## Problem

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

## What exists today (shipped, keep)

- `forge.policy.workflow` pipeline: tagger → filter → checker → reviewer stages.
- `build_divergence_config(**overrides)` (`policy/workflow/divergence.py`) — builds a `WorkflowConfig` but is **not**
  wired to any CLI.
- `get_bundle_policies("workflow", config=...)` registry path (dynamic `workflow.<name>` policy IDs).
- Manifest activation via `policy.bundles` + `policy.bundle_config.workflow`.

## What graduation needs

- A real `--workflow <preset>` (or similar) CLI UX on `forge policy enable`, with named presets that map to
  `build_divergence_config(...)` overrides.
- Discovery: surface `workflow` (and its presets) in `forge policy list` once it has a real surface.
- Wire `build_divergence_config` from the CLI path (today it is only reachable by constructing config dicts).
- Docs: promote the `docs/end-user/policy.md` `workflow` section from "experimental, manifest-only" to a documented
  command surface.
- Tests: CLI enable/list coverage + a preset → `WorkflowConfig` mapping test.

## Risks / open questions

- **Preset vocabulary**: what are the shipping presets (e.g. `divergence`), and are they user-extensible or a closed
  set? This decides whether `--workflow` takes a preset name, a config path, or both.
- **Cost surface**: the reviewer stage calls an expensive model. A discoverable CLI toggle needs guardrails/opt-in so a
  user does not enable per-change LLM review unaware of cost.
- **Overlap with the review engine** (`forge.review`): confirm the workflow bundle is the right home for this UX rather
  than folding it into the existing multi-model review surface.

## References

- Demote decision + rationale: `accidental_complexity_cleanup` (Phase C checklist, "WorkflowPolicy: DEMOTE").
- Config schema: `design.md` §4.1.2.
