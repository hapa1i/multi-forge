# Forge Architecture History

Retired architecture retained verbatim so removal rationale and non-goals remain reviewable without occupying the
shipped design contracts.

[Current architecture map](design.md)

---

## F. Removed Experimental WorkflowPolicy Bundle

The experimental, manifest-only `workflow` policy bundle and its tagger -> checker -> reviewer implementation were
removed. The preset lacked a normative project-pattern corpus, so its stateless reviewer could not substantiate the
citations required for a blocking architectural-divergence verdict.

The policy registry now rejects unknown bundle names and unknown `bundle_config` owners before registering any policy.
For existing sessions, `workflow` in `policy.bundles` or `policy.bundle_config.workflow` produces an actionable removal
diagnostic. The Claude and Codex policy hooks report that construction failure and allow the action before engine-owned
`fail_mode` semantics apply. Because session overrides take precedence over intent, recovery starts with
`forge session reset policy`; the user then runs terminal `forge policy enable` with supported bundles or
`forge policy disable`.

---
