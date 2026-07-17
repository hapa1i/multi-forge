# Understand

Analyze code or documentation to extract clear explanations of structure, design, and behavior.

## Usage

Invoke this skill with an optional target, mode, and depth.

## Arguments

| Argument   | Required | Description                                                                    |
| ---------- | -------- | ------------------------------------------------------------------------------ |
| `target`   | Optional | File, directory, question, or instruction on what to explain (defaults to cwd) |
| `--mode`   | Optional | `code` or `docs` (default: auto-detected from target)                          |
| `--depth`  | Optional | `quick`, `detailed`, or `deep` (default: `detailed`)                           |
| `--output` | Optional | Write result to file instead of conversation (e.g., `explanation.md`)          |

## Execution

Follow these steps in order. Do not skip steps.

### Step 1: Resolve Target

The task input is {{forge:task_arguments}}. It may be a file path, directory, question, or free-form instruction. If it
starts with `@`, strip that optional file-reference prefix. If the task input is empty, default to the current working
directory.

Recognized flags (extract from the task input if present):

- `--mode <value>` — code or docs
- `--depth <value>` — quick, detailed, or deep
- `--output <path>` — write result to file instead of conversation

Never ask the user to clarify. If the task input contains anything, proceed immediately.

### Step 2: Detect Mode

If `--mode` was not specified, auto-detect from the target (first match wins):

| Pattern                                                                        | Mode |
| ------------------------------------------------------------------------------ | ---- |
| `*.md`, `*.rst`, `*.txt`                                                       | docs |
| `*.py`, `*.ts`, `*.js`, `*.go`, `*.rs`, `*.java`                               | code |
| Path starts with `docs/`, `design/`, `adr/`, `rfcs/`                           | docs |
| Path starts with `src/`, `lib/`, `pkg/`, `cmd/`                                | code |
| `README*`, repository instruction files, `CHANGELOG*`                          | docs |
| Question contains "design", "architecture", "rationale", "ADR", "why we chose" | docs |
| Question contains "bug", "function", "class", "method", "how does"             | code |
| Default                                                                        | code |

Do not ask the user -- just apply the rules.

### Step 3: Load Instruction File

**Do NOT start the analysis until this step is complete.**

{{forge:model_family}}

Use the runtime binding above as the model-family context. Do not force a runtime-specific session identifier: unmanaged
direct sessions may not be in Forge's session index, and a different tracked session must not override the host runtime.

Pick **one** instruction file (first match wins, read only one):

1. Code mode with model family `openai`: {{forge:resource_loading:resources/code-openai.md}}
2. Code mode with model family `gemini`: {{forge:resource_loading:resources/code-gemini.md}}
3. Code mode with any other family: {{forge:resource_loading:resources/code.md}}
4. Docs mode with model family `openai`: {{forge:resource_loading:resources/docs-openai.md}}
5. Docs mode with model family `gemini`: {{forge:resource_loading:resources/docs-gemini.md}}
6. Docs mode with any other family: {{forge:resource_loading:resources/docs.md}}

If model family lookup returns empty output, `anthropic`, or errors, treat it as the default family and immediately load
the default resource for the selected mode. Do not probe multiple variants.

### Resource-loading contract (normative)

Load exactly the selected instruction file and no other family or mode variant. If the chosen file is missing, report
its path and stop. Do not attach unrelated commentary or optional parameters to the file-loading operation.

**After loading, tell the user in one message:**

```
Analyzing {target} in {mode} mode (depth: {depth}).
  model_family: {family or "anthropic"}
  model:        {main_model or "runtime default (exact model not exposed to Forge)"}
  instruction:  {instruction_file_name}
```

Do not read target files or begin analysis until after you have:

1. Resolved the target
2. Resolved the mode
3. Resolved the instruction file
4. Emitted the preflight summary message

### Step 4: Execute Analysis

Use the runtime's available local exploration behavior exactly as directed by the selected resource. If required local
behavior is unavailable, stop and report the mismatch instead of silently substituting an external analysis service.

For depth handling inside this skill:

- `quick`: perform a concise local analysis using the allowed tools in this skill
- `detailed`: perform a fuller local analysis using the allowed tools in this skill
- `deep`: perform the deepest local analysis available with the allowed tools in this skill

Use only local runtime capabilities made available to this skill; do not call external analysis services.

Execute analysis following the loaded instructions with the specified depth. The instruction file defines the structure
and output format -- follow it.

**Depth levels:**

| Depth      | Output Size | Execution                        |
| ---------- | ----------- | -------------------------------- |
| `quick`    | \<500 words | Local analysis, concise          |
| `detailed` | 500-1000    | Local analysis, fuller coverage  |
| `deep`     | Full        | Local analysis, maximum coverage |

When a resource file contains tool guidance that conflicts with this skill's allowed tools, this SKILL.md file wins. Do
not improvise around the conflict.

**Output routing:** If `--output` was specified, write the complete explanation to that path, creating parent
directories if needed. Print a one-line confirmation: `Wrote explanation to {path}`. Do not also print the full result
in the conversation. If `--output` was not specified, print the result in the conversation as usual.
