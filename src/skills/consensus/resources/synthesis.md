# Consensus Synthesis Instructions

You have received results from a two-round consensus workflow. Round 1 contains independent positions from role-assigned
models. Round 2 contains reconciled recommendations after each model reviewed all Round 1 positions.

Your task is to synthesize these into a unified consensus report.

**Key principle**: The reconciliation process -- how and whether models converged -- is as valuable as the final
positions. Surface the dynamics, not just the outcomes.

## Synthesis Framework

### 1. Identify Points of Agreement

Recommendations that ALL perspectives converged on during reconciliation (Round 2). These are high-confidence findings.

```markdown
## Agreed Recommendations (High Confidence)

- **[Recommendation]** (all perspectives agree)
  - Evidence: [supporting reasoning from multiple roles]
```

### 2. Identify Partial Agreement

Recommendations where MOST perspectives agree but with different emphasis or conditions:

```markdown
## Partially Agreed (Moderate Confidence)

- **[Recommendation]**
  - Agreeing: [roles that support]
  - Dissenting: [role] -- [reason for different emphasis]
  - Conditions: [if applicable]
```

### 3. Identify Remaining Disagreements

Points where consensus was NOT reached after reconciliation. This should be the most detailed section -- remaining
disagreements expose genuine analytical uncertainty and are often the most valuable findings for the reader.

For each unresolved point:

- Which perspectives disagree and why
- How positions shifted (or hardened) between Round 1 and Round 2
- Which position has stronger evidence
- Whether the disagreement is fundamental or a matter of emphasis
- What the disagreement reveals about the underlying problem's complexity

```markdown
## No Consensus

- **[Point of disagreement]**
  - [Role A]: [position and reasoning]
  - [Role B]: [position and reasoning]
  - Assessment: [which has stronger evidence, or why this is genuinely unresolvable]
```

**Convergence dynamics**: For each recommendation in sections 1-3, briefly note how positions shifted between rounds.
Did Round 2 reconciliation move perspectives closer, or did it sharpen the disagreement? The trajectory matters as much
as the final position.

### 4. Final Recommendation

Based on the synthesis above:

- If full consensus: State the shared recommendation with confidence level
- If partial consensus: State what was agreed, flag what was not, recommend which disputed position to follow and why
- If no consensus: Explicitly state "NO CONSENSUS" and explain the fundamental disagreements that prevented convergence

### 5. Confidence Assessment

- Consensus strength: strong | moderate | weak | none
- What would strengthen the consensus?
- What caveats apply?

## Output Format

```markdown
# Consensus Report: [Subject]

## Summary
- Models consulted: N
- Roles: [list]
- Consensus strength: strong|moderate|weak|none

## Agreed Recommendations (High Confidence)
[...]

## Partially Agreed (Moderate Confidence)
[...]

## No Consensus
[...]

## Overall Recommendation
[...]

## Confidence and Caveats
[...]
```
