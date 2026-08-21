# Decide compatibility requirements for cleanup deletions

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md) (DG4).

**Lane**: `done/` -- approved on 2026-08-04; the post-Wave 6 screen split admitted work under the parked
[`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

## Problem

The review identifies deletion-class candidates in O047–O052, O092–O093, and O096: modules with no production importers,
unraised exception paths, inert configuration, legacy public methods, dead retry branches, test-only callers, and
unreachable branches.

Zero production callers do not establish that deletion is compatible. Tests may pin a supported import, serialized
config may be user-authored, extension consumers may live outside this repository, and several claims are partial or
explicitly unverified. A bulk sweep would mix safe local cleanup with public-surface and migration decisions.

## Decision Required

Define the compatibility evidence required before deleting:

- a module or public symbol;
- an exception type and its handling path;
- a serialized config field;
- a public store/registry method;
- a legacy environment shim; or
- a test-only helper or unreachable branch.

For every candidate, record `keep`, `deprecate`, `delete`, `replace`, or `verify further`, with external-consumer risk,
test disposition, documentation impact, and migration requirements. O092 must be split into individually verified
symbols; O093's no-op claim and every explicitly unverified candidate remain ineligible until confirmed.

## Evidence

- Review: [`review_combined.md` DG4](../../review_combined.md#decision-gates).
- Candidate rows: O047–O052, O092–O093, and O096 in the review's code and maintenance table.
- Board rule: independently shippable changes remain member cards; deletion is not one mechanical operation merely
  because the findings share a type label.

## Decision

**Status:** approved on 2026-08-04.

Forge does not promise a general Python library API for every importable object under `src/forge`. A symbol becomes a
compatibility surface through evidence: end-user or developer documentation, a stable CLI/JSON contract, user-authored
configuration, durable serialized state, a declared plugin/entry point, a packaged extension/resource contract, or an
intentional re-export from a supported package surface. A test import alone proves coverage, not support.

### Deletion rubric

Before deletion, an implementation card must record:

1. repository-wide static callers, dynamic imports, entry points, package resources, templates, docs, and bundled
   extension consumers;
2. whether the surface is private implementation, deliberately re-exported API, user-authored config, durable state, or
   an external wire/CLI contract;
3. the behavior the existing tests characterize and whether those tests should move to a reachable replacement or be
   removed with the dead feature;
4. the compatibility action: immediate internal deletion, staged deprecation, explicit migration, replacement, or
   retained compatibility shim; and
5. focused verification plus the relevant unit, regression, integration, wheel/resource, or clean-install tier.

Private implementation may be removed in one release after caller and behavior characterization. Documented/re-exported
interfaces require either a retained shim or a deprecation window. Inert user-owned config is accepted with an
actionable relocation/removal warning in the first release containing the migration and becomes an error no earlier than
the following release. Durable manifests/indexes require an explicit schema migration or tolerant reader; deleting a
dataclass field while old strict documents exist is prohibited. Wire-shape and provider-conversion branches require
protocol fixtures, not only `rg` evidence.

“Unreachable” must be demonstrated from the branch preconditions and tests. “Zero caller” is not enough when the symbol
encodes an intended optimization or safety invariant; wiring it may be the right disposition.

## Finding-Level Disposition

### Verified primary rows

| Finding / surface                                                 | Disposition                   | Compatibility and test requirement                                                                                                                                                                                                                                      |
| ----------------------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| O047 `forge.proxy.model_spec`                                     | Delete                        | No production, docs, resource, or extension importer was found; remove its self-only tests and confirm live model detection covers the intended cases.                                                                                                                  |
| O048 `AbstractLLMClient`                                          | Delete                        | No implementation inherits from it; update stale type comments and test the actual adapter protocol.                                                                                                                                                                    |
| O048 `ToolCallError` and two handlers                             | Delete after characterization | No production path raises it, but a metrics test synthesizes it. Move failure-metric coverage to a reachable exception before removing the exception and handlers.                                                                                                      |
| O049 `ProviderConfig.enable_preamble`                             | Deprecate, then delete        | It is accepted user-owned provider config. Stop generating it, accept-and-warn for one compatibility window, then reject it.                                                                                                                                            |
| O049 `ProviderConfig.openai_api_mode`                             | Deprecate, then delete        | It is copied through templates and instance config but has no consumer. Remove template emission and use the same accept/warn window before schema rejection.                                                                                                           |
| O049 `SessionConfig.manifest_filename`                            | Deprecate, then delete        | `MANIFEST_FILENAME` is authoritative. Preserve config-file readability during the warning window; never imply the path is configurable.                                                                                                                                 |
| O049 `MemoryIntent.generated_file`                                | Migrate, then delete          | It is persisted in strict session manifests. Add a schema migration/tolerant decode that removes the inert key before deleting the field.                                                                                                                               |
| O050 `IndexStore.add_session`, `add_from_state`, `remove_session` | Replace                       | They are extensively used as unsafe test-fixture shortcuts and can bypass row/manifest transactions. Production and regression fixtures must use transaction-safe builders; retain only private lock-local helpers needed by `create_session_txn`/`delete_session_txn`. |
| O051 `_get_tier_for_model` environment shim                       | Replace                       | Remove nonexistent legacy env lookup and false “auto-detected” logging. Callers must pass an explicit resolved tier or use one named default at the routing boundary. Characterize cache keys and auth-retry coupling.                                                  |
| O052 corruption-classification retry                              | Delete                        | The second identical index lookup cannot discover the commented manifest condition. Preserve corruption propagation with direct tests, then remove the retry.                                                                                                           |
| O093 `map_model_name`                                             | Keep; verified 2026-08-13     | The deletion claim is contradicted by live behavior: explicit backend requests consume its result, fresh-config mapping and OpenRouter pass-through/alias tests pass, and the completed investigation found no deletion or simplification to admit.                     |
| O096 `restore_settings_backup`                                    | Delete                        | Only its direct tests call it; no CLI recovery path or supported export was found. Remove the tests with the unused feature.                                                                                                                                            |
| O096 `check_scalar_conflict`                                      | Delete                        | Same test-only/internal disposition as `restore_settings_backup`; retain merge-conflict coverage on the live merge path.                                                                                                                                                |
| O096 `session_fork` `elif proxy_name` branch                      | Delete                        | `proxy_name` always initializes `_preflight_routing` before this branch, making it unreachable. Preserve routing-summary tests for proxy, inherited, and direct modes.                                                                                                  |

### O092 split

| O092 candidate                                       | Disposition            | Reason / admission condition                                                                                                                                                                                                                                              |
| ---------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `parse_supervisor_verdict`                           | Deprecate, then delete | Production uses `_with_status`, but the wrapper is deliberately re-exported. Warn or retain a one-release shim before removing its export/tests.                                                                                                                          |
| `TierClientFactory.get_cache_status` / `clear_cache` | Delete                 | No production callers or documented operator surface; move any useful cache behavior assertions to live factory paths.                                                                                                                                                    |
| `ProjectRootNotFoundError`                           | Delete                 | Definition-only and not a documented/re-exported error contract.                                                                                                                                                                                                          |
| `collect_shadow_entries(..., session_filter=...)`    | Delete parameter       | Every production caller passes `None`; remove the non-production filtered behavior and its direct-only tests unless a CLI consumer is first admitted.                                                                                                                     |
| `_print_session_tip`                                 | Delete                 | Explicit private no-op stub.                                                                                                                                                                                                                                              |
| `_extract_command_paths`                             | Delete                 | Private zero-caller helper; retain tests on the live settings-merge path rather than the helper.                                                                                                                                                                          |
| `IndexState.needs_reindex`                           | Keep and wire          | It was unused at decision time but expresses the intended `mtime`/size guard. Use it to stop re-extracting metadata-unchanged transcript snapshots; do not delete the optimization or describe it as content identity.                                                    |
| status-line in-process cache candidates              | Verify further         | The compound row does not name exact symbols or prove one-render call counts. Split and measure before admission.                                                                                                                                                         |
| `render_categories` always-empty parameters          | Replace signature      | Remove individually proven unused parameters while preserving wrapping/hardening output fixtures.                                                                                                                                                                         |
| `caps.py` non-dict branch                            | Verify further         | Establish the durable schema/tolerant-reader contract before deleting defensive input handling.                                                                                                                                                                           |
| converter `system_prompt` key and Gemini residue     | Verify further         | These touch provider wire shapes; require request fixtures for every supported backend before deletion.                                                                                                                                                                   |
| `_generate_relaunch_name` `parent_name` parameter    | Delete parameter       | The function uses only `forge_root`; keep project-scoped collision behavior and remove the unused argument.                                                                                                                                                               |
| `count-tokens.py --local`                            | Keep and wire          | It is exposed in script help and already selects local behavior by leaving the mutually exclusive `provider_api` mode false. Make both mode flags write one destination so the redundant unread `args.local` field disappears without removing the explicit CLI selector. |
| O5's remaining approximately 20 unnamed symbols      | Verify further         | They remain ineligible until individually named, searched, classified, and tested.                                                                                                                                                                                        |

This matrix intentionally rejects two deletion recommendations as written: O093 has verified production behavior, and
`IndexState.needs_reindex` should be wired to remove redundant work. It also retains `--local`: the flag is not named in
the repository documentation, but it is exposed by the script's help and its behavior is unambiguous. Local counting is
the default, `--provider-api` is the sole opt-in remote path, and argparse prevents selecting both. Wiring both flags to
one mode destination removes the dead parsed value without deleting the explicit selector.

## Implementation Members

The initial accepted cleanup was deliberately parked in broad placeholders pending a current-source screen. That screen
completed on 2026-08-13 and the executable sequence now lives under
[`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md). In particular:

