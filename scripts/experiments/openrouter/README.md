# OpenRouter probe harness

## Codex Responses

Stages 50–80 exercise the sessionless Codex Responses route. Select each stage by name or number. Stage 50 uses a
private loopback server, a dummy provider token and disposable Codex homes. Supply a JSON object mapping each pinned
version (`0.141.0`, `0.149.1`, `0.161.0`, `0.170.0`) to its retained native executable's absolute path. Keep the
complete distribution next to each executable. Point `OPENROUTER_CAPTURE_DIR` at a fresh private directory.

```bash
export OPENROUTER_RESPONSES_BINARIES=/path/to/binaries.json
export OPENROUTER_CAPTURE_DIR=/path/to/private/capture-round
./reproduce.sh 50-responses-loopback
./sanitize.sh
```

The matrix records a local tool read, a follow-up turn, compaction, and client rendering and retries for seven error
controls across five refusal classes. Keep raw transcripts, native IDs and executable paths private. After the scan,
`python3 helpers/export_matrix.py "$OPENROUTER_CAPTURE_DIR/sanitized/50-loopback"` writes the per-request CSV to
standard output. [Recorded results](../../../docs/board/doing/codex_openrouter_responses/probe-results.md)

The final acceptance runner launches both native TUIs through a saved Forge proxy with a verified $0.50 reject cap. It
reserves requests before forwarding and relays SSE incrementally. Supply an unused receipt path. The selftest uses
loopback, synthetic credentials and a scratch workspace.

```bash
uv run --locked python scripts/experiments/openrouter/helpers/forge_acceptance.py --selftest \
  --manifest docs/board/doing/codex_openrouter_responses/paid-acceptance-manifest.json \
  --binary /path/to/pinned/codex --output /path/to/new-receipt.json
```

After separate operator approval, replace `--selftest` with `--approved-sha256 <full-approved-digest>` and supply the
dedicated key via `OPENROUTER_PROBE_API_KEY`. The live ledger permits one run per digest.
[Acceptance limits and optional key creation](../../../docs/board/doing/codex_openrouter_responses/paid-acceptance-manifest.json)

Stages 60 (ZDR), 70 (cost and identity) and 80 (Codex and HTTP replay) spend OpenRouter credit. They require a reviewed
manifest and a dedicated, credit-limited probe key. Supply the manifest path in `OPENROUTER_RESPONSES_MANIFEST` and the
**approved digest** in `OPENROUTER_RESPONSES_APPROVED_SHA256`. Supply the key through `OPENROUTER_PROBE_API_KEY`. For
native Codex probes, supply the retained binary path through `OPENROUTER_RESPONSES_CODEX`. Each stage consumes its
manifest's attempt budget and deadline, with a persistent receipt under
`~/.cache/forge-openrouter-probe/response-approvals/<manifest-sha256>/`. The key must have a non-resetting USD limit
within the approval and count BYOK charges. Local controls can be checked with
`python3 helpers/paid_probe.py selftest --selftest-codex /path/to/pinned/codex`. Pass
`--selftest-manifest /path/to/paid-probe-manifest.json` to include all pinned replay fixtures. This exercises the bridge
and scratch edit against a canned upstream. Keep the card's `evidence/` directory beside its manifests when moving or
copying the card. The runner resolves historical fixture paths there and replays the bytes verified during preflight.
[Original Qwen replay manifest](../../../docs/board/doing/codex_openrouter_responses/paid-probe-manifest-qwen.json)

The
[account ZDR manifest](../../../docs/board/doing/codex_openrouter_responses/paid-probe-manifest-qwen-account-zdr.json)
covers only stage 60. After approval, select `./reproduce.sh 60-responses-zdr`. The harness verifies the recorded Qwen
baseline locally, checks the key and current ZDR catalog, and sends both live requests with `provider.zdr=true`. A pass
requires a ZDR-specific Qwen refusal and completed text from Astra under the account policy. The independent effect of
the request flag remains unverified.

The [Astra continuation](../../../docs/board/doing/codex_openrouter_responses/paid-probe-manifest-astra-positive.json)
accepts the exact Qwen refusal the maintainer reviewed. The harness verifies both historical Qwen receipts, reads the
key and catalog, and sends one Astra request. To reproduce that sequence locally, pass the continuation file to
`--selftest-manifest`.
[Live result](../../../docs/board/doing/codex_openrouter_responses/evidence/paid-1ee865aa/zdr.json)

