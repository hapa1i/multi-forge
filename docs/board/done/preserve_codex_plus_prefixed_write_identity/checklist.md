# Preserve Codex plus-prefixed Write identity checklist

Current focus: implementation and verification are complete; parent-epic review and merge gate Wave 2.

- [x] Create the corrective branch from merged `main` and activate this member in `doing/`.
- [x] Reproduce plus-prefixed Add identity loss through the parser, adapter, supervisor, and plan checker.
- [x] Replace unified-diff extraction at the Codex parsing boundary.
- [x] Add parser and adapter unit coverage for plus-prefixed Add and Update content.
- [x] Add a marked D005 regression proving distinct fingerprints and cache misses in both semantic layers.
- [x] Run focused tests, the full regression and unit suites, and targeted policy-hook integration.
- [x] Run `make pre-commit` and board/link consistency checks.
- [x] Record the corrective outcome and move this member to `done/`.
