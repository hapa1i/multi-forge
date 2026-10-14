# Jev Decisions probes

The default prints a fixed synthetic manifest without resolving credentials or making network requests:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/probe.py > /tmp/jev-early.json
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/probe.py --stage measurement > /tmp/jev-measurement.json
```

Review the exact payloads, hashes, endpoint, request cap and dated prices before approving a paid run. The early
manifest contains four single-question/schema controls, with a $0.01 planning budget. The measurement manifest contains
24 requests across eight shapes, three samples each, plus one over-limit control. Its $0.05 planning budget uses 32,000
input tokens per ordinary question and a separate 132,000-token allowance for the 120,234-byte over-limit control. These
are planning estimates, not provider-enforced invoice caps. Both manifests require ZDR, disable retries and use a
30-second deadline per request. Deterministic retry/rate-limit cases run offline in tests.

After explicit approval of the selected manifest:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/probe.py \
  --live --manifest /tmp/jev-early.json --output /tmp/jev-early-capture
```

The output directory must not exist. Credentials resolve through Forge's environment/file owner before the runner
creates an isolated `FORGE_HOME` there. Only resolved OpenRouter credentials are carried forward; no credentials file,
session or historical telemetry is copied. The runner clears cached runtime config after switching homes so grouping and
retention use the isolated home's defaults. Captures omit headers and redact keys and the account `user_id`. A hard
counter includes control requests. Unexpected status, unusable answers, changed model/pricing or excessive reported cost
stop the run; a post-response check cannot undo a charge. Missing cost stays unknown.

`capture.json` retains responses, timings, attempt counts and code hashes. `summary.json` uses nearest-rank p50/p95 of
end-to-end client calls, including cached credential lookup and local telemetry. Initial credential resolution and
manifest preparation are excluded. With three samples, p95 is the maximum; these numbers are not an SLA. Raw interrupted
results remain unchanged when a local parser fix later admits them.

Replay the retained early and measurement captures against the current answer validator, HTTP error classifier and
accounting checks without resolving credentials or making requests:

```bash
uv run pytest tests/src/scripts/test_jev_probe.py -k retained_capture_contract
```

To continue an interrupted capture after fixing a local parser/transport defect, use a new output directory and
`--resume <prior-capture.json>`. The runner checks the exact manifest, each completed response and its accounting, then
consumes only the remaining approved requests. Failed provider requests and accounting/model breaches cannot be
bypassed. Preserve both capture files and isolated telemetry homes; resume does not copy the previous ledger.

The synthetic malformed/over-limit controls replace the wire payload in the harness transport. They still use the
production client's auth, mandatory ZDR, deadline and telemetry. The normal production byte guard remains intact.

Use this harness from a development checkout. Retain sanitized evidence under
[the A1 card](../../../docs/board/doing/jev_client_probes/evidence/README.md). Ordinary tests inject `httpx` transports
and never call Jev; no fixture transport ships in `src/forge`.
