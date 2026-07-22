# Panel Review

Run a panel review: fan out the same review task to multiple workers in parallel, then synthesize their findings.

## Usage

Invoke this skill with an optional target and workflow flags.

| Argument        | Required | Description                                                                  |
| --------------- | -------- | ---------------------------------------------------------------------------- |
| `target`        | Optional | File, directory, or instruction on what to review (defaults to cwd)          |
| `--code`        | Optional | Use the code-review framework (default: document review)                     |
| `--models`      | Optional | Comma-separated worker names (default: Forge workflow defaults)              |
| `--roles`       | Optional | Comma-separated reviewer roles (security, performance, architecture, ...)    |
| `--review-type` | Optional | Review focus: full, security, performance, quick (security/perf need --code) |
| `--severity`    | Optional | Minimum severity to report: high or critical                                 |
| `--output`      | Optional | Write the result to a file instead of the conversation                       |

## Execution

Execute the workflow now. Do not merely restate these instructions or ask the user to run the command unless a real
prerequisite is missing.

### Step 1: Resolve Target and Flags

The task input is {{forge:task_arguments}}. Parse it into a positional target and optional flags. The target is the
first non-flag value. Strip an optional leading `@` file-reference prefix. If no target is present, use the current
working directory.

Recognized flags:

- `--code`
- `--models <value>`
- `--roles <value>`
- `--review-type <value>`
- `--severity <value>`
- `--output <path>`

Never ask the user to clarify when the task input contains anything; proceed with the supplied input.

### Step 2: Check Worker Readiness

Execute `{{forge:forge_cli}} workflow list-models --json`. Use only workers whose status is `ready`. If an explicitly
requested worker is unavailable, report its stated recovery instead of silently substituting another worker. If no
workers are ready, report the missing prerequisites and stop.

The `codex` worker is opt-in and uses the model selected by the Codex runtime. Omitting `--models` retains the existing
Claude-backed workflow defaults.

### Step 3: Run the Panel

Execute, omitting flags the user did not supply:

```bash
{{forge:forge_cli}} workflow panel <target> [--code] [--models <models>] [--roles <roles>] [--review-type <type>] [--severity <severity>] --json --cwd "$(pwd)"
```

Parse the JSON result. Each `resolved_models` entry reports `runtime`, `requested_model`, `resolved_model`, `provider`,
`proxy`, `template`, `source`, and `model_selection`. A runtime-selected model has `resolved_model: null` and
`model_selection: runtime_default`; report that as "runtime default" rather than inventing a model name.

### Step 4: Synthesize Results

{{forge:resource_loading:resources/synthesis.md}}

If the resource is missing, report the missing path and stop. Apply it to the successful worker responses, then return:

0. Resolved workers used, including runtime and routing details from `resolved_models`
1. Consensus issues found by two or more workers
2. Unique findings from each worker
3. Conflict resolution
4. Unified priority list
5. Suggested fix order based on dependencies

If `--output` was supplied, write the complete synthesis to that path, creating parent directories if needed. Print
`Wrote synthesis to {path}` and do not also print the full result. Otherwise, return the synthesis in the conversation.

## Error Handling

- If one worker fails, include its error and synthesize the successful responses.
- If two or more workers fail, report the failure and do not synthesize.
- Surface the workflow's actual prerequisite or routing error; do not claim success from partial or invalid JSON.

## Runtime Requirements

- `{{forge:forge_cli}}` must be on `PATH`.
- Claude-backed workers require the local Claude runtime and any credentials or proxies reported by `list-models`.
- The `codex` worker requires a fresh successful `{{forge:forge_cli}} runtime preflight codex` cache entry.
