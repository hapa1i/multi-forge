# Deep Analysis

Run a deep single-worker analysis of a topic, question, or architectural decision.

## Usage

Invoke this skill with an optional topic and workflow flags.

| Argument   | Required | Description                                                                           |
| ---------- | -------- | ------------------------------------------------------------------------------------- |
| `topic`    | Optional | Question, file, directory, or instruction to analyze (ask only when entirely omitted) |
| `--models` | Optional | Comma-separated worker names (default: `claude-opus`)                                 |
| `--output` | Optional | Write the result to a file instead of the conversation                                |

## Execution

Execute the workflow now. Do not merely restate these instructions or ask the user to run the command unless a real
prerequisite is missing.

### Step 1: Resolve Topic and Flags

The task input is {{forge:task_arguments}}. Parse it into a topic and optional flags. The topic is everything that is
not a recognized flag. Strip an optional leading `@` file-reference prefix. If the task input is empty, ask what the
user wants to analyze.

Recognized flags:

- `--models <value>`
- `--output <path>`

Never ask the user to clarify when the task input contains anything; proceed with the supplied input.

### Step 2: Check Worker Readiness

Execute `{{forge:forge_cli}} workflow list-models --json`. Use only workers whose status is `ready`. If an explicitly
requested worker is unavailable, report its stated recovery instead of silently substituting another worker.

The `codex` worker is opt-in and uses the model selected by the Codex runtime. Omitting `--models` retains the existing
`claude-opus` default.

### Step 3: Run Deep Analysis

Execute, omitting `--models` when the user did not supply it:

```bash
{{forge:forge_cli}} workflow analyze "<topic>" [--models <models>] --json
```

If the command exits nonzero or returns invalid JSON, report the error and stop. Do not parse partial output or
fabricate a response.

### Step 4: Present Analysis

Format the worker's analysis as:

0. Resolved worker used, including `runtime`, requested model, resolved model, provider, proxy, and template
1. Problem decomposition
2. Key evidence and considerations
3. Analysis and trade-offs
4. Recommendations with rationale

A runtime-selected worker has `resolved_model: null` and `model_selection: runtime_default`; report that as "runtime
default" rather than inventing a model name. If the worker failed, report its error and suggest retrying.

If `--output` was supplied, write the complete analysis to that path, creating parent directories if needed. Print
`Wrote analysis to {path}` and do not also print the full result. Otherwise, return the analysis in the conversation.

## Runtime Requirements

- `{{forge:forge_cli}}` must be on `PATH`.
- Claude-backed workers require the local Claude runtime and any credentials or proxies reported by `list-models`.
- The `codex` worker requires a fresh successful `{{forge:forge_cli}} runtime preflight codex` cache entry.
