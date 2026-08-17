# Remove individually verified internal zero-callers (retired umbrella)

> **RETIRED -- REFERENCE ONLY. DO NOT IMPLEMENT.**

**Outcome**: `superseded`

**Retired**: 2026-08-13

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O092).

**Lane**: `retired/`. This compound card was split during Wave 7 admission; it did not ship independently and is not an
executable deletion list.

## Replacement Members

The admitted subsets now live with their actual compatibility and subsystem owners:

- factory cache methods: [`remove_obsolete_proxy_abstractions`](../../done/remove_obsolete_proxy_abstractions/card.md);
- dead git-root exception: [`unify_git_root_discovery`](../../done/unify_git_root_discovery/card.md);
- session helpers: [`remove_dead_session_helpers`](../../done/remove_dead_session_helpers/card.md);
- verdict wrapper: [`deprecate_supervisor_verdict_wrapper`](../../todo/deprecate_supervisor_verdict_wrapper/card.md);
- transcript guard: [`wire_transcript_reindex_guard`](../../todo/wire_transcript_reindex_guard/card.md);
- status-line candidates: [`extract_statusline_rendering`](../../todo/extract_statusline_rendering/card.md); and
- mode selector: [`simplify_count_tokens_mode_selector`](../../todo/simplify_count_tokens_mode_selector/card.md).

The cap-state branch, converter candidates, and unnamed O5 tail remain excluded rather than inherited by a replacement.

## Historical Admitted Scope

- Deprecate then remove the deliberately re-exported `parse_supervisor_verdict` wrapper.
- Remove `TierClientFactory.get_cache_status`/`clear_cache`, `ProjectRootNotFoundError`, the unused
  `collect_shadow_entries.session_filter` behavior, `_print_session_tip`, and unused `render_categories` parameters.
- Remove `_generate_relaunch_name.parent_name` while preserving project-scoped collision behavior.
- Retain and wire the explicit `count-tokens.py --local` selector by making both mode flags write one destination.

`_extract_command_paths` is owned by the settings-helper card. Status-line cache candidates, defensive cap parsing,
converter residue, and unnamed O5 claims remain excluded pending individual verification.

## Historical Acceptance Criteria

- Re-run caller, export, resource, extension, and documentation searches for every admitted symbol immediately before
  removal.
- Move behavior tests to reachable paths or delete only tests belonging exclusively to removed functionality.
- Split this card by domain before execution if the changes cannot remain one reviewable commit. This split is now the
  terminal outcome above.