- O049 is split into user-config deprecation and durable-manifest migration;
- O050 is split into safe fixture migration and only-then public mutator deletion;
- O092 is split by subsystem and compatibility class; and
- O096's fork branch is folded into the fork-execution extraction where its reachability proof belongs.

The former O092 umbrella is a retired
[`remove_verified_internal_zero_callers`](../../retired/remove_verified_internal_zero_callers/card.md) reference, and
the fork-only placeholder is a retired
[`remove_unreachable_fork_routing_branch`](../../retired/remove_unreachable_fork_routing_branch/card.md) reference. The
O093 investigation completed during admission and is retired as
[`characterize_explicit_backend_mapping`](../../retired/characterize_explicit_backend_mapping/card.md): current tests
prove the mapping behavior is live, so no replacement deletion member exists.

The accepted rubric should be added to `docs/developer/coding_standards.md` when the decision is approved. No production
symbol or serialized field is removed by this decision card.

## Acceptance Criteria

- A compatibility rubric covers imports, durable config, public APIs, tests, extensions, and migration.
- Every listed row has an evidence-backed disposition; compound rows are split by symbol or behavior.
- Unverified candidates are explicitly excluded or promoted only after confirmation.
- Accepted removals become narrowly scoped implementation cards with characterization and regression expectations.
- No production deletion is bundled into this decision card.

## Closeout

The compatibility rubric is now normative in `docs/developer/coding_standards.md`; every admitted row has a parked
member and explicitly unverified candidates remain excluded. No production symbol was deleted in this decision phase.
Verification: `make pre-commit-md` and `git diff --check`.