The
[stages 70 and 80 manifest](../../../docs/board/doing/codex_openrouter_responses/paid-probe-manifest-cost-codex.json)
pins the passing stage 60 receipt. Rehearse it with `selftest --selftest-manifest <manifest> --selftest-codex <binary>`.
After approval, run `./reproduce.sh 70-responses-cost` followed by `./reproduce.sh 80-responses-codex` with the same
dedicated key. The ledger enforces stage order, the shared deadline and the attempt limits.

The [stage 80-only manifest](../../../docs/board/doing/codex_openrouter_responses/paid-probe-manifest-codex-only.json)
reuses the stage 70 metadata decision and pins the prior credit refusal. Pass it to the same loopback command to run
only the native and HTTP replay probes. After approval, select `./reproduce.sh 80-responses-codex`. The standalone stage
checks the dedicated key's credit once before forwarding the first native request.

Run the original account ZDR manifest on loopback from the repository root.

```bash
python3 scripts/experiments/openrouter/helpers/paid_probe.py selftest \
  --selftest-manifest docs/board/doing/codex_openrouter_responses/paid-probe-manifest-qwen-account-zdr.json
```

For a failed request, inspect `requests[].error` in the stage receipt. The diagnostic projects OpenRouter's
`error.metadata.ineligibility_reasons` into `ineligibility_reasons`, retaining recognized routing codes, valid endpoint
counts and the public privacy settings URL when present. `ineligibility_reasons_omitted` counts entries withheld by the
sanitizer. The separate `routing_reasons` field contains recognized policy lines from the message. Stage 60 also records
the diagnostic on the failed control, for example `baseline.error`. The diagnostic includes the sanitized message and
available error code, provider name, upstream error fields and request ID. For an unreadable error body, use the
recorded byte count and SHA-256 to identify it. The original three-stage manifests use a paired test for independent
request-level enforcement. That test requires a completed unrestricted baseline before the same model and reasoning
setting can demonstrate a refusal with the flag set.

## Provider trace (Chat Completions)

**Question:** which OpenRouter externals does the `openrouter_observability` card rest on, and are they true? Phase 0
pins them with reproducible, operator-gated probes **before** any later phase populates a provider-id field.

Research pin: OpenRouter HTTP API as reached by Forge's direct `OpenRouterClient` (a thin `openai` SDK wrapper) and,
optionally, a LiteLLM gateway. These probes hit OpenRouter **directly** (the simplest channel); they reuse Forge
credential resolution read-only and never start a proxy.

> Operator-gated: needs a live `OPENROUTER_API_KEY` resolvable by Forge (env or `~/.forge/credentials.yaml`). Stage 00
> fails loudly otherwise. Probe 2's `/activity` arm additionally needs a management/provisioning key
> (`OPENROUTER_PROVISIONING_KEY`). Probe 4 is cost-heavy and explicit-only.

## Facts under test

| #   | Fact the card assumes                                                                                  | Stage                  | Gating                          |
| --- | ------------------------------------------------------------------------------------------------------ | ---------------------- | ------------------------------- |
| 1   | A `gen-…` id is exposed (body.id / stream chunk.id / header / lookup); Forge's canonical types drop it | `10-genid`             | headless                        |
| 2   | A stream cancelled before final usage is (likely) absent from OpenRouter remotely                      | `20-cancel`            | operator (mgmt key + dashboard) |
| 3   | `session_id` / `user` reach OpenRouter via `extra_body`; recognition is the open question              | `30-session-transport` | headless (gateway arm opt-in)   |
| 4   | A sticky `session_id` may improve cache/affinity (or pin to a worse provider)                          | `40-session-routing`   | explicit-only, cost-heavy       |

## Verdict vocabulary (one bracketed line in `results/verdict.txt`)

- **00-preflight:** `[PREFLIGHT-OK]` · `[PREFLIGHT-NO-KEY]`
- **10-genid:** `[GENID-IN-STREAM-CHUNK]` · `[GENID-IN-BODY]` · `[GENID-HEADER-ONLY]` · `[GENID-LOOKUP-ONLY]` ·
  `[GENID-ABSENT]` · `[GENID-INCONCLUSIVE]`
