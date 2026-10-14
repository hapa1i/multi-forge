# Native Claude permission/context trial

Status: **not run; skipped by user decision on 2026-10-15**. The user subsequently authorized merging PR #269 with this
evidence gap. Preserve the manifest as an unexecuted proposal; merge authorization is not permission to run it or use
another paid/native route. A2's native warning-delivery acceptance remains separate and unverified.

## Exact scope

The [manifest](native-manifest.json) contains eight fixed synthetic cases and pins the harness and production responder
content hashes. The [driver](../../../../../scripts/experiments/claude-hooks/policy-feedback.py) defaults to printing
that manifest. It requires an exact matching manifest plus a new absolute output directory to run; an existing output
cannot be reused. The trial stops at the first failed, inconclusive, timed-out or over-budget case, and does not retry
it.

Use local Claude Code **2.1.296**, pinned to its resolved executable path, and `claude-haiku-4-5-20251001`.
Authentication is the existing Anthropic API key from Forge's environment/credential-file chain. The child receives that
key in memory and uses canonical `https://api.anthropic.com`; there is no subscription, proxy or gateway fallback. If
the key is unavailable, stop before inference.

Each case has its own empty workspace, HOME, Claude config and Forge home below the new output directory. The only model
inputs are the manifest prompt, native tool definitions and synthetic `fixture.txt` content. No repository contents or
transcripts are selected. Parent instruction files cause refusal before dispatch. The prepared configuration excludes
user/project settings, skills, plugins, MCP connections, Chrome and native session persistence. Managed organization
policies can still apply; the evidence must confirm the observed tool and permission behavior instead of assuming those
policies are absent. The production `ClaudeHookResponder` is called by the probe hook; its authored marker is absent
from the user prompt.

## Cases and limits

For both Write and Edit, exercise feedback on/off with and without an explicit native allow rule. Edit may read the
synthetic file first. Only Read and the selected mutation tool are available. The hook admits at most one read and one
mutation, only to the declared file and values, and refuses malformed input or further attempts. There is no bypass
permission mode.

All cases use the CLI's manual mode and `--permission-prompts none`: a call that needs human approval is denied in this
headless trial. Cases with an explicit allow rule are the control. Capture native permission-denial evidence and actual
file content; a missing mutation alone is not proof of a permission gate. A successful allow-rule control must echo the
hook-only marker with feedback on and omit it with feedback off. This verifies native headless behavior; it does not
observe the interactive prompt renderer.

- At most eight native invocations, each with at most four agentic turns and a 90-second wall deadline.
- `--max-budget-usd 0.10` per invocation: **$0.80 planning allowance** across the eight cases. This is a CLI budget, not
  a guaranteed invoice cap or a physical HTTP-attempt limit. There are no driver retries or model fallbacks.
- Missing/malformed CLI cost estimates or an estimate above $0.10 stop the run before another invocation. Preserve
  unknown cost as unknown; the native CLI estimate is not provider-invoice evidence.
- All subprocesses run in owned process groups and are reaped on exit/timeout. Started cases and partial outputs remain
  inspectable locally. The resolved API key is removed from saved process output; it is never saved in the manifest.

The installed binary contains the hidden `--max-turns` option, independently checked without inference. The official
[CLI reference](https://code.claude.com/docs/en/cli-reference) documents turn/budget limits and print-mode permission
handling. The [permission modes](https://code.claude.com/docs/en/permissions#permission-modes) distinguish ordinary
approval from configured allows. The [hook contract](https://code.claude.com/docs/en/hooks#pretooluse-decision-control)
separates additional context from an explicit permission decision. These sources guide the trial; only retained live
results will establish receipt on this binary.

## Approval and execution

Only if the user later requests this trial and explicitly approves its revalidated scope and budget:

```bash
uv run python scripts/experiments/claude-hooks/policy-feedback.py \
  --run docs/board/done/claude_policy_feedback_permissions/evidence/native-manifest.json \
  --output /private/tmp/forge-claude-policy-feedback-20261014
```

Retain the raw local output under that new directory. Publish a sanitized report under this card with CLI/source hashes,
case outcomes, native denials, actual file results, marker receipt, cost estimates and limitations. Do not infer success
from a hook JSON fixture or a zero exit code. Any later interactive trial or rerun needs its own reviewed allowance.
