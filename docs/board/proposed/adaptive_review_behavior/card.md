# Adaptive review behavior -- useful work inside the cap

**Epic**: [epic_budgeted_review_guards](../epic_budgeted_review_guards/card.md) (M3 -- Forge-owned review adaptation).

**Lane**: `proposed/`. Depends on M2's envelope and workflow admission implementation; independent of M1's native-review
policy.

## Goal

Make Forge-owned review surfaces degrade gracefully inside the envelope rather than stopping mid-thought or refusing
outright. `/forge:review` stays the recommended single-agent path; multi-model workflows use explicit orchestration.
Claude's opaque native review protocol is not adapted here -- M1 may block, warn, or admit its launches, but Forge does
not rewrite its finder/verifier algorithm.

## `/forge:review` behavior

- **Size before Agent**: use deterministic git/path statistics to size the target before the one Explore launch; do not
  spend a second agent merely to scout.
- **Default narrow**: when the target is omitted and git state is available, review changed files. A cwd/repo-wide
  target requires an explicit envelope or narrows along `degrade_order` before Agent starts.
- **Prioritize once**: changed files, explicitly requested paths, high-risk modules, and relevant tests determine one
  bounded Explore prompt. The single-agent skill does not invent a verifier fan-out it does not currently own.
- **Emit a receipt**: final output names what was reviewed, what was skipped, and why (which cap forced narrowing).

## Workflow fan-out behavior

- **Prepare context once in code**: the workflow op assembles a bounded diff/context payload once and supplies the same
  prepared input to each model worker. Workers do not independently perform a repo-wide discovery pass.
- **Schedule in bounded batches**: replace the current all-at-once `run_parallel(requests)` call at the review-domain
  seam with envelope-sized batches. Do not schedule the next batch when estimated/observed usage threatens the synthesis
  reserve.
- **Preserve synthesis**: reserve enough budget for the existing parent synthesis and emit model/scope coverage even
  when later workers are skipped.
- **Receipt**: JSON and human output name scheduled/skipped workers, reviewed/skipped scope, accounting confidence, and
  the binding admission rule.

## Open Questions

- Should prepared workflow context be an ephemeral file referenced by workers or an inline prompt payload? The choice
  must work for host and sidecar workers and must not expose context outside the invocation.

## Acceptance Criteria

- `/forge:review` with no target uses changed files when available and launches at most its existing single Explore
  agent; a broad target narrows before that launch or requires an explicit envelope.
- Workflow workers receive one centrally prepared bounded context and do not independently re-read the full diff.
- Workflow scheduling occurs in envelope-sized batches; an unscheduled batch cannot spawn after the synthesis reserve
  binds.
- Both surfaces complete with a receipt listing reviewed/skipped scope and the binding admission rule.
- Native Claude review behavior is unchanged by M3 and is not used as an acceptance fixture for this member.
