# Remove individually verified internal zero-callers

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092).

**Lane**: `todo/` -- accepted Wave 7 cleanup work.

## Admitted Scope

- Deprecate then remove the deliberately re-exported `parse_supervisor_verdict` wrapper.
- Remove `LLMClientFactory.get_cache_status`/`clear_cache`, `ProjectRootNotFoundError`, the unused
  `collect_shadow_entries.session_filter` behavior, `_print_session_tip`, and unused `render_categories` parameters.
- Remove `_generate_relaunch_name.parent_name` while preserving project-scoped collision behavior.
- Retain and wire the explicit `count-tokens.py --local` selector by making both mode flags write one destination.

`_extract_command_paths` is owned by the settings-helper card. Status-line cache candidates, defensive cap parsing,
converter residue, and unnamed O5 claims remain excluded pending individual verification.

## Acceptance Criteria

- Re-run caller, export, resource, extension, and documentation searches for every admitted symbol immediately before
  removal.
- Move behavior tests to reachable paths or delete only tests belonging exclusively to removed functionality.
- Split this card by domain before execution if the changes cannot remain one reviewable commit.
