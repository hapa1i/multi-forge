# Forge Subprocess Routing Design

Canonical subprocess routing, consumer lanes, dispatch, and freeze contracts. See [runtime design](design_runtime.md)
for proxies, backends, model catalogs, and isolation.

#### 3.6.12 Subprocess routing resolution (normative)

Forge subprocesses (workflow workers, semantic and team supervisors, memory writer) share `resolve_subprocess_routing()`
when they need Forge-owned transport selection. This replaced ad-hoc resolution paths that implemented different
fallback chains with different semantics. Intentional direct and runtime-native arms bypass the resolver.

Interactive main-session model selection does **not** use this ambient subprocess chain.
`forge.core.ops.session_model_routing` owns its read-only plan: explicit proxy/no-proxy, compatible persisted route,
new-Claude direct, then ordered package-catalog candidates. It inspects template/instance tier maps and backend-source
credentials without scanning unrelated running proxies or starting a process. `realize_session_model_route()` realizes
only the selected plan, calls `ensure_proxy()` once when startup/reuse is required, revalidates concrete identity and
compatibility, and treats every post-selection failure as terminal. The plan's exact selected-model context window is
the input to session resume/fork budget preflight; intent mutation remains a later lifecycle transaction.

**Resolution chain** (sources not supplied by a caller are skipped):

| Step | Source             | Behavior                                                                                        |
| ---- | ------------------ | ----------------------------------------------------------------------------------------------- |
| 1    | `explicit`         | Opaque base-URL override                                                                        |
| 2    | `explicit`         | Named CLI/config proxy; strict registration, reachability, and route compatibility              |
| 3    | `subprocess_proxy` | Ambient `FORGE_SUBPROCESS_PROXY`; strict, or host-injected sidecar URL/metadata                 |
| 4    | `preferred_proxy`  | Leading proxy candidate from the shared route catalog; soft -- skip if not running              |
| 5    | `route_scan`       | Find any running proxy compatible with a derived `ModelRoute`                                   |
| 6    | `session_proxy`    | Inherited `ANTHROPIC_BASE_URL`; opaque URLs are accepted when the caller does not require route |
| 7    | `unresolved`       | No route found; callers decide fail-open vs fail-closed                                         |

`source="direct"` is produced by workflow routing (`review.routing`) for direct-only model specs (e.g., `claude-opus`
running `claude -p --bare`), not by the shared resolver. Workflow routing also produces `source="runtime_native"` for
the Codex worker; that source intentionally has no `ModelRoute` because Codex owns model selection and auth. More
generally, `route=None` can also mean unresolved or opaque/non-model-specific routing (e.g., explicit base URL), so
`source` and `base_url` distinguish the cases.

**Supervisor model scope:** When semantic-supervisor routing resolves to a proxy URL, it invokes
`claude -p --model opus` and clears inherited Claude model-pin env vars (`ANTHROPIC_MODEL`,
`ANTHROPIC_DEFAULT_*_MODEL`). This keeps executor/session `--model` pins local to the executor while allowing the
semantic supervisor to use the selected proxy's `opus` tier.

The team supervisor also clears inherited model pins whenever any source resolves a base URL, including explicit,
ambient, inherited, and sidecar-injected URLs. It deliberately does **not** pass `--model opus`: the resumed team
supervisor keeps its existing model posture instead of acquiring semantic-supervisor tier policy. `direct=True` skips
resolution, while a truly unresolved route dispatches direct; both retain inherited model pins.

**Team commitment boundary:** The team handler resolves routing before its `on_dispatch` callback. Explicit or ambient
named proxies are strict: missing, corrupt, or unreachable entries fail open by skipping the check before lane freeze or
dispatch-usage emission. This includes an ambient `FORGE_SUBPROCESS_PROXY` that is unregistered (previously silently
fell through to direct) and one that is registered but unreachable (previously failed after dispatch commitment).
Reachable ambient proxies, inherited `ANTHROPIC_BASE_URL`, and sidecar-injected URLs keep the same destination but are
now visible early enough for cost tracking and model-pin scrubbing. The team caller supplies no `ModelRoute`, so
`preferred_proxy` and `route_scan` are no-ops.

