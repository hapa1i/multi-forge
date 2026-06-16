# Unified Backend Concept -- local and remote model sources as one first-class axis

**Status**: Proposed. Spun out of the `openrouter_observability` investigation (2026-06-16) while reasoning about whether
the provider-trace plane generalizes beyond OpenRouter. The local provider-trace card
(`docs/board/doing/openrouter_observability/card.md`) is the **first intended consumer**: its hardcoded
`provider_name == "openrouter"` gate is exactly the model-source identity this card would canonicalize.

**References**: `src/forge/backend/` (`BackendAdapter`, `BackendManager`, the runtime-instance `BackendInstance`/
`BackendRegistry` in `registry.py`), `BackendDependency` (`src/forge/config/schema.py`), the `ProviderType` enum, the
auth dependency map `TEMPLATE_ENV_VARS` (`src/forge/core/auth/template_secrets.py`) + `credentials_for_template()`
(`forge.core.auth.capabilities`; `Credential.unlocks_features` is presentation-only), proxy templates (`*-local` vs
`openrouter-*` in `src/forge/config/defaults/templates/`), the provider-trace plane
(`src/forge/proxy/provider_trace_logger.py`), design.md §3 (session/proxy separation, identity model), and
cli_reference.md §1 (`forge backend` / `forge proxy` / `forge authentication`).

## Problem

Forge has a first-class concept for a model source you **run locally** -- a *backend* -- but no first-class concept for
a model source you **connect to remotely**. The remote half exists, but only implicitly, inferred from a proxy
template's `base_url` plus a credential.

Concretely, a "backend" today is a lifecycle-managed local process: `BackendAdapter` (`backend/__init__.py:29`) is
*defined by* its lifecycle (`start` / `stop` / `health_check` of a process with a PID); `LiteLLMAdapter` spawns
`litellm --config ... --port N`, health-probes `/health/liveliness`, and registers a `BackendInstance` (`backend_id`,
`adapter_type`, `port`, `pid`, `status`) under `~/.forge/backends/`. Six `*-local` templates declare a
`backend_dependency`; OpenRouter and remote-LiteLLM templates declare none -- they carry a `base_url` directly.

The "model source" concept is therefore **real but scattered across four sites**, and only the local half is a named,
listable thing:

| Identity site                                    | Local (LiteLLM)                                  | Remote (OpenRouter / remote LiteLLM)            |
| ------------------------------------------------ | ------------------------------------------------ | ----------------------------------------------- |
| Lifecycle                                        | `BackendDependency` -> `BackendManager`/`Adapter` | none (no process to manage)                     |
| Identity / listing                               | `forge backend`, id `litellm-<port>`             | inferred from `preferred_provider` + a template |
| Wire client                                      | `ProviderType.litellm_local`                     | `ProviderType.openrouter` / `litellm_remote`    |
| Auth link                                        | `TEMPLATE_ENV_VARS` -> `GEMINI_API_KEY` etc.     | `TEMPLATE_ENV_VARS` -> `OPENROUTER_API_KEY`     |

> **Auth-link note.** The machine-readable contract is `TEMPLATE_ENV_VARS` (template -> env var names, in
> `template_secrets.py`) reverse-mapped to credentials by `credentials_for_template()`, plus connection values like
> `LITELLM_BASE_URL` (a base_url, not a secret, carried in the same map). `Credential.unlocks_features` is
> **presentation-only** (the human string in `forge authentication status`) and must not be treated as the dependency
> map.

The asymmetry is precise: **local sources are nouns you manage; remote sources are things you infer.** That fragments
two operator views in particular:

- **CLI explainability.** "What model sources does Forge know about?" requires reading `forge backend list` +
  `forge proxy template list` + `forge authentication status` and mentally joining them.
- **Auth transparency.** `forge authentication status` shows *credentials*; nothing shows, per source, its endpoint, the
  credential it needs, where that credential resolved from (`env` / `credentials.yaml` / omitted), and whether it is
  reachable and authed. The auth knobs (`auth_ignore_env`, `interactive_anthropic_api_key: omit`, connection values like
  `LITELLM_BASE_URL`) are legible only by tracing them by hand.

There is also a telemetry motivation. The four planes (cost, audit, usage, provider-trace) currently key on overlapping
ad-hoc identities (`proxy_id`, `provider`, credential name). Provider-trace literally hardcodes one source by string
(`provider_trace_logger.py:219`, `provider_name == "openrouter"`) because there is no canonical model-source id to key
on.

## The three axes (keep distinct; this card unifies only the source axis)

This card does **not** merge backend, proxy, and provider. They are deliberately separate and stay separate:

| Axis         | What it is                                       | Keyed by                       |
| ------------ | ------------------------------------------------ | ------------------------------ |
| **Proxy**    | Forge's routing endpoint Claude hits (`ANTHROPIC_BASE_URL`) | template + base_url + port |
| **Provider** | Per-request wire client inside the proxy         | `ProviderType` enum            |
| **Backend**  | The upstream **model source** the proxy reaches  | *this card: local \| remote*   |

