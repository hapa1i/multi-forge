# Claude-subscription billing probe harness (consumer_lanes T0, Phase 0, evaluation only)

**Question:** does a *keyless* `claude -p` ride a Claude Max/Pro subscription headlessly, and is the auth mode
detectable from a **stable** signal? T0's card claims `claude-max` could be a subscription lane; this harness pins that
**before** Phase 1 labels any run `subscription_*`. It is the gate for everything below it in
`docs/board/doing/claude_subscription_billing/checklist.md`.

Research pin: the *direct, keyless* `claude -p` path as Forge's runner would take it when no key resolves
(`session_runner.py:183` -> `can_use_bare` False -> `--bare` omitted -> OAuth/keychain). These probes reuse Forge
credential resolution **read-only** to PROVE keyless-ness; they never start a proxy and never write `~/.forge`.

> **Operator-gated, and inverted vs the `openrouter/` harness.** This needs **no resolvable `ANTHROPIC_API_KEY`** (shell
> env AND `~/.forge/credentials.yaml`; `auth_ignore_env` changes which sources count) plus a pre-authenticated Max/Pro
> session (run `claude` once interactively to log in). Stage 00 proves keyless-ness with the runner's own predicate and
> **aborts** if a key is resolvable -- otherwise the probe silently measures the *key* path and falsely concludes "no
> subscription."

## Relationship to `headless-cost-report/`

The sibling `scripts/experiments/headless-cost-report/` harness already proved the **envelope shape**
(`--output-format json` -> `[system, assistant, result]`; cost/usage in the last `result`) and the **direct-API-key**
cost row at CC 2.1.165. This harness reuses that exact parsing and fills the row that one left open -- the
**OAuth/subscription** column it marked *"run under OAuth to fill"* -- but adds the two things that harness does not do:
it **asserts keyless-ness** (never just detects the mode) and it tests **(a0) non-TTY OAuth feasibility** and **(c)
auth-mode detectability**, which are T0-specific. `headless-cost-report`'s `[COST-REPORTED]`/`[COST-ABSENT]` is this
harness's `[COST-PRESENT]`/`[COST-ABSENT]`.

## Facts under test

| #    | Fact T0 needs                                                                  | Stage             | Gating               |
| ---- | ------------------------------------------------------------------------------ | ----------------- | -------------------- |
| gate | No key is resolvable (else the probe measures the key path)                    | `00-precondition` | operator (keyless)   |
| a0   | A pre-authenticated Max/Pro session authenticates a `claude -p` in **non-TTY** | `10-turn`         | headless             |
| a    | Given (a0), a keyless `claude -p` completes a real turn                        | `10-turn`         | headless             |
| b    | The JSON envelope reports a dollar cost (API-equiv) vs usage-but-no-cost (sub) | `10-turn`         | headless             |
| c    | The auth mode is detectable from a **stable preflight** signal                 | `20-detection`    | headless (read-only) |
| d    | The run draws Max quota / surfaces rate-limit headroom (informs T5/T7)         | `30-quota`        | optional             |

## Verdict vocabulary (one bracketed line in `<stage>/results/verdict.txt`)

- **00-precondition:** `[KEYLESS-OK]` (proceed) · `[KEY-RESOLVABLE]` (**abort** -- unset the key) ·
  `[PRECONDITION-ERROR]` (forge import failed -- fails **closed**, never assumed keyless).
