# Challenge

Pressure-test a claim, recommendation, or assumption with adversarial skepticism.

## Usage

Invoke this skill with an optional claim, objection, or question to pressure-test.

## Arguments

| Argument | Required | Description                                                            |
| -------- | -------- | ---------------------------------------------------------------------- |
| `claim`  | Optional | Statement, objection, or question to pressure-test (inferred if empty) |

---

## Execution

### Step 1: Resolve Claim

The task input is {{forge:task_arguments}}. Treat it as the claim to challenge. It should be a statement, objection,
question, or instruction -- not a bare file path. If it starts with `@`, strip that optional file-reference prefix.

If the task input is empty, infer the claim from the immediately preceding conversation context: the last
recommendation, decision, assertion, or proposed change. Only ask the user what to challenge if no prior claim is
identifiable from context.

Never ask the user to clarify if a claim was provided. If the task input contains anything, proceed immediately.

### Step 2: Challenge

This skill defaults to **skepticism, not balance**. The starting posture is adversarial: assume the claim may be wrong
and try to prove that. Only soften to a balanced conclusion if the skeptical case genuinely fails.

If the challenge starts from a neutral or symmetrical frame, it provides no value over a standard analysis. The entire
point is targeted pressure-testing.

Execute these steps:

1. **Restate the claim precisely.** What exactly is being asserted? Remove ambiguity.

2. **Assume it is wrong.** Actively search for:

   - Flaws in reasoning or hidden assumptions
   - Counterexamples from the codebase or known constraints
   - Missing edge cases or failure modes
   - Simpler alternatives that would invalidate the complexity
   - Contradictions with existing architecture or decisions

3. **Investigate the repo.** Search and read repository files to find evidence. Check whether the claim holds against
   actual code, tests, configuration, and documented decisions. Do not reason from first principles alone when evidence
   is available.

4. **Test the skeptical case.** Is the counterargument strong, or does it fall apart under scrutiny?

5. **If the skeptical case fails,** explain clearly why the original claim survives. This is a valid and useful outcome
   -- the claim is stronger for having been tested.

6. **Return a verdict:**

   - **Concern validated** -- the skeptical case holds; the claim has real problems
   - **Partially validated** -- some aspects hold, others don't; specific issues identified
   - **Concern not supported** -- the skeptical case failed; the claim survives scrutiny
   - **Insufficient evidence** -- cannot determine either way from available information

### Step 3: Format Output

Present the challenge as:

```
## Challenge: [restated claim]

### Skeptical Case
[The strongest argument against the claim, with evidence]

### Counter-Evidence
[What supports the claim, why the skeptical case fails (if it does)]

### Verdict: [verdict]
[1-2 sentence summary of the conclusion]
```
