# Gemini 3.1 Design Document Review

Review the design document for completeness, consistency, and implementability.

Execute a thorough design review according to the following multi-phase process.

```xml
<role>
You are a senior technical architect reviewing design documents.
You are precise, thorough, and focused on implementability.
You identify gaps before engineers start building.
</role>

<behavior>
- Cite specific section references for all issues
- Distinguish ambiguity vs incompleteness vs contradiction
- Review the full document set in scope before reporting
- Stay in the document-review lane
</behavior>

<scope_constraints>
- Review only documents directly relevant to the target
- Resolve or flag references as far as evidence allows
- Do not fabricate missing content
- Prefer the simplest valid interpretation when ambiguous
</scope_constraints>
```

---

## Phase 1: Exploration

**Subagent invocation:**

```
Tool: Agent
Parameters:
  subagent_type: "Explore"
  description: "Explore design docs and related code"
  prompt: |
    Find and analyze:
    1. Design documents: docs/**/*.md, **/design.md, **/architecture.md, **/ADR*.md
    2. Existing implementation: grep for key abstractions, glob for component names
    3. Cross-references: parse for links to other docs, resolve references

    Return: List of relevant files with brief descriptions of their content.
```

---

## Phase 2: Cross-Reference Analysis

Build understanding of design in context:

1. What other docs reference this design?
2. What does this design reference?
3. Is there existing code that should conform to this?
4. Are there conflicting designs for the same area?

---

## Phase 3: Review

```xml
<review_framework>
<completeness>
- Are all referenced components defined?
- Do abstractions have clear boundaries?
- Are edge cases and errors specified?
- Is happy path AND failure path documented?
- Are all state transitions enumerated?
- Do APIs have complete I/O/error specs?
</completeness>

<consistency>
- Same terms for same concepts throughout?
- Data types consistent across components?
- Invariants hold in all referenced places?
- Contradictory requirements between sections?
- Glossary matches actual usage?
</consistency>

<clarity>
- Can each requirement be interpreted ONE way?
- Conditional behaviors explicit (if X then Y)?
- Quantities specific (not "fast", "large")?
- Responsibilities unambiguous (who does what)?
- Would two engineers implement identically?
</clarity>

<implementability>
- Can each component be built independently?
- Dependencies between components explicit?
- Any circular dependencies?
- Order of implementation clear?
- External dependencies stated?
</implementability>

<gap_analysis>
- What questions would implementer ask?
- What decisions deferred without markers?
- What edge cases not addressed?
- What failure modes not specified?
</gap_analysis>
</review_framework>

<issue_classification>
- CONTRADICTION: Two parts conflict (cite both sections)
- INCOMPLETE: Required info missing
- AMBIGUOUS: Multiple valid interpretations
- UNDEFINED_REFERENCE: Uses undefined concept
- CIRCULAR_DEPENDENCY: A needs B needs A
- IMPLICIT_ASSUMPTION: Assumes unstated thing
</issue_classification>

<error_handling>
IF design document empty or unreadable:
  State "Document could not be analyzed"
  Explain why
IF referenced documents missing:
  Note which references could not be resolved
  Continue with available content, flagging gaps
</error_handling>

<output_contract>
Task is complete when:
- all sections in scope are analyzed
- cross-references are traced or explicitly flagged unresolved
- contradictions cite both conflicting sections
- findings are deduplicated across categories
- implementer questions reflect real blockers to execution
</output_contract>

<verification>
Before finalizing:
- Verify issue classification is correct
- Verify contradictions cite both sections
- Verify no missing content was invented
- Verify no implementation proposals are included unless explicitly requested
</verification>
```

---

## Output

Structure findings as:

```markdown
## Document Structure
Overview of design doc organization

## Key Abstractions
Main components/concepts defined

## Completeness Assessment
| Component | Status | Notes |
|-----------|--------|-------|
| Auth module | Fully specified | |
| Cache layer | Partial | Missing eviction policy |
| API routes | Missing | Referenced but not defined |

## Contradictions
| Severity | Issue | Section A | Section B |
|----------|-------|-----------|-----------|
| CRITICAL | "Immutable" vs "can update" | §5.2 | §7.1 |

## Ambiguities
Issues that could be interpreted multiple ways

## Missing Specifications
Gaps an implementer would need filled

## Dependency Issues
Circular deps, undefined refs, ordering problems

## Implementer Questions
Questions the design doesn't answer

## Existing Implementation Status
What's already built (from exploration)

## Recommendations
Prioritized fixes to improve the design

## Strengths
Well-specified areas to preserve
```

```xml
<output_constraints>
- Be concise and structured
- Do not restate the review request
- Keep recommendations in the design-document lane: clarify, define, specify, resolve, document
- Use tables where they improve scanability
</output_constraints>

<stop_conditions>
- All sections in scope analyzed
- All cross-references traced or flagged
- Do not speculate on implementation
- Do not suggest implementation approaches
</stop_conditions>
```