- **10-turn** (verdict.txt carries the decision-relevant token; the per-signal tags are in the record/oracle):
  - `[OAUTH-NONTTY-FAILED]` -- keyless auth needs a TTY/login (**kill #1, architectural**).
  - `[TURN-INCONCLUSIVE]` -- turn failed for a non-auth reason (timeout / model error); rerun.
  - `[SHAPE-SUBSCRIPTION-LIKELY]` -- completed keyless **and** cost-absent + usage-present (the expected subscription
    signature).
  - `[SHAPE-PER-TOKEN-OR-ESTIMATE]` -- completed keyless but a dollar `total_cost_usd` is present. Ambiguous: a real
    per-token charge **or** Claude Code's informational estimate (**card Q3** -- which `billing_mode`).
  - Per-signal tags in the record: `a0_oauth_nontty` ∈ {`[OAUTH-NONTTY-OK]`,`-FAILED`,`-INCONCLUSIVE`}; `b_cost_signal`
    ∈ {`[COST-PRESENT]`,`[COST-ABSENT]`,`[COST-INCONCLUSIVE]`}.
- **20-detection:** `[SIGNAL-STABLE-PREFLIGHT]` (a named, Forge-ownable, preflight signal exists) ·
  `[SIGNAL-RUNTIME-ONLY]` (the only discriminator is the post-turn cost-null -- not classifiable at preflight) ·
  `[SIGNAL-NONE]` (no candidate qualifies). The honest expected outcome given there is **no `codex doctor`-equivalent**
  for Claude is `RUNTIME-ONLY` or `NONE` -- that is **card Q1**, the real soft spot.
- **30-quota:** `[QUOTA-OBSERVED]` · `[QUOTA-UNOBSERVED]` (the expected default -- `claude -p` does not surface
  `anthropic-ratelimit-*` headers).

**Keyless ≠ optional.** A `[KEY-RESOLVABLE]` gate is not a soft warning: the run aborts. Measuring the key path and
reporting "subscription" is the single failure mode T0 is built to avoid.

## How the verdicts map to the decision gate

The checklist's three-way decision gate reads directly off stage 10 + stage 20:

| Outcome                       | Reading                                                             | Action                                                         |
| ----------------------------- | ------------------------------------------------------------------- | -------------------------------------------------------------- |
| **Full kill (architectural)** | `[OAUTH-NONTTY-FAILED]`                                             | subscription lane impossible; close the `claude-max` question  |
| **Phase-1 no-go (brittle)**   | `SHAPE-SUBSCRIPTION-LIKELY` **but** detection `RUNTIME-ONLY`/`NONE` | do **not** emit a guessed `subscription_*`; record the finding |
| **Per-token (labeling)**      | `[SHAPE-PER-TOKEN-OR-ESTIMATE]`                                     | keep `api`/`unknown`; note the non-billing value separately    |
| **Proceed**                   | `SHAPE-SUBSCRIPTION-LIKELY` **and** detection `STABLE-PREFLIGHT`    | Phase 1; record which `billing_mode` (b) implies (card Q3)     |

## Running

```bash
./reproduce.sh                 # 00-precondition (gate) + 10-turn + 20-detection
./reproduce.sh all             # + 30-quota (optional; draws extra quota)
./reproduce.sh 10-turn         # one stage (turn self-guards keyless on its own)
./sanitize.sh                  # ALWAYS last: scan-and-fail secret scrub
```

Knobs (all optional env vars):

- `CLAUDE_SUB_PROBE_MODEL` -- `--model` for the turn (default: Claude Code's default). Pick a cheap tier to limit quota.
- `CLAUDE_SUB_PROBE_PROMPT` -- the turn prompt (default `Reply with exactly: ok`; keep it tiny).
- `CLAUDE_SUB_TURN_TIMEOUT` -- inner per-call timeout in seconds (default 150).
- `PROBE_TURN_TIMEOUT` -- outer wall-clock guard around `uv run` (default 180).
- `CLAUDE_SUB_CAPTURE_DIR` -- capture root (default `~/.cache/forge-claude-sub-probe`).

## Privacy

- **No API key or OAuth token is ever printed or persisted.** The precondition resolves the key only to test its
  *presence* (a boolean + a `source` label); the value is discarded. Records are metadata-only: dollar cost numbers,
  token **counts**, booleans, subtype, and an id **prefix**.
- **Token stores are never read.** `20-detection` checks `~/.claude/.credentials.json` for existence/mode only and does
  **not** query the OS keychain (a read would surface the token). `claude config get` is captured for key **names**
  only.
- **No raw output by default.** For raw stdout/stderr, run a stage directly so it forwards the flag
  (`bash stages/10-turn.sh --debug-raw`); `reproduce.sh` does not pass args through to stages. Raw payloads land in the
  cache only, scrubbed by `sanitize.sh`, never committed.
- **`sanitize.sh` is scan-and-fail.** It redacts host paths/usernames and **fails loudly** on any residual secret
  (`sk-ant-…`, JWT/OAuth tokens, `Bearer …`, `*_TOKEN=` assignments). Run it before promoting any excerpt.

## Captures

```
${CLAUDE_SUB_CAPTURE_DIR:-~/.cache/forge-claude-sub-probe}/<stage>/
├── results/   # verdict.txt, <label>.record.json, <label>.oracle.txt, <label>.exit
├── meta/      # run.json (env var NAMES only, never values)
└── streams/   # raw stdout/stderr -- ONLY when --debug-raw (uncommitted)
```

Promote the sanitized findings into `docs/board/doing/claude_subscription_billing/phase0-results.md` (metadata-only) and
tick the Phase 0 boxes in that card's `checklist.md`. Raw captures stay in the cache, never committed.
