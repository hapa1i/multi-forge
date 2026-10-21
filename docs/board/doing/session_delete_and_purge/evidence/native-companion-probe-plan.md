# Companion metadata capture

This follow-up was separately approved and executed once on 2026-10-20. Its
[execution record](native-companion-probe-20261020/execution.json) confirms verified export and container removal. The
[native result](native-companion-probe-20261020/container-evidence/native-result.json) reports one completed subagent,
4.091 seconds, and $0.0170009. The first approved call completed one subagent for a reported $0.01699045, but the purge
planner refused its uncharacterized `agent-<id>.meta.json` companion. The first capture saved that file's path, size,
and hash; it did not save the JSON object. The disposable container was removed after evidence export. Its results
remain in [the first execution record](native-probe-20261020/execution.json).

The [fixed follow-up manifest](native-companion-probe-manifest.json) retains the first probe's exact Claude 2.1.245
command, Haiku model, prompt, one invocation, one requested subagent, two parent turns, 512 output-token setting,
90-second timeout, and $0.10 CLI cap. It invokes no Codex client. The fresh container name is
`forge-native-purge-companion-20261020`. There are no host mounts or repository tools in the prompt. Authentication is
forwarded by the environment-variable name `ANTHROPIC_API_KEY`; no login store is copied.

This capture adds only generated `projects/<namespace>/<session>/subagents/*.meta.json` objects, limited to 64 KiB each,
alongside the synthetic parent and agent JSONL, file hashes, binary and image identity, runtime PID census, and native
result. It requires exactly one completed subagent and one metadata companion. Missing evidence is a failed probe with
no inference retry. It does not change the native planner or treat a companion as deletion authority.

The runner verifies exported files against the container's SHA-256 inventory before removal. After capture it removes
the disposable runtime home and stops the exact container. Successful, verified exports permit container removal;
failures retain the stopped container's `/probe/evidence` for diagnosis without its runtime home.

Manifest SHA-256: `20f0af8172af71995d463ff03efa7292d0e9c0b752b379c500d750d3ebea38d1`. The manifest also pins the capture
payload's SHA-256. Its [generator](../../../../../scripts/experiments/session-purge/native-companion-probe-manifest.py)
is offline.

The approved execution command was:

```bash
direnv exec . .venv/bin/python scripts/experiments/session-purge/run_native_probe.py \
  --manifest docs/board/doing/session_delete_and_purge/evidence/native-companion-probe-manifest.json \
  --output /Users/habib/workspace/multi-forge/docs/board/doing/session_delete_and_purge/evidence/native-companion-probe-20261020
```

The CLI cap and timeout are operational bounds, not a guaranteed HTTP-request count or invoice cap. This capture
preceded the metadata validator implementation; it establishes the observed layout, not a paid execution of that later
implementation. Subsequent lifecycle checks use the saved bytes offline.
