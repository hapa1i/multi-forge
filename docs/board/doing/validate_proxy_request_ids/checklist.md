# Validate proxy request IDs checklist

Current focus: implementation and verification complete; awaiting independent review and merge.

## Activation and reproduction

- [x] Start `fix/validate-proxy-request-ids` from merged PR #158 at `ce7eb1ec`.
- [x] Close D035, move D036 from `todo/` to `doing/`, and advance the child-epic cursor.
- [x] Add a marked D036 regression for whitespace, controls, non-token bytes, path syntax, and overlong IDs.
- [x] Confirm five retained assertions fail on `ce7eb1ec` because the raw header reaches state, diagnostics, and the
  Forge-owned response header; four valid-ID controls pass.

## Ingress contract

- [x] Define one dependency-light validator with an explicit `[A-Za-z0-9._-]{1,128}` contract.
- [x] Preserve accepted client IDs byte-for-byte and mint endpoint-specific IDs for absent or invalid values.
- [x] Apply validation once before request state, downstream event IDs, logs, telemetry, and response paths diverge.
- [x] Replace supplied or duplicate raw headers with the resolved safe value before downstream audit/header consumers
  can copy them.
- [x] Materialize the ASGI header iterable before any cached header view and exercise a fresh downstream `Request` in
  the regression.
- [x] Pin `mint_request_id()` to the ingress validator so exact direct-path cost joins cannot silently drift.
- [x] Keep translated and Anthropic-passthrough routing, upstream-header filtering, and the four `X-Forge-*` validators
  unchanged.

## Acceptance tests

| Test                   | Fixture                                            | Assertion                                                                  |
| ---------------------- | -------------------------------------------------- | -------------------------------------------------------------------------- |
| Valid compatibility    | UUID, hex, `req_`, hyphen, and dot token IDs       | exact value reaches state, response, and one diagnostic/telemetry record   |
| Invalid fallback       | whitespace, controls, non-token bytes, overlong ID | generated prefix is used everywhere; raw value appears nowhere             |
| Endpoint prefixes      | messages, count-tokens, and root requests          | invalid/absent input yields `req_`, `tok_`, and `inf_` respectively        |
| Passthrough parity     | translated and Anthropic-passthrough requests      | both paths share the validated state value and Forge-owned response header |
| Existing Forge headers | valid and spoofed `X-Forge-*` values               | their independent validation and persistence behavior remain unchanged     |
| Direct-path join       | `core.llm` request-ID minter                       | every minted ID satisfies the proxy ingress validator                      |

## Verification and closeout

- [x] Run the marked D036 regression and review-focused correlation/middleware/audit tests (125 passed).
- [x] Run translated and passthrough targeted Docker integration (two passed).
- [x] Run the full unit and marked regression suites (8,954 unit and 716 regression passed; one unit skip).
- [x] Review normative/operator docs and update them only if the internal ingress contract changes a documented surface.
- [x] Synchronize member, child-epic, parent-epic, ledger, and change-log evidence without closing the child epic before
  merge.
- [x] Run board link/size checks, diff checks, and `make pre-commit`.
- [ ] Receive independent review and merge, then close the proxy-diagnostic hygiene epic.
