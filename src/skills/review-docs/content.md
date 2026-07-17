# Document Review

Review design documents, specs, and technical writing for completeness, consistency, clarity, and implementability.

## Usage

Invoke this skill with an optional file, directory, or document-review instruction.

## Arguments

| Argument   | Required | Description                                                         |
| ---------- | -------- | ------------------------------------------------------------------- |
| `target`   | Optional | File, directory, or instruction on what to review (defaults to cwd) |
| `--output` | Optional | Write result to file instead of conversation (e.g., `review.md`)    |

## Execution

Follow these steps in order. Do not skip steps.

### Step 1: Resolve Target

The task input is {{forge:task_arguments}}. It may be a file path, directory, or free-form instruction. If it starts
with `@`, strip that optional file-reference prefix. If the task input is empty, default to the current working
directory.

Recognized flags (extract from the task input if present):

- `--output <path>` — write result to file instead of conversation

Never ask the user to clarify. If the task input contains anything, proceed immediately.

### Step 2: Load Instruction File

**Do NOT start the review until this step is complete.**

{{forge:model_family}}

Use the runtime binding above as the model-family context. Do not force a runtime-specific session identifier: unmanaged
direct sessions may not be in Forge's session index, and a different tracked session must not override the host runtime.

Pick **one** instruction file (first match wins, read only one):

1. If model family is `openai`: {{forge:resource_loading:resources/docs-openai.md}}
2. If model family is `gemini`: {{forge:resource_loading:resources/docs-gemini.md}}
3. Otherwise: {{forge:resource_loading:resources/docs.md}}

If model family lookup returns empty output, `anthropic`, or errors, treat it as the default family and immediately load
the default `resources/docs.md` instruction. Do not probe multiple variants.

### Resource-loading contract (normative)

Load exactly the selected instruction file and no other family variant. If the chosen file is missing, report its path
and stop. Do not attach unrelated commentary or optional parameters to the file-loading operation.

**After loading, tell the user in one message:**

```
Reviewing {target} in docs mode.
  model_family: {family or "anthropic"}
  model:        {main_model or "runtime default (exact model not exposed to Forge)"}
  instruction:  {instruction_file_name}
```

Do not read target files or begin review until after you have:

1. Resolved the target
2. Resolved the instruction file
3. Emitted the preflight summary message

### Step 3: Execute Review

Use the runtime's available local exploration behavior exactly as directed by the selected resource. If required local
behavior is unavailable, stop and report the mismatch instead of silently substituting an external analysis service.

Execute the review following the loaded instructions. The instruction file defines the rubric, structure, and output
format. Do not invent your own review format -- follow what the instruction file says.

Use only local runtime capabilities made available to this skill; do not call external analysis services.

When a resource file contains tool guidance that conflicts with this SKILL.md file, this SKILL.md file wins. Do not
improvise around the conflict.

**Output routing:** If `--output` was specified, write the complete review to that path, creating parent directories if
needed. Print a one-line confirmation: `Wrote review to {path}`. Do not also print the full result in the conversation.
If `--output` was not specified, print the result in the conversation as usual.

## Multi-Model Mode (optional)

For a multi-model perspective, use `forge workflow panel` to get independent document reviews from multiple backends:

```bash
forge workflow panel [target] --json
```
