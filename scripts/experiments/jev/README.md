# Jev Decisions probes

The A2 `rule-pack-eval.py` harness prepares the wrapper corpus and evaluates saved responses without a live mode. See
its [evaluation plan](../../../docs/board/doing/jev_rule_pack/evidence/evaluation-plan.md) for manifests, explicit
threshold settings, label provenance and metric limitations. The paid transport probe below remains separate.

Use `--review-packet` to export case evidence with authored labels/rationales withheld, and `--import-review <path>` to
validate a human-completed packet and emit a new corpus on stdout. See the
[human review instructions](../../../docs/board/doing/jev_rule_pack/evidence/human-review.md) for partial reviews,
explicit replacement and disagreement/exclusion handling. These commands do not call a provider.

Shared module ownership is in [rule-pack design](../../../docs/design_rule_packs.md).

Prepare the separate decomposition diagnostic packet without credentials or dispatch:

```bash
uv run python scripts/experiments/jev/rule-pack-diagnostic.py > /tmp/jev-diagnostic-review.json
uv run python scripts/experiments/jev/rule-pack-diagnostic.py --case validation-boundary
uv run python scripts/experiments/jev/rule-pack-diagnostic.py --validate-review /tmp/jev-diagnostic-review.json
```

The [diagnostic review guide](../../../docs/board/doing/jev_rule_pack/evidence/diagnostic-human-review.md) links the
blank worksheets and completed ledger. This packet has separate criteria and identities; old human labels do not answer
its new questions. Validation checks a retained partial ledger without importing labels into the active corpus.
Active-rule provenance is separate from diagnostic answer identity. `--carry-review <ledger.json>` explicitly prepares a
new partial ledger, retaining only unchanged question contexts and their source attribution; changed answers and
contract decisions reopen. The review guide describes source bindings and new human review. Diagnostic draft 3 has 32
carried answers and 63 renewed answers; all 95 questions and the revised contract are reviewed. The
[bounded study plan](../../../docs/board/doing/jev_rule_pack/evidence/bounded-feasibility-plan.md) proposes hard stops
and a stronger-model reference arm. The
[capture review packet](../../../docs/board/doing/jev_rule_pack/evidence/bounded-capture-review.md) links the exact
manifest and reproduction commands for `diagnostic_manifest.py`. Preparation and validation are offline; a manifest does
not grant paid approval. After explicit approval,
`diagnostic_capture.py --live --manifest <manifest.json> --review <completed-review.json> --catalog <catalog.json> --output <new-absolute-directory>`
executes the fixed two-arm study. The output must be new and private. It includes an isolated Forge home, a durable
journal and a scored report. Catalog drift refuses dispatch; technical failures stop the whole study and repeated
sentinel errors stop the affected arm. There are no retries or resume mode, and a consumed proposal cannot be started
again. The existing calibration capture command does not execute this study.

Both capture replay guards recognize published journals that reference a retained manifest. References must remain
inside the evidence directory, avoid symlinks and match the manifest digest. A diagnostic publication cannot block an
unrelated calibration proposal merely because its manifest is referenced, or permit its own replay after a local claim
is lost. Invalid references refuse the scan.

Compare the same action evidence with marker and AST signals without dispatching requests:

```bash
uv run python scripts/experiments/jev/rule-pack-baselines.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json > /tmp/jev-baselines.json
```

These are raw candidate signals, not semantic judgments. The AST detector supports complete Python `Edit` declarations;
partial edits and patches remain unsupported. Required callback/validation adapters can also be flagged. Neither
baseline reads the supplied file path or uses human labels to choose a signal.

Compare the fixed 12-case diagnostic review and 17-case constructed corpus locally:

```bash
uv run python scripts/experiments/jev/rule-pack-offline.py \
  --review docs/board/doing/jev_rule_pack/evidence/diagnostic-review-2026-10-18-batch-6.json \
  --corpus docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json
```

