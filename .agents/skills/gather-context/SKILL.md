---
name: gather-context
description: Core Forge context load for blueprint, companion docs, and board files.
---

# gather-context

Use this skill when the user asks to run the `gather-context`, or asks for a core Forge context load.

## Command Template

Core context load for Forge.

**Read the design map and domain contracts**:

1. **Design Overview**: @docs/design.md
2. **Session Design**: @docs/design_sessions.md
3. **Runtime Design**: @docs/design_runtime.md
4. **Telemetry Design**: @docs/design_telemetry.md
5. **Installation Design**: @docs/design_installation.md
6. **Workflow Design**: @docs/design_workflows.md
7. **Memory Design**: @docs/design_memory.md
8. **CLI Reference**: @docs/cli_reference.md
9. **Context-size Policy**: @.file-size-limits.json and @docs/developer/documentation_guidelines.md

**Read board and gap tracking**:

1. **Change Log**: @docs/board/change_log.md
2. **Implementation Notes Index**: @docs/board/impl_notes.md
3. **Core and Installation Notes**: @docs/board/impl_notes/core_installation.md
4. **Session Notes**: @docs/board/impl_notes/sessions.md
5. **Runtime and Telemetry Notes**: @docs/board/impl_notes/runtime_telemetry.md
6. **Active Cards**: inspect `docs/board/doing/`; if it is empty, inspect the `docs/board/todo/<slug>/` card named by
   the user.

---

After reading, summarize:

- Current status of the project
- Key architectural concepts and how they relate
- Blockers or design decisions needed
