# Complete proxy instance config wiring

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `doing/` -- implemented and verified on `agent/complete-proxy-instance-config-wiring` from merged `main` at
`7c76a099`; awaiting an independent draft PR.

**Findings**: D029 and O025.

## Goal

Preserve template-declared tool-ignore and prompt-cache settings through the template-to-instance-to-runtime pipeline.

## Evidence and Authority

Rechecked on merged `main` at `7c76a099`: `tool_prefixes_to_ignore` exists only on `ProxyConfig`, while
`create_proxy_file()` omits it and also lets `prompt_caching`/`auto_cache_min_tokens` fall back to instance defaults.
[`docs/design_appendix.md` §A.1](../../../design_appendix.md#a1-proxy-overlay-schema-364--user-edit-surface) assigns
proxy overlay ownership and precedence.

## Acceptance Criteria

- All three fields survive template load, instance serialization/reload, and runtime config projection.
- Existing instance files without the fields retain current defaults.
- Extend the structural wiring guard so future shared-field additions cannot silently skip a hop.
- Retain regression/config round-trip tests and run proxy creation integration coverage.

## Implementation Outcome

`ProxyInstanceConfig` now owns `tool_prefixes_to_ignore`. Declared direct-field sets carry unchanged top-level proxy
fields and selected-provider fields through template creation, instance reload, and runtime projection. Prompt-cache
policy and threshold therefore come from the selected template provider instead of instance defaults.

The structural guard closes both dataclass intersections: every shared proxy/instance and provider/instance field must
be a declared direct copy, registered block, or explicit transform. Tier construction and CLI override merging remain
explicit transforms. Missing keys still use the existing instance defaults.

## Verification

The retained five-case regression failed in the three expected wiring cases on unchanged production code from merged
`main` at `7c76a099`, while legacy-default and unrelated-block controls passed (`3 failed, 2 passed`). All five now
pass. The full config/proxy unit slice plus the prior shared-block regression passes (`1,015 passed`).

Full unit tests pass (`8,986 passed`, one existing platform skip, 122 deselected), as do all 758 marked regressions. Six
Docker-backed `forge proxy create --no-start` integration cases pass, including custom-template creation and runtime
reload of all three fields. Design and end-user proxy contracts now describe snapshot ownership and absent-key defaults.

`make pre-commit` passes. Its first run exposed invalid package-level imports in the already-merged O014/O026
regression; an import-only correction passes standalone mypy and all six prior regressions without changing product
behavior. The final board audit covers 288 files and 713 local links with zero missing targets; the Wave 6 lane graph is
4 done, 1 doing, and 7 todo. Diff, Markdown, and document-size checks pass.

## Compatibility and Exclusions

No migration rewrite is required for absent optional fields. Existing proxy files retain `[]`, `passthrough`, and `1024`
defaults. Model mapping, tier/CLI override transforms, provider credentials, and unrelated proxy block ownership are
unchanged.