The
[offline retention/admission review](../../../docs/board/doing/jev_rule_pack/evidence/offline-retention-admission.md)
explains the prospective dependency table and retained report. Syntax spans and candidate differences are observations,
not new human labels or quality scores. The cohorts overlap. This command has no live mode or native acquisition, and
the completed diagnostic capture remains failed under its original contract.

Prepare A2's nine-request constructed calibration manifest without credential access:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python scripts/experiments/jev/rule-pack-capture.py > /tmp/jev-calibration.json
```

Both retained calibration approvals are consumed. The
[completed calibration plan](../../../docs/board/doing/jev_rule_pack/evidence/calibration-boundary-run-plan.md) records
historical scope, dated price and allowance; it does not authorize a repeat. The runner refuses proposal identities
already dispatched in retained A2 journals before accessing credentials. A separately reviewed repeat needs a new
proposal identity, supplied during generation with `--proposal-id <new-id>`. Creating that identity does not approve
spending.

Only after a new exact manifest receives approval, run the same script with
`--live --manifest /tmp/jev-calibration.json --output /tmp/jev-calibration-capture`. It requires a new absolute output
directory, isolates `FORGE_HOME`, disables retries and stops at the first failure or model/accounting drift. Its
`capture.json` journal is authoritative; `predictions.json` uses evaluator schema 2. The journal binds source bytes and
revision, dirty checkout status and retains sanitized bodies, original response sizes/status and elapsed client-call
time, including local journal I/O. Unknown cost remains unknown. The replay check covers retained A2 journals;
unretained, deleted or concurrent runs are outside that local guard. It is not an authorization system. There is no
resume or held-out mode; a continuation needs a new request scope.

Real native actions are a separate local-only acquisition under the
[feasibility study plan](../../../docs/board/doing/jev_rule_pack/evidence/feasibility-study-plan.md). Its approval does
not authorize sending them to a provider or adding them to Git. The inventory script implements only metadata selection
and source-path admission, with no native-content reads:

```bash
uv run python scripts/experiments/jev/rule-pack-inventory.py --metadata
uv run python scripts/experiments/jev/rule-pack-inventory.py --inspect-sources /private/tmp/jev-a2-feasibility-<id>
```

Run it only within an approved acquisition scope. The first command creates a private directory; the second consumes
that retained metadata selection. Neither command searches for replacements. The
[checkpoint](../../../docs/board/doing/jev_rule_pack/evidence/feasibility-progress.md) records the first run's
missing-source shortfall; no action extractor was needed or implemented.

The [bounded continuation](../../../docs/board/doing/jev_rule_pack/evidence/feasibility-continuation-2026-10-19.md) uses
a separate metadata-only mode:

```bash
uv run python scripts/experiments/jev/rule-pack-inventory.py --availability-first
```

It checks confirmed paths within one fixed 24-candidate recency cohort before allocating up to three available sources
per runtime. It writes a new private selection ledger and aggregate summary, without reading native content or searching
for replacements. The recorded action window is prospective; path existence does not verify native identity, completion
or action admission. The original modes retain their original selection behavior.

For a separately authorized content scope, audit only that frozen selection:

```bash
uv run python scripts/experiments/jev/rule-pack-source-audit.py \
  --audit /private/tmp/jev-a2-availability-<id>/availability-private.json
```

This Claude-only schema audit rechecks active state and source identities, bounds JSONL reads, and emits controlled
metadata counters. It retains private source receipts without message text or tool arguments. It does not verify turn
completion, extract actions or dispatch requests. Existing audit outputs refuse a repeat before any source read. The
continuation records the completed study's shortfall and recommendation to stop the current A2 implementation path.

## A1 transport probes

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
[the A1 card](../../../docs/board/done/jev_client_probes/evidence/README.md). Ordinary tests inject `httpx` transports
and never call Jev; no fixture transport ships in `src/forge`.
