# Preserve the documented LiteLLM backup

**Status:** Done. Shipped on 2026-10-29 in [PR #287](https://github.com/hapa1i/multi-forge/pull/287), merged as
`addf8f7e`; board closeout recorded on 2026-10-30. See [checklist](checklist.md).

The [backend upgrade procedure](../../../end-user/proxy.md#updating-saved-proxy-and-backend-configurations) saves
`config.yaml.bak` inside the adapter directory that `forge model backend delete litellm` removes. Following the
procedure therefore loses both the custom config and its backup. The snippet originated in `8a2eea11` and was retained
when `fb803b92` consolidated the upgrade instructions.

Save the backup at `~/.forge/backends/litellm-config.yaml.bak`, outside the deleted adapter directory. Verify the
documented copy, delete and create sequence against an isolated custom config. This corrects documentation; backend
deletion behavior and architecture remain unchanged.
