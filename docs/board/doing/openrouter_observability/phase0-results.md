# Phase 0 probe results -- OpenRouter externals

Metadata-only, promoted from the sanitized captures at `~/.cache/forge-openrouter-probe/` (raw captures **not
committed**). Probes ran against a live `OPENROUTER_API_KEY` on 2026-06-15; probes 1-3 were re-run the same day after
harness fixes.

> **All four probes settled.** Two findings flipped on re-run after harness fixes: probe 2's false
> `[REMOTE-PRESENT-GENERATION]` became `[REMOTE-ABSENT]` (a 404 error body had been counted as "present"); probe 3's
> `[CHANNEL-UNVERIFIABLE]` became **`[CHANNEL-USER-RECOGNIZED]`** once recognition polled the eventually-consistent
> `/generation` record. **Channel correction: OpenRouter records the OpenAI-standard `user` field but ignores a custom
> `session_id`** -- see [Probe 3: the channel correction](#probe-3-the-channel-correction).

| Run metadata                     | Value                                                                    |
| -------------------------------- | ------------------------------------------------------------------------ |
| Date run                         | 2026-06-15 (probes 1-3 re-run same day after the fixes)                  |
| OpenRouter model probed          | `openai/gpt-4o-mini`                                                     |
| Inference key provenance         | `env`                                                                    |
| Management key present (probe 2) | `env` (`OPENROUTER_MANAGEMENT_KEY`)                                      |
| Gateway arm tested (probe 3)     | **no** (`OPENROUTER_PROBE_GATEWAY_BASE_URL` unset -> direct path only)   |
| Harness commit                   | `2b7f0ab` (harness incl. the post-run fixes was uncommitted at run time) |

## Verdicts

| Probe       | Stage                  | Verdict                     | One-line observed surface                                                                                        |
| ----------- | ---------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 1 gen-id    | `10-genid`             | `[GENID-IN-STREAM-CHUNK]`   | `gen-` id in `body.id`, `x-generation-id` header, and every stream `chunk.id`                                    |
| 2 cancel    | `20-cancel`            | `[REMOTE-ABSENT]`           | aborted id not retrievable (`/generation` 404 after ~23s; `/activity` 200, absent); completed baseline DID index |
| 3 transport | `30-session-transport` | `[CHANNEL-USER-RECOGNIZED]` | direct: `user` recognized (in polled `/generation`), `session_id` unverifiable; **direct path only**             |
| 4 routing   | `40-session-routing`   | `[STICKY-NEUTRAL]`          | sticky vs baseline within noise; no cache hits; all routed to one provider                                       |

## Observed surfaces

- **Probe 1 (`10-genid`).** Non-streaming `body.id` present, prefix `gen-`; response-header carrier `x-generation-id`.
  Streaming `chunk.id` present and **stable across all 12 chunks**. `forge_canonical_type_preserved_provider_id = false`
  (Forge's canonical types drop the provider id, as the card predicts). Polled `/generation?id=` reached **HTTP 200
  after 3 attempts** (~3s) -- the gen-id **is** retrievable once OpenRouter indexes it.
- **Probe 2 (`20-cancel`).** `stream_started=true`, `first_chunk_seen=true`, `final_usage_seen=false`,
  `client_disconnected=true`, `stop_reason="deliberate client close after first chunk"`. A `gen-` id was captured from
  the first chunk **before** the close. Aborted-id `/generation`: **404 after all 6 attempts** (~23s) -- never indexed.
  Completed-call **baseline** `/generation`: **HTTP 200** (the control indexed, so the window was long enough).
  `/activity`: **200**, aborted id **absent**. `local_usage_status = unavailable`.
- **Probe 3 (`30-session-transport`).** `direct/session_id`: `[TRANSPORTED+UNVERIFIABLE]` (HTTP 200; not found in the
  polled `/generation` record). `direct/user`: `[TRANSPORTED+RECOGNIZED]` (HTTP 200; the sent value **appeared in the
  polled `/generation` record**). Recognition was decided against the *indexed* record, not an immediate 404. Gateway
  arm `[GATEWAY-SKIPPED]` (not run).
- **Probe 4 (`40-session-routing`).** `n=5` per arm, `failure_rate=0.0`, no cached tokens, single provider (`Azure`)
  across all arms. first-token / total ms means: baseline `905 / 968`, sticky_session_id `883 / 1027`, sticky_user
  `841 / 897`. Deltas are within run-to-run noise at `n=5` -> neutral (verdict spans **both** sticky arms).

## Probe 2: the headline finding

**Result: `[REMOTE-ABSENT]` -- a stream cancelled after the first chunk leaves no remotely-retrievable record.** The
completed-call baseline indexed to HTTP 200 within the poll window while the aborted id stayed 404 across all 6
attempts, and `/activity` (200) did not contain it. Because the control proved the window was long enough, the absence
is real, not "we didn't wait long enough."

**Why the first run was wrong (kept for memory).** It reported `[REMOTE-PRESENT-GENERATION]` from a record that
contradicted itself (`generation_lookup_status=404` **with** `generation_lookup_present=true`). `_http_get` returned the
body regardless of status, and the verdict used `bool(gdata)` -- but OpenRouter returns a truthy JSON **error envelope**
on a 404, so the error body was counted as "present." Probe 1 was the cross-check: a fully **completed** call's gen-id
404s on an *immediate* lookup too, so the 404 is OpenRouter **indexing latency**, not record absence.

**Harness fix (shipped in `helpers/or_probe.py`).** Presence requires **HTTP 200 + a non-error body**
(`_generation_present`); `/generation` is **polled** (`GENERATION_POLL_DELAYS`, ~23s); the cancel probe adds a
**completed-call baseline** control and only asserts `[REMOTE-ABSENT]` once the baseline indexes while the aborted id
does not (else `[REMOTE-INCONCLUSIVE]`).

## Probe 3: the channel correction

**Result: OpenRouter records the OpenAI-standard `user` field but ignores a custom `session_id`.** On the direct path
both fields transport (HTTP 200), but only `user` reappears in the polled `/generation` record (`recognized=true`);
`session_id` does not (`recognized=false`). The first run reported both `UNVERIFIABLE` because recognition fell back to
a **single immediate** `/generation` lookup, which 404s on indexing lag (probes 1-2) -- so a recorded field was misread
as absent. The helper now **polls** the indexed record (`_poll_generation_body`); that flipped the verdict to
`[CHANNEL-USER-RECOGNIZED]`. The recognition test searches the indexed body for the *exact sent value*, so a positive is
sound (not the `bool(body)` artifact that bit probe 2). Scope: **direct OpenRouter path only**; the gateway/LiteLLM arm
was not run, but recognition is an OpenRouter-side property expected to be path-independent (LiteLLM forwards
`extra_body` verbatim).

## Implications for later phases

- **Phase 2 / 3 (provider metadata + trace plane).** Lift the gen-id from the streaming **`chunk.id`** (stable across
  chunks) and the non-streaming **`body.id`**; `x-generation-id` is the header carrier. Streaming
  `provider_generation_id` is **not** structurally `None` (this **corrects** the checklist hedge at line 43 / the Phase
  2 streaming task). `forge_canonical_type_preserved_provider_id=false` confirms the drop Phase 2/3 must close.
- **Phase 4 (read surface).** **Settled:** a cancelled stream is not retrievable remotely, so a local-only trace is the
  only source of truth at disconnect -- `local_usage_status="unavailable"` (distinct from a billed `0`) is justified by
  `final_usage_seen=false`. Nuance for the `explain` copy: a **completed** generation *does* become retrievable after a
  ~3s indexing delay, so phrase it as **"no remote record was retrievable for the cancelled request"** / "no remote
  lookup was performed," not "OpenRouter keeps no record" -- a later reconciliation card may poll `/generation` for
  completed requests.
- **Phase 5 (`session_id` injection) -- channel correction applies.** Inject the Forge session id under the **`user`**
  field, not a custom `session_id`: OpenRouter **records `user`** (so a supervised fork becomes findable/groupable in
  OpenRouter's own dashboard -- directly addressing the incident) but **ignores `session_id`** (Forge-local correlation
  only, invisible upstream). Caveats: (a) recognition is **not** routing impact -- probe 4 `[STICKY-NEUTRAL]` shows no
  latency/cache benefit, so the flag still **defaults OFF** and is opt-in for *observability*, not performance; (b) a
  recognized `user` value is **retained by OpenRouter**, which reinforces the card's "hash the human name, never send it
  raw" decision (`forge_sess_<hash>` / `forge_run_<hash>`); (c) the adverse "pin to a worse provider" case did not
  appear (single provider, 0% failure) but `n=5` is too small to rule it out.

## Notes / anomalies

- **Indexing latency is real and asymmetric.** A completed call's gen-id indexed in ~3s (3 poll attempts); the
  cancelled-after-first-chunk call never indexed within ~23s and was absent from `/activity`. Any future "look it up
  after the fact" feature must poll, and must not expect a cancelled request to appear at all.
- **Recognition was masked by indexing.** Probe 3's `user` recognition only surfaced once the lookup polled -- the same
  eventual-consistency that bit probe 2. The lesson generalized to every `/generation` consumer in the harness.
- Single upstream provider (`Azure`) was selected for every `gpt-4o-mini` call, so probe 4 could not observe
  provider-affinity effects; a model with several upstreams would exercise stickiness harder.
- No cached-token usage was reported on any arm, so the prompt-cache hypothesis behind sticky routing is untested here.
- Whether OpenRouter *bills* a stream aborted after one chunk is a separate question (cost was not captured;
  `local_usage_status=unavailable`).
