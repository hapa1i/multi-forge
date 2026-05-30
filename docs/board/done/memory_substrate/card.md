# Memory Substrate

## Thesis

Forge memory is captured context plus curated propagation. "Handoff" is a transfer operation over memory, not a separate
subsystem.

## Problem

The current codebase uses "handoff" to mean two unrelated things: the memory writer (stop-time agent that updates docs)
and the resume context file (parent transcript passed to child sessions). These share no code, no data structures, and
no lifecycle. The naming conflation makes the architecture harder to teach and extend.

Memory-related concepts are scattered across modules (`handoff_agent.py`, `handoff.py`, `session/handoff.py`,
`prev_sessions/`, `artifacts/`) without a unifying taxonomy. Search indexes transcripts, the resume system assembles
context, and the memory writer updates docs -- all operating on the same underlying captured data but through separate
abstractions.

## Target

Define a memory taxonomy that unifies these concepts:

| Layer               | What it holds                                        | Current location          |
| ------------------- | ---------------------------------------------------- | ------------------------- |
| **Raw memory**      | Transcripts, plans, artifacts, reports, usage events | `.forge/artifacts/`       |
| **Project memory**  | Passported docs (changelog, impl notes, patterns)    | `docs/`, `.forge/memory/` |
| **Transfer memory** | Curated context for fork/resume/runtime transfer     | `.forge/prev_sessions/`   |

Memory operations:

- **Capture**: hooks record transcripts, plans, artifacts (existing)
- **Index**: search indexes raw memory for retrieval (existing)
- **Curate**: memory writer selects and updates project docs at Stop (existing)
- **Update**: direct writes to project docs per passport strategy (existing)
- **Transfer**: assemble curated context for child sessions or cross-runtime handoff (existing for Claude, new for other
  runtimes)

## Naming Cleanup

| Current term      | Proposed term               | Rationale                                    |
| ----------------- | --------------------------- | -------------------------------------------- |
| handoff agent     | memory writer / curator     | It writes memory; "handoff" implies transfer |
| handoff file      | transfer context            | It is context assembled for transfer         |
| handoff report    | memory report               | Report of what the memory writer did         |
| `process_handoff` | `assemble_transfer_context` | Describes what it does                       |
| `prev_sessions/`  | (keep for now)              | Rename when transfer abstraction ships       |

## Relationship to Other Cards

**Runtime abstraction** (`todo/runtime_abstraction/`) should depend on this card for cross-runtime context transfer. The
runtime card owns the runtime registry, headless invokers, and capability matrix. This card owns the memory taxonomy and
transfer-context format.

Transfer flow: raw memory -> memory curator -> transfer context -> target runtime input.

## Open Questions

- Should transfer context be a formal schema (versioned, structured) or stay as generated markdown?
- Should the memory writer naming change be a single rename pass or gradual?
- How does search relate to the transfer context (can search results feed into transfer assembly)?