Proxies route *through* backends; credentials *authenticate* backends; the telemetry planes *attribute to* backends. The
backend axis is the missing **spine** that the other three already lean on informally.

## Proposal

Promote "model source" to a first-class, listable concept with two kinds -- `local` and `remote` -- so OpenRouter (and
remote LiteLLM, and possibly direct Anthropic) become *remote backends* alongside the local LiteLLM backend.

### 1. A common supertype, lifecycle as a local-only refinement

The load-bearing design constraint: a remote source has **no process lifecycle**, so it must not be forced under the
current `BackendAdapter` (whose entire contract is `start`/`stop`/`health_check` of a process). Forcing it there makes
`start()` a lie and `forge backend start openrouter` an awkward error -- the tombstone-shaped wart coding-standards §6
rejects.

Introduce a supertype (the naming is an open question below) with:

- **Common**: id, `kind: local | remote`, resolved endpoint/base_url, required credential(s), proxies-that-use-it,
  health (semantics differ by kind).
- **Local-only**: the existing adapter lifecycle (`start`/`stop`/PID/port). Today's `BackendAdapter` becomes the local
  refinement.
- **Remote**: connection + auth check only (reachable? authed?), no lifecycle.

It is an *is-a vs has-a* split: a remote backend *has* an endpoint and auth but does *not have* lifecycle.

### 2. CLI symmetry: unified noun, divergent verbs

`forge backend list` shows both kinds in one view. The symmetry is at the **noun**, not every **verb** -- a deliberate,
acknowledged partial symmetry (cf. `git remote` vs local branches):

| Verb              | Local backend | Remote backend |
| ----------------- | ------------- | -------------- |
| `list` / `show`   | yes           | yes            |
| `start` / `stop`  | yes           | n/a            |
| `test-auth`       | yes           | yes            |

```text
$ forge backend list
ID             KIND    ENDPOINT                      CREDENTIAL              STATUS
litellm-4000   local   http://localhost:4000         GEMINI_API_KEY (env)    healthy (pid 1234)
openrouter     remote  https://openrouter.ai/api/v1  OPENROUTER_API_KEY (env) reachable, authed
litellm-remote remote  $LITELLM_BASE_URL             LITELLM_API_KEY (file)  reachable
```

### 3. Auth transparency (reframe, not simplify)

Each backend declares its credential dependency, so one view answers "what does this source need and where did the key
come from?" -- endpoint, required credential, resolution provenance (`env` / `credentials.yaml` / `omitted`),
reachability. The dependency map is `TEMPLATE_ENV_VARS` (`template_secrets.py`) reverse-mapped by
`credentials_for_template()` -- **not** the presentation-only `Credential.unlocks_features`; this reuses the existing
resolver and does **not** remove the resolution logic (`auth_ignore_env`, interactive omit, env > file). The win is
legibility and a clean thing to attach provenance to, not fewer auth code paths. Never echo a key -- report only the
provenance class.

### 4. Consolidation mandate (absorb the four sites, do not layer)

The refactor only pays off if a static **model-source catalog** becomes the **single source of truth** that templates
reference and credentials attach to. This catalog is the *definition* layer (id, kind, endpoint, required credentials)
and is **distinct from the runtime instance registry** (`BackendRegistry` / `~/.forge/backends/index.json`, which holds
PID/port/status for *running local* processes). The split already exists locally -- `forge backend create` writes a
static config under `~/.forge/backends/<adapter>/`, separate from `index.json` -- and a remote backend has a definition
but never an instance row (the §1 lifecycle point). The real work is reconciling the four scattered *definition* sites
(the `ProviderType` enum, template `base_url`/`preferred_provider`, `BackendDependency`, and the auth map
`TEMPLATE_ENV_VARS` + `credentials_for_template()`) into that one catalog -- e.g. a template names `source: openrouter`
instead of carrying an inline base_url. If "remote backend" is bolted on without absorbing those, the result is a fifth
overlapping concept and *more* surface, not less.

### 5. Telemetry spine: backend id as the canonical *source* key

Once backends are first-class, the **downstream** telemetry plane keys on `backend_id` as its canonical
**source identity**. This card owns that *key*; it does **not** decide how many planes exist -- the plane
**structure** (whether cost / audit / usage / provider-trace collapse, plus a new upstream outcome plane) is owned by
`upstream_downstream_ledgers` under the `telemetry_architecture` epic. Here we only make `backend_id` the source key
downstream records attribute to.

- **provider-trace** is the first migration target: replace `provider_name == "openrouter"` and the
  `~/.forge/providers/openrouter/traces/` path with a backend-id gate/layout. The generalization the observability card
  deferred (`selected_provider`-based broadening) becomes "this backend, and gateway backends expose their selected
  upstream" -- a clean axis rather than a hardcoded string.
- **downstream cost/metrics** attribution gains a stable source identity beyond `proxy_id`. The *upstream* outcome plane
  is session-keyed, not backend-keyed (one operation spans many backends), so `backend_id` is a downstream key, not a
  universal one.
