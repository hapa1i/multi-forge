# Implementation notes: T4 `forge_hook_dispatcher`

Proposed durable lessons for human review before promotion:

- Keep benchmark gates ahead of production code when a card names performance as a shape decision. The
  populated-registry fixture mattered here because an empty fixture would not exercise JSON parse plus path matching.
- Treat standalone hook shims as a separate runtime artifact, not an extension manifest file. They need their own
  version/source stamp, sync re-render, and doctor drift surface.
- Do not couple runtime launcher metadata to `installed.json`. Extension ownership and hook-runtime resolution age on
  different timelines.
- Preserve scope boundaries in code and docs: T4 provides the dispatcher mechanism; T5 owns registration byte changes
  and presence-detection updates.
