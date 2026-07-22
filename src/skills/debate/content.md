# Debate Evaluation

Run an adversarial multi-worker evaluation in which workers argue for, against, and neutrally about a subject.

## Usage

Invoke this skill with an optional subject and workflow flags.

| Argument   | Required | Description                                                                     |
| ---------- | -------- | ------------------------------------------------------------------------------- |
| `subject`  | Optional | File, directory, proposal, or instruction to evaluate (defaults to cwd)         |
| `--code`   | Optional | Use the code-evaluation framework (default: proposal)                           |
| `--models` | Optional | Comma-separated worker names (default: Forge workflow defaults)                 |
| `--worker` | Optional | Repeatable `model:stance` or `model:"custom prompt"`; exclusive with `--models` |
| `--output` | Optional | Write the result to a file instead of the conversation                          |

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

### Step 3: Run Adversarial Evaluation

Execute, omitting flags the user did not supply and never combining `--models` with `--worker`:

```bash
{{forge:forge_cli}} workflow debate "<subject>" [--code] [--models <models>] [--worker <spec>]... --json
```

Each worker receives a different stance. Parse the JSON result. Each `resolved_models` entry reports `runtime`,
`requested_model`, `resolved_model`, `provider`, `proxy`, `template`, `source`, `model_selection`, and stance. A
runtime-selected model has `resolved_model: null` and `model_selection: runtime_default`; report that as "runtime
default" rather than inventing a model name.

If the command fails, surface the actual error and stop; do not claim success.

### Step 4: Synthesize

Return:

0. Resolved workers used, including runtime, routing details, and stance
1. Points of agreement across all stances
2. Key disagreements and which stance has stronger evidence
3. Risk assessment from the critic's perspective
4. Viability assessment from the supporter's perspective
5. Overall recommendation with confidence level

Distinguish agreement across stances from disputed conclusions.

If `--output` was supplied, write the complete synthesis to that path, creating parent directories if needed. Print
`Wrote synthesis to {path}` and do not also print the full result. Otherwise, return the synthesis in the conversation.

## Models and Roles

Stances cycle through `for`, `against`, and `neutral` in worker order. In code mode, the supporter identifies strengths
and production readiness, the critic searches for bugs and architectural flaws, and the neutral worker gives a balanced
assessment with file-and-line evidence.

## Runtime Requirements

- `{{forge:forge_cli}}` must be on `PATH`.
- Claude-backed workers require the local Claude runtime and any credentials or proxies reported by `list-models`.
- The `codex` worker requires a fresh successful `{{forge:forge_cli}} runtime preflight codex` cache entry.
