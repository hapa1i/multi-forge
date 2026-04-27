---
name: forge:panel
description: Multi-model panel review. Multiple models review independently, then findings are synthesized.
disable-model-invocation: true
argument-hint: '[target: path or instruction] [--output path] [--code] [--models m1,m2] [--roles r1,r2] [--review-type type] [--severity level]'
context: fork
allowed-tools: Bash, Read
---

# Panel Review

Run a panel review: fans out the same review task to multiple models in parallel, then synthesizes findings.

## Usage

```
/forge:panel [target] [--code] [--models model1,model2]
```

## Arguments

| Argument        | Required | Description                                                                  |
| --------------- | -------- | ---------------------------------------------------------------------------- |
| `target`        | Optional | File, directory, or instruction on what to review (defaults to cwd)          |
| `--code`        | Optional | Switch: use code review framework (default: document review)                 |
| `--models`      | Optional | Comma-separated model list (default: all available)                          |
| `--roles`       | Optional | Comma-separated reviewer roles (security, performance, architecture, ...)    |
| `--review-type` | Optional | Review focus: full, security, performance, quick (security/perf need --code) |
| `--severity`    | Optional | Minimum severity to report: high or critical                                 |
| `--output`      | Optional | Write result to file instead of conversation (e.g., `review.md`)             |

**Available models:** !`forge workflow list-models`

## Models Used

| Model            | Strength                             | Via                  |
| ---------------- | ------------------------------------ | -------------------- |
| `gpt-5.5`        | Logical problems, systematic review  | litellm-openai proxy |
| `gemini-2.5-pro` | Balanced analysis, large context     | litellm-gemini proxy |
| `claude-opus`    | Deep architecture, complex reasoning | Direct Anthropic     |

---

## Execution

### Step 1: Resolve Target and Flags

Parse `$ARGUMENTS` into a positional target and optional flags. The target is the first non-flag value (file path,
directory, or free-form instruction). Strip any leading `@` prefix on the target (Claude Code file reference syntax). If
no target is found, default to the current working directory.

Recognized flags (extract from `$ARGUMENTS` if present):

- `--code` — switch
- `--models <value>` — comma-separated model list
- `--roles <value>` — comma-separated role list
- `--review-type <value>` — one of: full, security, performance, quick
- `--severity <value>` — one of: high, critical
- `--output <path>` — write result to file instead of conversation

Never ask the user to clarify. If `$ARGUMENTS` contains anything, proceed immediately.

### Step 2: Run Multi-Model Review

Execute the panel workflow, forwarding all parsed flags:

```bash
forge workflow panel <target> [--code] [--models <models>] [--roles <roles>] [--review-type <type>] [--severity <sev>] --json --cwd "$(pwd)"
```

Omit any flag the user didn't specify.

Parse the JSON output. The structure is:

```json
{
  "prompt": "...",
  "results": {
    "gpt-5.5": {"response": "...", "error": null, "success": true, "duration_seconds": 45.2},
    "gemini-2.5-pro": {"response": "...", "error": null, "success": true, "duration_seconds": 38.1},
    "claude-opus": {"response": "...", "error": null, "success": true, "duration_seconds": 52.7}
  },
  "successful": 3,
  "failed": 0
}
```

### Step 3: Synthesize Results

Read `${CLAUDE_SKILL_DIR}/resources/synthesis.md` for synthesis instructions. If the file is missing, report the actual
missing-path problem and stop. Then respond with:

1. Consensus issues (found by 2+ models)
2. Unique findings from each model
3. Conflict resolution
4. Unified priority list
5. Suggested fix order based on dependencies

**Output routing:** If `--output` was specified, write the complete synthesis to that path using the Write tool (create
parent directories if needed). Print a one-line confirmation: `Wrote synthesis to {path}`. Do not also print the full
result in the conversation. If `--output` was not specified, print the result in the conversation as usual.

---

## Error Handling

- If 1 model fails: Include its error, synthesize from successful models
- If 2+ models fail: Report failure, do not attempt synthesis
- If proxy not available: `forge workflow panel` skips that model and reports the error in JSON

## Requirements

- **Forge CLI**: `forge` must be on PATH
- **Proxies**: GPT-5.5 and Gemini require active proxies (`forge proxy create litellm-openai`)
- **List available models**: `forge workflow list-models`
