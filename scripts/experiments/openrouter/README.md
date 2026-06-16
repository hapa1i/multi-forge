# OpenRouter provider-trace probe harness (Phase 0, evaluation only)

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

Promote the sanitized findings into `docs/board/doing/openrouter_observability/phase0-results.md` (metadata-only) and
tick the Phase 0 boxes in that card's `checklist.md`. Raw captures stay in the cache, never committed.
