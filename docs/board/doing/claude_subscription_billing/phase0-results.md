# T0 Phase 0 results: does `claude -p` ride Max headlessly?

**Status: TEMPLATE (awaiting an operator run).** Fill the verdicts below from a real run on a machine with a
pre-authenticated Claude Max/Pro session and **no resolvable `ANTHROPIC_API_KEY`**. Harness:
`scripts/experiments/claude-subscription/` (see its `README.md`). Paste only **sanitized** evidence (`./sanitize.sh`
must pass first) -- metadata only, never a key/token/transcript.

## Run context (fill in)

- Date / operator:
- Claude Code version (`claude --version`):
- OS:
- Keyless proof (stage 00 `[KEYLESS-OK]`; `key_source` should be `none`):
- `auth_ignore_env`:
- OAuth token env var present (`CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN`)? (distinguishes "rode the keychain
  Max session" from "rode a token env var" for a0):
- Model used (`CLAUDE_SUB_PROBE_MODEL` or `<claude-default>`):

## Findings

| Signal                      | Verdict                                                 | Evidence (sanitized)                 |
| --------------------------- | ------------------------------------------------------- | ------------------------------------ |
| (a0) non-TTY OAuth feasible | `[OAUTH-NONTTY-OK \| -FAILED \| -INCONCLUSIVE]`         | rc, subtype, `auth_marker_seen`      |
| (a) keyless turn completes  | yes / no                                                | rc=0, `has_result`, `is_error=false` |
| (b) billing signal          | `[COST-PRESENT \| -ABSENT]`                             | `cost_value`, `usage` in/out tokens  |
| (b) composite shape         | `[SHAPE-SUBSCRIPTION-LIKELY \| -PER-TOKEN-OR-ESTIMATE]` | from the 10-turn verdict             |
| (c) detection signal        | `[SIGNAL-STABLE-PREFLIGHT \| -RUNTIME-ONLY \| -NONE]`   | chosen candidate + why others fail   |
| (d) quota draw              | `[QUOTA-OBSERVED \| -UNOBSERVED]`                       | quota fields seen (expect none)      |

## Decision gate outcome (pick one; record in the epic)

- [ ] **Full kill (architectural)** -- (a0) `[OAUTH-NONTTY-FAILED]`: the subscription lane is impossible headlessly.
  Close the `claude-max`-as-subscription question in the epic. **Stop.**
- [ ] **Phase-1 no-go (brittle signal)** -- (a)/(b) positive but (c) = `RUNTIME-ONLY`/`NONE` below the bar: do **not**
  emit a guessed `subscription_*`. Record the finding (optionally as future runtime-only work). **Stop.**
- [ ] **Per-token (labeling, not kill)** -- keyless auth succeeds but (b) `[COST-PRESENT]`: keep `api`/`unknown`; note
  the path's non-billing value (fidelity / decorrelation) separately. **Stop the billing work.**
- [ ] **Proceed** -- (a0)/(a)/(b) positive **and** (c) `[SIGNAL-STABLE-PREFLIGHT]`: go to Phase 1; record the
  `billing_mode` (b) implies -- `subscription_quota` vs `subscription_headless_credit` (**card Q3**):

## Notes for Q1-Q3 (carry back to the card)

- **Q1 (detection-signal risk):** is the chosen (c) signal stable enough to gate a durable `billing_mode` label?
- **Q2 (Phase-2 scope):** if proceeding, does `BillingPosture` need `subscription_headless_credit` before the
  `claude-max` source can carry it?
- **Q3 (which `billing_mode`):** does the cost shape lean `subscription_quota` or `subscription_headless_credit`?
