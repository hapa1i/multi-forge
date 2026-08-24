# Correct Daily Review Findings 2026-08-24

**Lane**: `done/`

## Goal

Correct the nine current-main defects verified across transcript cleanup, model-route replay and launch, Markdown
candidate-state validation, and the shared route-catalog boundary.

## Scope

- Serialize every destructive relocated-transcript decision when the current and relocated UUIDs alias.
- Preserve Claude `[1m]` transport state across bare resume and inherited fork replay.
- Keep stored proxy template/source identity exact during bare replay and make explicit recovery bypass malformed stored
  routing.
- Apply the selected proxy tier to Claude, and stop automatic selection at the first admissible candidate.
- Keep lexical Git identity distinct from resolved filesystem identity in Markdown validation.
- Reject non-Claude direct route candidates and non-integer route-catalog schema versions with contextual errors.
- Preserve aliased-UUID agent-log cleanup, symlink-spelled manual link checks, and actionable first-candidate failures.

## Constraints

- Preserve the index-to-manifest lock order and conservative retention for cached positive transcript ownership.
- Preserve neutral route intent as the model/source authority while using `direct_model` only for validated Claude
  execution transport details.
- Preserve strict explicit proxy/direct precedence and hard failure after automatic candidate selection.
- Preserve resolved containment checks for Markdown targets while correcting candidate-state membership.
- Keep the packaged route catalog and existing public command shapes unchanged.

## Acceptance

1. A sibling published during aliased ordinary/relocated cleanup cannot retain a manifest without its transcript.
2. Direct and proxied Claude `[1m]` routes retain their modifier and 1,000,000-token preflight on bare replay.
3. Bare replay rejects template/source drift without mutating intent; the printed explicit recovery command succeeds.
4. Claude receives the persisted `selected_tier`, even when it differs from the model's intrinsic tier.
5. Automatic selection propagates compatibility failure from the first candidate that passes admission.
6. A staged-deleted symlink target fails Markdown candidate-state validation even when its referent remains tracked.
7. Route-catalog validation rejects non-Claude direct candidates, booleans, floats, and container schema versions.
8. Locked aliased-UUID cleanup reclaims sidechain logs only when no sibling owns the transcript.
9. Manual Markdown checks canonicalize a repository symlink prefix and never crash while printing a foreign source.
