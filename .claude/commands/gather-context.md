---
description: Routed context load for the active Forge task and its owning domains.
disable-model-invocation: true
allowed-tools: Read
---

Load Forge context in two passes so domain partitioning reduces aggregate context as well as individual file size.

**Always read the routing set first**:

1. **Design Overview**: @docs/design.md
2. **Change Log**: @docs/board/change_log.md
3. **Implementation Notes Index**: @docs/board/impl_notes.md
4. **Active Cards**: inspect `docs/board/doing/`; if it is empty, inspect the `docs/board/todo/<slug>/` card named by
   the user.

**Then load only the domains implicated by the user request and active card**:

- **Sessions**: @docs/design_sessions.md and @docs/board/impl_notes/sessions.md
- **Runtime or telemetry**: @docs/design_runtime.md and/or @docs/design_telemetry.md, plus
  @docs/board/impl_notes/runtime_telemetry.md
- **Installation or core ownership**: @docs/design_installation.md and/or the relevant core sections in @docs/design.md,
  plus @docs/board/impl_notes/core_installation.md
- **Workflows or memory**: @docs/design_workflows.md and/or @docs/design_memory.md; add the implementation-note ledger
  named by @docs/board/impl_notes.md only when it contains relevant precedent
- **CLI surfaces**: @docs/cli_reference.md
- **Documentation or context-limit work**: @.file-size-limits.json and @docs/developer/documentation_guidelines.md

Follow explicit links from the selected card when they identify another required contract. Do not load every domain by
default. If the user explicitly asks for a full repository context load, read all domain design documents, all three
implementation-note ledgers, the CLI reference, and the context-size policy.

---

After reading, summarize:

- Current status of the project
- Key architectural concepts and how they relate
- Blockers or design decisions needed