- **Defer plane count to `upstream_downstream_ledgers`.** That card collapses cost + audit + provider-trace into one
  *downstream* plane (keyed on `backend_id`) and adds a first-class *upstream* outcome plane. This card supplies the key;
  it must **not** assert the four planes persist. See the `telemetry_architecture` epic for the shared contract.

## Relationship to other cards

- **`openrouter_observability`** (in `doing/`): provider-trace is the first consumer. Sequence this card **after** it.
  **Reorientation decided 2026-06-16: signpost-only.** The observability card ships its Phases 4-5 as scoped; the two
  hardcoded model-source identity sites (`provider_trace_logger.py` -- the `provider_name == "openrouter"` gate and the
  `_traces_dir()` path) carry forward-reference comments naming this card as the migration owner. No code was
  pre-refactored: the migration is a deliberate clean break owned here, not a speculative seam built on a sample size of
  one. Phase 4's read CLI stays provider-neutral (`forge provider trace ...`), so naming needs no migration.
- **`proxy_log_hygiene`**, **`openrouter_remote_reconciliation`**: both also key on provider/source identity and would
  consume a canonical backend id.
- **`upstream_downstream_ledgers`** + the **`telemetry_architecture`** epic (on the `supervisor_statusline_health`
  branch): the orthogonal **plane-structure** axis to this card's **source-identity** axis. Composable (collapse-to-two
  *and* key downstream on `backend_id`) and both edit `core/usage/emit.py`, so §5 owns only the `backend_id` key and
  defers plane count to that card. The epic holds the shared contract (canonical there; cross-branch until both merge to
  `main`; referenced by slug, not a relative link, since the epic is not in this branch's board).

## Open questions

- **Naming.** Promote "backend" to the supertype (symmetric, matches the user's intent; cf. Terraform/DB "backends"), or
  introduce "model source" / "endpoint" as the supertype and keep "backend" = local? Promotion is cleaner *iff* the
  consolidation (section 4) is real.
- **Remote identity unit.** Local id is `litellm-<port>` (port is meaningful). Remote has no port you own -- is the id
  the provider/credential name (`openrouter`)? If so, is a remote backend just the credential re-badged, or does it add
  real structure (endpoint + health + used-by) worth a distinct concept? Where is the line vs the `Credential` registry?
- **Direct Anthropic.** `ProviderType` has `anthropic` (passthrough). Does direct Anthropic become a remote backend too,
  or stay a proxy wire-shape detail?
- **Proxy -> backend reference.** How do templates reference backends -- migrate the six `*-local` `backend_dependency`
  blocks and the `openrouter-*` inline `base_url` to a `source: <backend-id>` reference? What is the one source of truth?
- **Remote health semantics.** Reachable vs authed vs rate-limited -- how much to probe, and at what cost/latency, given
  status surfaces poll frequently?
- **`ProviderType` fate.** Does the enum collapse into `backend.kind` + the wire-client detail, or stay as the
  per-request client identity beneath the backend axis?

## Risks

- **Large cross-cutting refactor.** Touches proxy, templates, credentials, the `ProviderType` enum, and the telemetry
  planes. Spike first (enumerate every source-identity site; design the supertype) before committing.
- **Vocabulary churn.** Redefining "backend" to include remote ripples through docs, tests, and mental models. A
  research-preview clean break is allowed (no compat shims, coding-standards §5), but the blast radius is real.
- **Fifth-concept trap.** Without the consolidation mandate, this adds surface instead of removing it.
- **Catalog vs instance conflation.** The static model-source catalog must stay separate from the runtime
  `BackendRegistry` (`~/.forge/backends/index.json`, PID/port/status). A remote backend has a catalog definition but no
  instance row; mixing static remote definitions into the PID-keyed registry would break its pruning/health semantics.
- **Lifecycle confusion.** Users may expect `forge backend start openrouter` to do something; the unified-noun/divergent-verbs
  model must be obvious in help and errors.
- **Over-promising auth.** The auth-resolution complexity is intrinsic. Frame this as transparency, not simplification.
- **Sequencing collision.** Doing this while `openrouter_observability` is in flight (it keys on `provider_name`) risks
  churn; the observability card should ship first.

## Acceptance sketch

- **Unified listing**: `forge backend list` shows local LiteLLM instances and remote sources (OpenRouter, remote
  LiteLLM) in one view with `kind`, endpoint, credential, and status.
- **No remote lifecycle**: a remote backend exposes `show`/`test-auth` but not `start`/`stop`; the LSP split lives in the
  type system (no remote adapter implements process start/stop).
- **Single source of truth**: templates reference a backend by id; the six `*-local` `backend_dependency` blocks and the
  `openrouter-*` templates resolve to **model-source catalog** entries (the static definition layer, distinct from the
  runtime `BackendRegistry` instance store), not inline base_urls.
- **Auth provenance**: one view shows each backend's required credential, resolution source (`env` / `credentials.yaml`
  / `omitted`), and reachability -- no secret ever printed.
- **Telemetry keys on backend id**: provider-trace's `provider_name == "openrouter"` gate is gone; a trace record's
  source identity is a backend id, and the plane covers any configured backend.
- **Clean break documented**: removed/renamed CLI surfaces fail with the framework's native error; the changelog names
  the replacements.
