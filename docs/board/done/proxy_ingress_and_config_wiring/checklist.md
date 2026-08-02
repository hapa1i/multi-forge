# Checklist -- proxy_ingress_and_config_wiring

**Branch**: `refactor/proxy-ingress-config-wiring` **Current focus**: Closeout

Single-card execution (decision 2026-08-02). Order: B1 -> B3 -> B2 -> B4 -> A1. Each slice is independently verifiable;
`make test-unit` green per slice, proxy integration before closeout.

---

## Slice B1: `core/wire_shapes.py` vocabulary leaf

- [x] New `src/forge/core/wire_shapes.py`: `WireShape` Literal, the three shape constants, `VALID_WIRE_SHAPES`,
  `PASSTHROUGH_WIRE_SHAPES` (byte-faithful pair, used by two sites), `DEFAULT_WIRE_SHAPE`. Imports `typing` only.
- [x] Repointed all code-literal sites, including three the card missed (schema.py:621 validator + both dataclass field
  defaults :664/:753, found by the closing sweep): schema.py, loader.py, env.py (local constants deleted, 3 usages),
  responses_ingress.py (5 sites), server.py (3), model_pin.py, proxy_orchestrator.py (3), codex_preflight.py.
- [x] Leaf unit tests: `tests/src/core/test_wire_shapes.py` (4 tests -- membership, default, Literal/tuple parity,
  passthrough subset).
- [x] Sweep: `rg '"(openai_translated|anthropic_passthrough|openai_responses_passthrough)"' src/forge/ --type py`
  returns the leaf + prose (docstrings/comments) only. Full unit suite 8,643 passed; mypy + ruff clean on touched files.
  Committed.

| Test               | Fixture         | Assertion                                                                                                   | Test File                            |
| ------------------ | --------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| Leaf parity        | none            | `VALID_WIRE_SHAPES` == the 3 shapes; default is `openai_translated`; Literal args match tuple               | `tests/src/core/test_wire_shapes.py` |
| No stray literals  | none            | `rg` for the 3 strings in `src/` code positions returns leaf + prose only (checked manually; recorded here) | manual sweep                         |
| Behavior preserved | existing suites | schema/loader/env/model_pin/orchestrator/preflight suites green unchanged                                   | existing files                       |

## Slice B3: `forge info` home + version-parse dedup

- [x] Moved to `cli/info.py` (git rename, 90% similarity); `install/cli.py` deleted (info was its only content);
  `cli/main.py` repointed. No other importers existed.
- [x] Inline parse replaced with `install/version.py::get_claude_runtime_version` (cached, first-token). Sweep: one
  `claude --version` parse remains in `src/`.
- [x] `forge info` had NO existing tests; new `tests/src/cli/test_info.py` (4 tests: sections, `--json` shape, version
  from shared helper, no helper call when binary absent). Also fixed the stale `InstallProfile` docstring (standard now
  includes skills/status-line; full == standard). CLI+install suites 3,374 passed. Committed.

| Test            | Fixture               | Assertion                                                                   | Test File                       |
| --------------- | --------------------- | --------------------------------------------------------------------------- | ------------------------------- |
| Command home    | CliRunner             | `forge info` and `forge info --json` work from the new registration         | existing info tests (repointed) |
| Parse dedup     | mocked version helper | info's claude version comes from `install/version.py`, first-token form     | info tests                      |
| No second parse | none                  | `rg 'claude.*--version'` in `src/` hits `install/version.py` only (+ prose) | manual sweep                    |

## Slice B2: shared block-field wiring

- [x] `PROXY_BLOCK_COERCERS`/`PROXY_BLOCK_FIELDS` + `_coerce_proxy_blocks` in `config/schema.py` drive both
  `__post_init__` loops, hop 1, hop 2, AND a third enumeration point found during the slice:
  `proxy_orchestrator.create_proxy_file` (template -> proxy.yaml). `write_proxy_instance_config` verified safe
  (`asdict`, whole-dataclass). Block defaults now have one source: the dataclass fields.
- [x] Per-dataclass unique validations untouched; wire_shape error message pinned unchanged
  (`test_invalid_wire_shape_message_unchanged`).
- [x] Live-read tests: `tests/src/config/test_proxy_block_wiring.py` (marker-per-block through both hops, completeness
  guard tied to the registry, defaults-single-source, dataclass drift guard).
- [x] **Bug found + fixed in-slice**: `create_proxy_file` dropped template-declared `costs`, so custom-template spend
  caps silently reverted at 'forge proxy create' (same class as the provider_trace/logging drop previously fixed there).
  Regression: `tests/regression/test_bug_create_proxy_file_costs_drop.py`. Full unit 8,653 + regression 594 passed.
  Committed.

