# Checklist -- proxy_ingress_and_config_wiring

**Branch**: `refactor/proxy-ingress-config-wiring`
**Current focus**: Slice B1 (wire-shape vocabulary leaf)

Single-card execution (decision 2026-08-02). Order: B1 -> B3 -> B2 -> B4 -> A1. Each slice is independently
verifiable; `make test-unit` green per slice, proxy integration before closeout.

---

## Slice B1: `core/wire_shapes.py` vocabulary leaf

- [ ] New `src/forge/core/wire_shapes.py`: `WireShape` Literal, the three shape constants, `VALID_WIRE_SHAPES` tuple,
      `DEFAULT_WIRE_SHAPE`. Imports nothing beyond `typing`.
- [ ] Repoint code-literal sites (docstrings/error text stay prose): `config/schema.py:273` (`_VALID_WIRE_SHAPES` ->
      import), `config/loader.py:463` (default), `core/reactive/env.py:65-66` (fold half-centralized constants into the
      leaf; re-export or repoint consumers), `proxy/responses_ingress.py` (code sites), `proxy/server.py:599/1864/1949`,
      `session/model_pin.py:18`, `proxy/proxy_orchestrator.py:1033/1046/1114-1115`, `core/runtime/codex_preflight.py:515`.
- [ ] Unit tests for the leaf (membership, default, Literal/tuple parity).

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Leaf parity | none | `VALID_WIRE_SHAPES` == the 3 shapes; default is `openai_translated`; Literal args match tuple | `tests/src/core/test_wire_shapes.py` |
| No stray literals | none | `rg` for the 3 strings in `src/` code positions returns leaf + prose only (checked manually; recorded here) | manual sweep |
| Behavior preserved | existing suites | schema/loader/env/model_pin/orchestrator/preflight suites green unchanged | existing files |

## Slice B3: `forge info` home + version-parse dedup

- [ ] Move `info_cmd` + `_gather_info_data` + `_print_info_human` from `install/cli.py` to a `cli/` module
      (`cli/info.py`); `cli/main.py` imports from the new home.
- [ ] Replace the inline `claude --version` subprocess/parse with `install/version.py` (`get_claude_version` or
      `_run_claude_version` via its public wrapper). One parse in `src/` afterwards.
- [ ] Output identical except the drifted token fix (first version token, matching every other caller).

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Command home | CliRunner | `forge info` and `forge info --json` work from the new registration | existing info tests (repointed) |
| Parse dedup | mocked version helper | info's claude version comes from `install/version.py`, first-token form | info tests |
| No second parse | none | `rg 'claude.*--version'` in `src/` hits `install/version.py` only (+ prose) | manual sweep |

## Slice B2: shared block-field wiring

- [ ] One shared declaration (block-field names -> coercers) in `config/schema.py`, driving: hop 1's constructor kwargs
      (`load_proxy_instance_config_from_dict`), hop 2's constructor kwargs (`_proxy_instance_to_forge_config`), and both
      `__post_init__` coercion loops.
- [ ] Per-dataclass unique validations (provider/port/tiers/endpoint; per-provider tier-override constraints) stay
      explicit and untouched.
- [ ] Live-read regression: a block value set in a proxy dict reaches `config.proxy.<block>.*` through both hops (not
      schema-only).

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Live-read wiring | proxy dict with non-default `intercept`/`audit`/`provider_trace`/`logging`/`costs`/`wire_shape` | every block survives hop1+hop2 to `ForgeConfig.proxy` | `tests/src/config/` (new or extended) |
| Drift guard | dataclass introspection | every shared block field exists on both dataclasses and is covered by the declaration | same |
| Posture untouched | invalid provider / bad port / bad tier override | same errors as before, same messages | existing schema tests green |

## Slice B4: `OPENAI_MODELS` conformance test

- [ ] Determine the intended relationship (allowlist entries present in catalog `models:`?) and pin it in a test; no
      single-sourcing (config decision not taken here).

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Conformance | catalog YAML | every `OPENAI_MODELS` entry cross-checks against the catalog per the determined relationship | `tests/src/config/test_schema.py` |

## Slice A1: passthrough ingress extraction (caution zone -- characterization first)

- [ ] Characterization test BEFORE the move: passthrough request records cost, provider-trace, metrics, audit in the
      current order; wire bytes forwarded unchanged (existing passthrough suites + a new ordering assertion if missing).
- [ ] Extract `_handle_anthropic_passthrough` + `_apply_passthrough_override` to `proxy/passthrough_ingress.py`,
      mirroring `responses_ingress.py`'s lazy-import dependency pattern and route-registration shape.
- [ ] `server.py` keeps registration + the GET / advert wiring; no `converters.py` change; no intercept/override split.
- [ ] Characterization green after the move, byte-identical assertions.

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Characterization | fake upstream, passthrough proxy config | wire bytes unchanged; cost -> trace -> metrics ordering identical pre/post move | `tests/src/proxy/` |
| Existing suites | -- | passthrough/server/audit/cost suites green unchanged | existing |
| Integration | Docker LiteLLM | `./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py` green | integration |

## Closeout

- [ ] `make test-unit` green; relevant proxy integration files green
      (`tests/integration/proxy/test_proxy_local_litellm_e2e.py`, `test_session_routing_e2e.py`).
- [ ] `make pre-commit` clean.
- [ ] Design-doc sync: none expected (internal placement only; §3.7/§7.x behavior unchanged) -- re-verify at closeout;
      update `docs/design.md` §6 directory map if `core/wire_shapes.py` / `passthrough_ingress.py` warrant a line.
- [ ] Change-log entry; card `doing/` -> `done/`; repoint inbound links (none known -- verify with `rg`).
