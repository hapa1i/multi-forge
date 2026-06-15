# Supervisor Launch Controls -- cascade parity and effort plumbing

**Status**: Proposed. Split from `docs/board/proposed/same_dir_transfer_forks/card.md` so same-directory transfer can
ship without being blocked by effort-control design questions.

**References**: `src/forge/cli/session_fork.py` and `src/forge/cli/session_lifecycle.py` launch-time `--supervise`
flags; `src/forge/cli/policy.py::supervise_cmd` cascade/checker options;
`src/forge/session/models.py::SupervisorConfig`; `src/forge/policy/semantic/plan_check.py` tier-1 checker routing and
prompt budget logic; `forge policy supervisor` one-shot evaluation.

## Problem

`forge session fork --supervise` and `forge session start --supervise` can configure supervisor routing, but they cannot
fully express the supervision posture a user may already know they want at launch time.

There are two distinct gaps:

1. **Launch-time parity for existing cascade knobs**: persistent `forge policy supervise` already supports
   `--cascade`, `--checker-model`, and `--checker-provider`, and `SupervisorConfig` already has matching fields. Fork
   and start should be able to persist those values before the child begins.
2. **New effort controls**: `checker_effort` does not exist on `SupervisorConfig` today, and the tier-1 plan checker
   currently uses `checker_budget_tokens` for prompt packing rather than passing `reasoning_effort` into the
   `core.llm` call. Effort is new plumbing, not a simple CLI passthrough.

Bundling these with same-directory transfer would make ready UX cleanup wait on model-effort design. Keep this as its
own card.

## Proposal

### 1. Phase 1: launch-time parity for existing cascade knobs

Add existing cascade/checker controls to supervised launch commands:

```bash
forge session fork parent \
  --name child \
  --supervise \
  --supervisor-proxy openrouter-openai \
  --cascade \
  --checker-model google/gemini-3.5-flash \
  --checker-provider openrouter

forge session start child \
  --supervise planner \
  --cascade \
  --checker-model google/gemini-3.5-flash \
  --checker-provider openrouter
```

Route validation and manifest mutation through the same helper used by `forge policy supervise <target> --cascade ...`
so launch-time and policy-time behavior do not drift.

### 2. Phase 2: explicit effort controls

Start Phase 2 with one external probe: determine whether `claude -p` exposes a per-invocation reasoning-effort lever.
That decides whether `--supervisor-effort` can be implemented client-side for the frontier supervisor, or whether
frontier effort must stay governed by proxy tier/model configuration.

Add effort knobs only after deciding the storage and model-call plumbing:

- `--checker-effort <value>` for the tier-1 plan-check `core.llm` call
- `--supervisor-effort <value>` for the frontier supervisor path, if that path can apply effort reliably
- durable defaults, for example:

```yaml
policy:
  supervisor:
    checker_effort: low
    supervisor_effort: medium
```

Do not add a bare `--effort` flag unless the checker and frontier supervisor are intentionally coupled. They are
different LLM paths with different routing and support constraints.

The one-shot CLI should also use explicit names:

```bash
forge policy supervisor -f src/foo.py -r planner \
  --proxy openrouter-openai \
  --cascade \
  --checker-effort low \
  --supervisor-effort medium
```

### 3. Documentation and help

Update:

- `forge session fork --help`
- `forge session start --help`
- `forge policy supervise --help`
- `forge policy supervisor --help`
- `docs/end-user/session.md`

Docs should show a one-command supervised fork/start shape and explain that effort is separate from prompt budget.

## Open questions

- Should launch-time cascade options imply `--supervise`, or require it explicitly?
- Where should default checker/supervisor effort live: global runtime config, policy config, proxy tier overrides, or
  supervisor config defaults?
- Should `checker_effort` live on `SupervisorConfig` beside `checker_budget_tokens`, or in a nested checker config?
- Does `claude -p` expose a per-invocation reasoning-effort lever, or is frontier supervisor effort proxy-tier-only?
- Should one-shot `forge policy supervisor --cascade` use the same approved-plan resolution as persistent cascade, or
  require an explicit plan file?
- How should validation handle model-dependent effort values whose support is only known through the provider/catalog?

## Risks

- Launch-time cascade flags can duplicate `forge policy supervise` logic. Route all surfaces through one supervisor
  configuration helper so defaults, validation, and manifest writes do not drift.
- Effort values are provider/model dependent. Validation must be helpful without rejecting valid OpenRouter models whose
  supported effort set is only known at request time.
- Frontier supervisor effort may not be directly controllable through `claude -p`. If so, document that it is governed
  by proxy tier/model configuration instead.
- Mixing checker and supervisor effort under one option would make it unclear which LLM path changed.

## Acceptance sketch

- **Fork can enable cascade**: `fork --supervise --cascade --checker-model ...` persists supervisor cascade and checker
  model before launch.
- **Start can enable cascade**: `start --supervise planner --cascade --checker-provider ...` persists the same
  `SupervisorConfig` fields as `forge policy supervise`.
- **Launch parity uses shared validation**: invalid checker provider/model errors match `forge policy supervise`.
- **Supervisor effort probe recorded**: Phase 2 records whether `claude -p` supports per-invocation reasoning effort,
  and gates `--supervisor-effort` behavior on that answer.
- **Checker effort default applies**: config default `checker_effort=low` resolves into a supervised cascade session
  without a CLI effort flag, and the tier-1 `core.llm` call receives low reasoning effort.
- **Checker effort override wins**: launch or policy CLI `--checker-effort low` overrides a medium config default, and
  the plan-check call receives low effort.
- **Explicit one-shot effort**: `forge policy supervisor ... --checker-effort low --supervisor-effort medium` passes
  effort through the selected checker/supervisor paths or errors if unsupported.