- **20-cancel:** `[REMOTE-ABSENT]` (**expected, a PASS**) · `[REMOTE-PRESENT-GENERATION]` · `[REMOTE-PRESENT-ACTIVITY]`
  · `[REMOTE-INCONCLUSIVE]`. `/generation` is eventually-consistent (an immediate lookup 404s even for a *completed*
  call), so the probe polls with backoff and makes a **completed-call baseline** as the absence control: it only asserts
  `[REMOTE-ABSENT]` once the baseline indexed (HTTP 200) while the aborted id did not. If even the baseline never
  indexes in-window the verdict is `[REMOTE-INCONCLUSIVE]` (poll too short), never a premature `[REMOTE-ABSENT]`.
  Presence requires HTTP **200** with a non-error body — a 404 error envelope is **not** "present".
- **30-session-transport:** `[CHANNEL-SESSION_ID-RECOGNIZED]` · `[CHANNEL-USER-RECOGNIZED]` (→ Phase 5 channel
  correction) · `[CHANNEL-UNVERIFIABLE]` · `[CHANNEL-TRANSPORT-FAILED]`. Per cell (in the record / oracle):
  `[TRANSPORTED+RECOGNIZED]` · `[TRANSPORTED+UNVERIFIABLE]` · `[TRANSPORT-FAILED]`.
- **40-session-routing:** `[STICKY-IMPROVES]` · `[STICKY-NEUTRAL]` · `[STICKY-DEGRADES]` · `[ROUTING-INCONCLUSIVE]`.

**Transport ≠ recognition (probe 3).** `TRANSPORTED` = the field demonstrably left in the outgoing body (code-confirmed
possible: `extra_body` forwards verbatim). `RECOGNIZED` = OpenRouter demonstrably did something with it (echo / grouping
/ behavior delta). `UNVERIFIABLE` = transported, but no observable surface confirms recognition — a real finding (the
likely `session_id` outcome), never reported as `RECOGNIZED`. Recognition is checked against the **polled**
`/generation` record (eventual-consistency, like probes 1-2 -- an immediate lookup would misread a stored field as
absent). The headless run tests the **direct** OpenRouter path only; the gateway/LiteLLM arm is opt-in, and recognition
is an OpenRouter-side property expected to be path-independent (LiteLLM forwards `extra_body` verbatim).

**Inconclusive ≠ absent.** A verdict from a turn that failed is `[…-INCONCLUSIVE]` (exit ≠ 0). A successful query that
returns nothing — probe 2's expected `[REMOTE-ABSENT]` — is a PASS.

## Running

```bash
./reproduce.sh                      # headless: 00-preflight + 10-genid + 30-session-transport
./reproduce.sh all                  # + 20-cancel (operator: management key + dashboard)
./reproduce.sh 40-session-routing   # explicit-only, cost-heavy
./sanitize.sh                       # ALWAYS last: scan-and-fail secret scrub
```

Knobs (all optional env vars):

- `OPENROUTER_PROBE_MODEL` — model id (default `openai/gpt-4o-mini`; pick any valid OpenRouter id).
- `OPENROUTER_PROVISIONING_KEY` — management key for probe 2's `/activity` arm.
- `OPENROUTER_PROBE_GATEWAY_BASE_URL` (+ optional `OPENROUTER_PROBE_GATEWAY_KEY`) — enables probe 3's gateway arm.
- `OPENROUTER_PROBE_REPEATS` — probe 4 repeats per arm (default 5).
- `OPENROUTER_CAPTURE_DIR` — capture root (default `~/.cache/forge-openrouter-probe`).

## Privacy

- **No API key is ever printed or persisted.** The key flows only through the in-process SDK/httpx call. `creds` emits
  only `base_url` + provenance (`env` / `credentials.yaml` / `management key unavailable`). `meta/run.json` records env
  var **names** present, never values.
- **No raw bodies by default.** `or_probe.py` emits deliberately shaped records. A raw dump is opt-in behind
  `--debug-raw`, written to the cache only (scrubbed by `sanitize.sh`), never committed.
- **`sanitize.sh` is scan-and-fail.** It redacts host paths/usernames and **fails loudly** on any residual secret
  (including OpenRouter `sk-or-v1-…`). Run it before promoting any excerpt into the committed results doc.

## Captures

```
${OPENROUTER_CAPTURE_DIR:-~/.cache/forge-openrouter-probe}/<stage>/
├── results/   # verdict.txt, <label>.record.json, <label>.oracle.txt, <label>.exit
├── meta/      # run.json, base-url.txt, key-provenance.txt
└── streams/   # raw payloads -- ONLY when --debug-raw (uncommitted)
```

The [provider-trace results](../../../docs/board/done/openrouter_observability/phase0-results.md) record the completed
Chat Completions investigation. Raw captures stay in the private cache.
