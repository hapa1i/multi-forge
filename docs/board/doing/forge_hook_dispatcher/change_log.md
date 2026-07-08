# Change log: T4 `forge_hook_dispatcher`

## 2026-07-08

### Goal

Ship the user-scope hook dispatcher mechanism: a fast no-op gate, durable `forge` resolver metadata, rendered dispatcher
command bytes, stale-shim surfacing, and tests, without flipping hook registration to user scope.

### Key changes

- Chose the stdlib `forge-hook` shim from a populated-registry benchmark: p95 22.13 ms vs p95 611.78 ms for the full
  Forge gate representative.
- Added `~/.forge/bin/forge-hook` rendering plus `~/.forge/runtime.json` metadata, resolver fallback through known
  user-tool locations, no-op gate parity with the project registry, and runtime-agnostic `exec` forwarding.
- Extended `forge extension enable/sync` to render the dispatcher artifact and `forge extension doctor` to report
  missing/stale/unreadable dispatcher state.
- Documented the dispatcher deployment model, metadata home, absolute command form, and stale-shim contract.

### Verification

- `uv run pytest tests/src/install/test_hook_dispatcher.py tests/src/install/test_doctor.py tests/src/cli/test_extension_enable.py tests/src/cli/test_env_vocabulary.py -q`
- `uv run pytest tests/src/install -q`
- `make pre-commit-md`
- `make pre-commit`
- `make test-unit`
- `./scripts/test-integration.sh tests/integration/docker/test_installer.py`
