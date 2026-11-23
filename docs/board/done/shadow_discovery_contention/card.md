# Keep shadow proposals visible across projects

Shipped on `main` in [PR #307](https://github.com/hapa1i/multi-forge/pull/307) on 2026-11-23.

In `3e88e270`, session listing began serving a partial snapshot while the index was busy. A legacy session with an
unstamped index row can disappear from that snapshot. If it is the only session in a sibling project, shadow discovery
skips that project's passports and can report a successful empty list.

Workspace and global shadow discovery now refuse a partial root list before scanning passports or dispatching curation.
Project discovery already knows which root to scan. See the [execution checklist](checklist.md) and
[memory design](../../../design_memory.md#57-cli-verbs).
