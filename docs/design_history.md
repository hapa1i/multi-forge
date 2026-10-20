# Forge Architecture History

Retired architecture and removal decisions remain reviewable without occupying the shipped design contracts.

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

## G. Removed Jev Rule-pack and Cascade Experiments

The Jev consumer epic and A2/A3 were retired on 2026-10-19. A2's tested rule failed its bounded model screen; A3's first
synthetic packet offered no human-positive cases beyond deterministic controls. Neither consumer was activated. Their
experiment runners, provisional rule definitions and outcome combiner, session-consent helpers and dedicated evaluation
tests were subsequently removed. Ordinary policy and session paths no longer carry the unused consent checks; the policy
registry rejects the unsupported bundle through its existing unknown-bundle validation.

A1's typed judgment client, ZDR enforcement, attempt accounting, explicit run identity and transport probes remain
shipped. The independent Claude permission-feedback fix and supervisor behavior are unchanged. Human adjudications,
corpora, manifests, captures and source hashes remain historical evidence, without a model-quality or runtime claim. The
[source archive](board/retired/epic_jev_support/source-archive.md) identifies the final complete experiment revision and
the removed design contract. Reconsideration requires a new proposed card and its own bounded evidence plan.