| Test              | Fixture                                                                                         | Assertion                                                                             | Test File                             |
| ----------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------- |
| Live-read wiring  | proxy dict with non-default `intercept`/`audit`/`provider_trace`/`logging`/`costs`/`wire_shape` | every block survives hop1+hop2 to `ForgeConfig.proxy`                                 | `tests/src/config/` (new or extended) |
| Drift guard       | dataclass introspection                                                                         | every shared block field exists on both dataclasses and is covered by the declaration | same                                  |
| Posture untouched | invalid provider / bad port / bad tier override                                                 | same errors as before, same messages                                                  | existing schema tests green           |

## Slice B4: `OPENAI_MODELS` conformance test

- [x] Relationship determined and pinned: every catalog `openai/` alias and its canonical target must satisfy
  `is_openai_model` (`TestOpenAIModelsCatalogConformance` in `tests/src/config/test_schema.py`). No single-sourcing.
- [x] **Bug found + fixed in-slice**: the conformance test surfaced real drift -- `gpt-5.5-pro` was in the catalog but
  missing from `OPENAI_MODELS`, so the proxy misclassified it. Added to the allowlist. Committed (5db0b837).

| Test        | Fixture      | Assertion                                                                                    | Test File                         |
| ----------- | ------------ | -------------------------------------------------------------------------------------------- | --------------------------------- |
| Conformance | catalog YAML | every `OPENAI_MODELS` entry cross-checks against the catalog per the determined relationship | `tests/src/config/test_schema.py` |

## Slice A1: passthrough ingress extraction (caution zone -- characterization first)

- [x] Characterization test BEFORE the move: `test_passthrough_accounting_order_and_wire_bytes` in
  `tests/src/proxy/test_passthrough.py` pins cost -> metrics order, wire-byte fidelity (thinking field survives), and
  resolved-model/tier headers. Written and green pre-move.
- [x] Extracted `_handle_anthropic_passthrough` + `_apply_passthrough_override` to `proxy/passthrough_ingress.py`,
  mirroring `responses_ingress.py`'s lazy-import pattern (`import forge.proxy.server as server`, live singleton reads at
  call time -- all monkeypatch seams preserved). server.py 2361 -> 2088 lines.
- [x] `server.py` keeps registration + the GET / advert wiring (binds `_handle_anthropic_passthrough` to the imported
  handler so the dispatch/test seam is unchanged); no `converters.py` change; no intercept/override split.
- [x] Characterization green after the move; all 31 passthrough tests + full unit suite (8,655 passed) + mypy + ruff
  green. Integration gate: 12 passed (`test_proxy_local_litellm_e2e.py` + `test_session_routing_e2e.py`). Committed
  (c4c4e9f8).
- [x] **Pre-existing bug found + fixed during the gate** (not an A1 regression -- reproduced on pristine `main`):
  `proxy_server_local_openai` started the proxy template-only, so the `litellm_local` provider override (gated on
  `FORGE_PROXY_ID` + proxy.yaml `upstream_base_url`) never fired and the preflight 500'd without `LITELLM_BASE_URL` in
  the environment. Fixture now registers the proxy with the isolated upstream. Committed (190f5365).

| Test             | Fixture                                 | Assertion                                                                                     | Test File          |
| ---------------- | --------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------ |
| Characterization | fake upstream, passthrough proxy config | wire bytes unchanged; cost -> trace -> metrics ordering identical pre/post move               | `tests/src/proxy/` |
| Existing suites  | --                                      | passthrough/server/audit/cost suites green unchanged                                          | existing           |
| Integration      | Docker LiteLLM                          | `./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py` green | integration        |

## Closeout

- [x] `make test-unit` green (8,655 passed, 1 pre-existing skip); proxy integration gate green: 12 passed across
  `tests/integration/proxy/test_proxy_local_litellm_e2e.py` + `test_session_routing_e2e.py`.
- [x] `make pre-commit` clean (all hooks pass; one mypy splat-typing fix in `test_proxy_block_wiring.py`, e2945f06).
- [x] Design-doc sync re-verified: behavior sections unchanged as expected. Added `core/wire_shapes.py` to the
  `docs/design.md` §6 directory map (peer of `tiers.py`); `passthrough_ingress.py` omitted -- the map lists neither
  `server.py` nor `responses_ingress.py`, so a line there would be inconsistent granularity.
- [x] Change-log entry added; card moved `doing/` -> `done/`; inbound-link sweep: only this card's own files and
  historical `done/` cards reference the touched paths -- no live links to repoint.