This chain applies to the supervisor's default `claude_code` lane. The `codex` lane arm (the supervisor's
`consumer_lanes` binding, epic consumer_lanes) bypasses it entirely: `codex exec` runs **direct** to OpenAI with no
Forge proxy. See [design_subprocesses.md §G](design_subprocesses.md#g-subprocess-routing-reference) for the
consumer-lane layer.

**Fail behavior by subprocess type:**

| Subprocess          | On unresolved   | Rationale                                                        |
| ------------------- | --------------- | ---------------------------------------------------------------- |
| Workflows           | Fail closed     | User asked for this work; partial results worse than an error    |
| Semantic supervisor | Fail open       | Blocking the coding session is worse than skipping a check       |
| Team supervisor     | Dispatch direct | No configured route is a valid direct resumed-session posture    |
| Memory writer       | Fail open       | Async/best-effort; benefits future sessions, not the current one |

**Review worker preparation:** `review.worker_preparation` owns role/stance marker validation and fill, stable worker
IDs/labels, and `model:assignment` parsing. Commands retain domain types, routing/fan-out, and JSON schemas.

**Per-invocation routing plan:** Workflow commands resolve one frozen `WorkerRoutingPlan` for all workers at invocation
start. With Codex, it freezes one fresh cached readiness/auth/billing preflight; no workflow verb runs an inline doctor.
This prevents fan-out drift and keeps two-round consensus on one snapshot. Workflow JSON exposes decisions in
`resolved_models`: runtime, requested/actual model, provider, proxy, template, source, and selection state. Codex
entries report `resolved_model=null` and `model_selection="runtime_default"` because Forge neither pins nor observes the
exact model.

> **Routing reference details** — data type schemas (`ModelRoute`, `RoutingResult`, `WorkerRoutingPlan`), function
> signatures, route derivation ranking, and sidecar constraints are in
> [design_subprocesses.md §G](design_subprocesses.md#g-subprocess-routing-reference).

## G. Subprocess Routing Reference

Extracted from [design.md §3.6.12](design_subprocesses.md#3612-subprocess-routing-resolution-normative). Resolution
chain concept, fail-open/fail-closed semantics, and per-invocation routing plan remain in design.md.

**Consumer-lane layering (epic consumer_lanes).** Forge resolves each consumer's `(runtime, backend, model)` lane and
dispatches by runtime (`forge.core.lanes`; `resolve_lane` is pure). Persisted `consumer_lanes` bindings cover semantic
supervisor, shadow-curation, memory-writer, and team-supervisor. Policy-check resolves `SUPERVISOR_CONSUMER` and
**injects** its `LaneRecord` into `run_supervisor_check` for the two `_dispatch_supervisor` arms:

- **`claude_code`** (default lane) -- the byte-identical `claude -p` path; transport (direct vs proxy / `base_url`) is
  still derived inside the arm by `resolve_subprocess_routing` (the chain below). The lane layer never touches the proxy
  registry.
- **`codex`** -- the non-Claude supervisor lane, selected by the supervisor's `consumer_lanes` binding (a declared
  `SUPERVISOR_CONSUMER` candidate on the `chatgpt` subscription backend, `reachable_via=("codex",)`, T2). The
  policy-check hook reads the binding (`read_bound_lane`, confirmed-first then intent) and **injects** the resolved lane
  into `run_supervisor_check`, which never reads the store. Runs headless `codex exec` **direct** to OpenAI (no proxy,
  read-only sandbox), **blind/transfer-fed** -- Codex has no `--resume`, so the approved plan must reach it via the
  plan-override preamble. Preflight is **cached, never probed in the hook**: `codex doctor` is ~20s and
  `run_doctor=False` cannot see `codex_store` (ChatGPT-login) auth, so the arm reads the `run_doctor=True` preflight
  that `forge runtime preflight codex` wrote to `core/runtime/codex_preflight_cache.py` (invalidated by codex-binary +
  `$CODEX_HOME/auth.json` mtime + TTL). The invoker auto-emits the sole `emit_codex_usage`, and the arm passes
  `Attribution.operation=None` so the shared invoker **suppresses** its upstream-outcome row -- the engine's
  `policy.evaluate` is the arm's only upstream row (parity with the claude arm; T5/WS1 resolved T4's documented
  double-count). Every failure (bad override, cold/stale/unready cache, plan-absent, or any setup exception) **fails
  open** -- the supervisor's contract (design_workflows §1.2).

For supervisor, shadow-curation, and memory-writer, `runtime_id` selects the Claude Code or Codex arm. Codex
`backend_id`/`model` are placement metadata: Codex selects its model; preflight auth determines billing. Claude Code
`backend_id` drives `resolve_billing_mode` (for example, `claude-max`). Team-supervisor lacks a Codex candidate and is
billing-only. T1b replaced `supervisor_runtime` with a persisted consumer-lane `LaneRecord`. The **first policy check**
for a registered supervisor freezes an explicit `intent.consumer_lanes` override into `confirmed.consumer_lanes` -- a
commitment, not a dispatch. Default lanes never freeze and remain re-pinnable. `--supervisor-runtime` and
`policy supervisor set <target> --runtime` set the override; raw `set` is rejected. Re-pinning is an idempotent no-op;
`policy supervisor remove` clears intent and confirmed.

**Aux consumers on `claude-max` (T6a).** All three aux consumers use the same machinery. A `claude-max` binding keeps
the default `claude_code` runtime, changing the **billing label, not dispatch**. Shadow-curation and memory-writer also
have dispatch-changing Codex lanes (T6b/T6c); team-supervisor is billing-only.
`forge session lane set --consumer <id> --backend claude-max` writes `intent`; `on_dispatch` freezes it into `confirmed`
on Claude dispatch, or `codex exec` for shadow-curation and memory-writer. `persist_lane_freeze` is best-effort: lock
failure never blocks a run; skipped/throttled runs never freeze. Under lock, it uses the supervisor's
`read_bound_lane(m) == dispatched_lane` guard. Unlike the supervisor's first-check commitment, aux consumers freeze only
on dispatch; they lack a registration commitment point. `read_bound_backend_id` yields `claude-max`; a **keyless +
direct** run is `subscription_quota`, a resolvable key wins as `api`, and a proxied run is `unknown`. Billing works from
`intent` alone (confirmed-first **then intent**); freezing adds immutability and a stable observable binding, not the
label.

**Shadow-curation codex arm (T6b).** This clean mirror-T4 consumer (blind, read-only, stdout-is-output) allows
`Lane(codex, chatgpt, gpt-5-codex)`. The curate CLI passes its `LaneRecord` to `run_shadow_curation`, which validates
`LaneRecord -> Lane -> resolve_lane`; invalid explicit bindings fail loud before any wrong-arm dispatch. Runtime
branches into `_dispatch_codex_shadow_curation` before Claude `on_dispatch`; the `claude_code` path stays
byte-identical. The arm mirrors `_dispatch_codex_supervisor` -- cached preflight, read-only direct `codex exec`,
self-contained prompt -- but its contract differs on three axes:

- **Degrade: fail-loud, not fail-open.** User-invoked, so a cold/unready preflight or a failed turn returns
  `CurationResult(success=False)` carrying a refresh hint surfaced by the CLI (human via `print_error` + `--json`, the
  new `CurationResult.error`); it never silently falls back to claude.
- **Upstream row: `operation="memory.shadow_curation"`, not `None`.** Curation has no engine `policy.evaluate` row, so
  the invoker's auto `record_upstream_operation` is its only upstream outcome and must match the claude path -- the
  opposite of the supervisor arm, which suppresses that row.
- **Freeze past the preflight skip-gate.** `on_dispatch` fires only after preflight passes: a cold preflight that never
  spawns codex does not freeze; a turn that spawns then fails still freezes (claude-arm parity). `runtime_is_error` is
  folded (the invoker's `success` is returncode-only) so an exit-0-but-failed turn fails loud instead of persisting an
  empty report.

**Memory-writer codex arm (T6c).** Its `Lane(codex, chatgpt, gpt-5-codex)` can **write the repo** in augment mode.
`forge memory-writer run` passes the bound `LaneRecord` to `run_memory_writer`, which resolves
`LaneRecord -> Lane -> resolve_lane` **before** the Claude-availability check, then branches into
`_dispatch_codex_memory_writer` ahead of Claude `on_dispatch`. It differs from T6b in two ways:

- **Degrade: best-effort async, not fail-loud.** The writer runs detached from the work queue (stdout -> DEVNULL), so
  every failure logs + records an outcome + `return False` (never raises, never fails-open). Resolving the runtime
  before the `is_claude_available()` gate -- which now guards only the claude arm -- lets a codex-bound writer run when
  claude is absent (Finding 2).
- **Per-mode sandbox; no permission scan (D4).** `review-only` -> `read-only`; `augment` -> `workspace-write`, editing
  the designated docs in place. A Phase 0 probe confirmed codex auto-approves in-project writes and auto-rejects
  out-of-project ones -- but a rejection exits 0 with `is_error=False` (it rides `turn.completed`), so
  `runtime_is_error` does not catch it. Immaterial: an in-project doc update (`cwd=forge_root`) never hits that path, so
  the Claude `_stdout_indicates_permission_denied` scan is not ported; real provider/turn failures still fold via
  `runtime_is_error`.

Outcome recording matches T6b (Finding 1): the invoker's `_emit_codex` owns the single upstream row for a spawned run
(failure-biased, so a success writes none under default volume -- claude parity); the arm records manually only on a
no-spawn preflight/setup failure.

Team-supervisor (plan-blind without snapshot machinery) stays billing-only for now, pending a context-model change --
its shape diverges from the mirror-T4 template. (Memory-writer's divergent shape shipped as T6c, above.)

**Observability (T5/T1b).** `forge policy supervisor status` displays the full `(runtime, backend, model)` lane via
`resolve_supervisor_lane(read_bound_lane(...))`: the **frozen `confirmed` binding** when present (a real dispatch
record, T1b), else the `intent` override or the default claude lane. `runtime_id` selects the arm; the codex
`model=gpt-5-codex` stays nominal (codex picks its own model). Status revalidates `LaneRecord -> Lane` on every call and
**never rewrites** the manifest, so a frozen lane whose catalog entry was later removed prints `Lane: not executable`
rather than crashing or silently falling back to the default. `forge telemetry activity` shows the per-call
`runtime`/`billing_mode` each command ran on (`mixed` when a command's events disagree); the usage ledger carries no
catalog backend id, so the full lane shows only on supervisor status. The team event tagger emits `team-tagger` usage
events through `.complete()`, which retains the token counts that `.ask()` discarded.

**Subscription-exhaustion degrade (T7).** A supervisor check that exhausts its bound codex subscription
(`failure_type="subscription_exhausted"`, classified in `run_supervisor_check` from the codex JSONL message -- no
structured status survives the `codex exec` boundary) persists a sticky degrade overlay in
`confirmed.policy.policy_states["forge.supervisor_lane_degrade"]`, deliberately *separate* from the immutable
`consumer_lanes` binding. The write rides the existing freeze lock behind the same
`read_bound_lane(m) == dispatched_lane` stale-write guard; the read side (`register_supervisor_and_restore`) injects
`lane_record=None` when degraded, so later checks dispatch the default claude lane while the frozen codex binding stays
observable (`lane show` and `supervisor status` annotate it `degraded`, `from`/`to` audit-only -- routing never trusts
the stored `to_lane`). Reset follows the *binding*, not the command name: `supervisor remove` and a re-pin
(`set --runtime/--backend`, `session lane set --consumer supervisor`) clear it; `session lane clear` does not (the
frozen binding still dispatches codex); a fresh process resume (`SessionStart source in {startup, resume}`) clears it so
a refilled weekly quota is retried, while `compact`/`clear` preserve it (mid-sitting -- re-arming codex would just
re-exhaust). The degrade emits exactly one upstream `policy.lane_degraded` outcome (`command=supervisor`,
`reason_code=subscription_exhausted`, from/to lane in `message`), read by `forge telemetry activity` -- not a
`UsageEvent`. Fail-open throughout (design_workflows §1.2): a degrade-path error still degrades the check to allow, and
a drifted default catalog still degrades (route by `None`, `to_lane` null).

### G.1 Core types (from `core.reactive.routing`)

```python
RoutingSource = Literal[
    "explicit",
    "subprocess_proxy",
    "preferred_proxy",
    "route_scan",
    "session_proxy",
    "direct",
    "runtime_native",
    "unresolved",
]

@dataclass(frozen=True)
class ModelRoute:
    provider: str
    credential: str
    family: str
    template_id: str | None
    template_family: str | None
    model_ref: str

@dataclass(frozen=True)
class RoutingResult:
    base_url: str | None
    proxy_id: str | None
    template: str | None
    source: RoutingSource
    route: ModelRoute | None
    credential: str | None
    warning: str | None = None
```

`direct` has a concrete route. `runtime_native` deliberately has none because the runtime owns selection and auth (the
`codex` worker). `unresolved` means failure. A route-null shared-resolver result can still be successful opaque base-URL
passthrough; `source` and `base_url` distinguish it.

### G.2 Workflow types (from `review.routing`)

```python
@dataclass(frozen=True)
class WorkerRoutingPlan:
    routes: tuple[RoutingResult, ...]
    resolved_at: str
    via_override: str | None
    codex_preflight: CodexPreflight | None = None
```

Workflow plans accept `route=None` only for `runtime_native`; every other route-null entry fails closed. This does not
narrow the shared resolver's opaque `require_route=False` successes.

### G.3 Key function signatures

```python
def resolve_subprocess_routing(
    explicit_base_url: str | None = None,
    explicit_proxy: str | None = None,
    preferred_proxy: str | None = None,
    routes: tuple[ModelRoute, ...] = (),
    *,
    require_route: bool = False,
    use_environment: bool = True,
    advisory_check: bool = False,
) -> RoutingResult:
    """Unified routing resolution for all Forge subprocesses.

    Walks the 6-step chain. Callers decide fail-open vs fail-closed
    based on source and their use case.
    """

def derive_model_routes(spec: RoutableSpec) -> tuple[ModelRoute, ...]:
    """Materialize the shared route catalog for one workflow worker.

    Candidate order comes from model_routes.yaml. Template metadata
    contributes family/provider/credential facts without registry I/O.
    """

def resolve_invocation_routing(
    specs: Sequence[Any],
    via: str | None = None,
) -> WorkerRoutingPlan:
    """Resolve routing for all workers at invocation start.

    Fail-closed: raises if any worker has no route.
    """

def resolve_model_flag(route: ModelRoute) -> str | None:
    """Return --model flag for a routed workflow worker.

    Proxied workers: route.model_ref. Direct workers: None (use env pins).
    """
```

### G.4 Route derivation ranking

`derive_model_routes()` preserves the exact candidate order in packaged `model_routes.yaml`; workflow code neither
re-ranks candidates nor owns a parallel preferred-proxy/provider-ref list. The first proxy candidate is the soft
`preferred_proxy` input to the shared resolver. The catalog's fixed-order tests guard preferred-template promotion,
provider order, native-family-before-cross-family placement, and template tiebreakers.

Registry scan then ranks matched proxies:

1. Route preference order from the shared catalog
2. Alphabetical proxy_id as tiebreaker

### G.5 Sidecar constraints

In sidecar mode (`~/.forge` not mounted), registry-dependent steps are unavailable:

| Step                | Host mode | Sidecar mode                                                   |
| ------------------- | --------- | -------------------------------------------------------------- |
| `explicit_base_url` | Opaque    | Works (returned before sidecar checks; opaque URL passthrough) |
| `explicit_proxy`    | Registry  | Works only via injected env metadata                           |
| `subprocess_proxy`  | Registry  | Works via `FORGE_SUBPROCESS_BASE_URL`/`PROXY_ID`/`TEMPLATE`    |
| `preferred_proxy`   | Registry  | No-op (registry unavailable)                                   |
| `route_scan`        | Registry  | No-op (registry unavailable)                                   |
| `session_proxy`     | Env       | Works (`ANTHROPIC_BASE_URL` inherited from host)               |

Proxy IDs are resolved on the host before entering the sidecar. If a user supplies a plain proxy ID inside a sidecar
with no injected metadata, Forge fails with an actionable error suggesting `--subprocess-proxy` at session start or
running the workflow on the host.

---
