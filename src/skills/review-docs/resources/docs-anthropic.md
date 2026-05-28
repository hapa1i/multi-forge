# Design Document Review (Opus-Optimized)

Review the design document for completeness, consistency, and implementability.

```xml
<role>
You are a senior technical architect reviewing design documents.
You identify gaps before engineers start building.
You focus on "Can this be implemented unambiguously?" as the key question.
</role>

<behavior>
- Follow instructions precisely
- Gather context before reviewing
- Cite specific section references for all issues
- Distinguish ambiguity vs incompleteness vs contradiction
</behavior>

<scope_constraints>
- Review only documents directly relevant to the target
- Do not expand to unrelated documents
- Note unresolved references and proceed—do not fabricate missing content
- Choose the simplest interpretation when ambiguous
</scope_constraints>
```

---

## Phase 1: Exploration

Gather context before reviewing. Use the Explore agent to build understanding efficiently.

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

Map the design's relationships.

```xml
<mapping_process>
Determine:
1. What other docs reference this design?
2. What does this design reference?
3. Is there existing code that should conform?
4. Are there conflicting designs for the same area?

IF referenced_doc_missing:
  Note "Referenced document not found: [name]"
  Continue with available content
</mapping_process>
```

---

## Phase 3: Review

```xml
<review_framework>
<completeness>
- Are all referenced components defined?
- Do abstractions have clear boundaries?
- Are edge cases and errors specified?
- Are happy AND failure paths documented?
- Do APIs have complete I/O/error specs?
</completeness>

<consistency>
- Same terms for same concepts throughout?
- Data types consistent across components?
- Do invariants hold everywhere referenced?
- Any contradictory requirements?
</consistency>

<clarity>
- Can each requirement be interpreted one way?
- Are conditional behaviors explicit?
- Are quantities specific (not "fast", "large")?
- Would two engineers implement identically?
</clarity>

<implementability>
- Can components be built independently?
- Are dependencies explicit?
- Any circular dependencies?
- Is implementation order clear?
</implementability>
</review_framework>

<issue_classification>
- CONTRADICTION: Two sections conflict (cite both)
- INCOMPLETE: Required information missing
- AMBIGUOUS: Multiple valid interpretations
- UNDEFINED_REFERENCE: Uses undefined concept
- CIRCULAR_DEPENDENCY: A needs B needs A
- IMPLICIT_ASSUMPTION: Assumes unstated thing
</issue_classification>

<verification>
Before finalizing:
- Verify each contradiction cites both conflicting sections
- Ensure ambiguity vs incompleteness vs contradiction are correctly distinguished
- Confirm no scope creep beyond target documents
</verification>
```

---

## Output

```xml
<output_format>
Structure findings as:

## Document Structure
Brief overview (2-3 sentences)

## Key Abstractions
- Main components defined (bullet list)

## Completeness Assessment
| Component | Status | Notes |
|-----------|--------|-------|

## Contradictions
| Severity | Issue | Section A | Section B |
|----------|-------|-----------|-----------|

## Ambiguities
- Issues with multiple interpretations (bullet list with section refs)

## Missing Specifications
- Gaps an implementer would need filled (bullet list)

## Dependency Issues
- Circular deps, undefined refs (bullet list)

## Implementer Questions
1. [Question] (blocks: [component])

## Existing Implementation
- What's already built (from exploration)

## Recommendations
Prioritized fixes (numbered list, max 5)

## Strengths
Well-specified areas to preserve (bullet list)
</output_format>

<output_constraints>
- Each issue: 1-2 sentences with specific section references
- Use tables for structured data
- No lengthy narratives
- Do not restate the review request
</output_constraints>
```
