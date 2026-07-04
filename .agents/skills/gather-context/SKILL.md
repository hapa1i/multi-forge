---
name: gather-context
description: Core Forge context load for blueprint, companion docs, and board files.
---

# gather-context

Use this skill when the user asks to run the `gather-context`, or asks for a core Forge context load.

## Command Template

Core context load for Forge.

**Read design blueprint and appendix**:

1. **Design Overview**: @docs/design.md
2. **Design Appendix**: @docs/design_appendix.md
3. **Workflow Design**: @docs/design_workflows.md
4. **CLI Reference**: @docs/cli_reference.md

**Read board and gap tracking**:

1. **Change Log**: @docs/board/change_log.md
2. **Implementation Notes**: @docs/board/impl_notes.md
3. **Active Cards**: inspect `docs/board/doing/`; if it is empty, inspect the `docs/board/todo/<slug>/` card named by
   the user.

---

After reading, summarize:

- Current status of the project
- Key architectural concepts and how they relate
- Blockers or design decisions needed
