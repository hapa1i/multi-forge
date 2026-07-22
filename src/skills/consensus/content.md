# Consensus Workflow

Run a multi-worker consensus workflow in which role-assigned workers build a shared recommendation through two rounds of
evaluation and reconciliation.

## Usage

Invoke this skill with an optional subject and workflow flags.

| Argument   | Required | Description                                                                   |
| ---------- | -------- | ----------------------------------------------------------------------------- |
| `subject`  | Optional | File, directory, proposal, or instruction to evaluate (defaults to cwd)       |
| `--code`   | Optional | Use the code-evaluation framework (default: proposal)                         |
| `--models` | Optional | Comma-separated worker names (default: Forge workflow defaults)               |
| `--worker` | Optional | Repeatable `model:role` or `model:"custom prompt"`; exclusive with `--models` |
| `--output` | Optional | Write the result to a file instead of the conversation                        |

## Execution

Execute the workflow now. Do not merely restate these instructions or ask the user to run the command unless a real
prerequisite is missing.

### Step 1: Resolve Subject and Flags

The task input is {{forge:task_arguments}}. Parse it into a subject and optional flags. The subject is everything that
is not a recognized flag. Strip an optional leading `@` file-reference prefix. If no subject is present, use the current
working directory.

Recognized flags:

- `--code`
- `--models <value>`
- `--worker <value>` (repeatable)
- `--output <path>`

Never ask the user to clarify when the task input contains anything; proceed with the supplied input.

### Step 2: Check Worker Readiness

Execute `{{forge:forge_cli}} workflow list-models --json`. Use only workers whose status is `ready`. If an explicitly
requested worker is unavailable, report its stated recovery instead of silently substituting another worker. If no
workers are ready, report the missing prerequisites and stop.

The `codex` worker is opt-in and uses the model selected by the Codex runtime. Omitting `--models` retains the existing
Claude-backed workflow defaults.

### Step 3: Run the Consensus Workflow

Execute, omitting flags the user did not supply and never combining `--models` with `--worker`:

```bash
{{forge:forge_cli}} workflow consensus "<subject>" [--code] [--models <models>] [--worker <spec>]... --json
```

Parse the two-round JSON result:

- Round 1: each worker independently evaluates the subject from its assigned role.
- Round 2: each worker receives all Round 1 positions and produces a reconciled recommendation.
- Each `resolved_models` entry reports `runtime`, `requested_model`, `resolved_model`, `provider`, `proxy`, `template`,
  `source`, `model_selection`, and role.

A runtime-selected model has `resolved_model: null` and `model_selection: runtime_default`; report that as "runtime
default" rather than inventing a model name. If the command fails, surface the actual error and stop.

### Step 4: Synthesize

{{forge:resource_loading:resources/synthesis.md}}

If the resource is missing, report the missing path and stop. Apply its rules to both rounds. Start the report with a
"Resolved Workers Used" section that includes each worker's runtime, routing details, and role.

If `--output` was supplied, write the complete synthesis to that path, creating parent directories if needed. Print
`Wrote synthesis to {path}` and do not also print the full result. Otherwise, return the synthesis in the conversation.

## Models and Roles

Roles cycle through worker order. Proposal mode defaults to architecture, security, and correctness. Code mode defaults
to architecture, security, and maintainability. Explicit roles are `architecture`, `security`, `correctness`,
`maintainability`, and `performance`; use `--worker` for an exact worker-to-role mapping.

## Runtime Requirements

- `{{forge:forge_cli}}` must be on `PATH`.
- Claude-backed workers require the local Claude runtime and any credentials or proxies reported by `list-models`.
- The `codex` worker requires a fresh successful `{{forge:forge_cli}} runtime preflight codex` cache entry.
