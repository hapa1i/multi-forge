# Forge Architecture Diagrams

Visual representations of the Forge unified architecture.

---

## 1. Core Architecture Overview

```mermaid
flowchart TB
    User["User / automation"] --> CLI["forge CLI<br/>(launcher + operator surface)"]

    subgraph RuntimeLayer["Runtime layer"]
        Claude["Claude Code<br/>(default runtime)"]
        Codex["Codex CLI<br/>(alternate runtime)"]
    end

    CLI -->|"starts / resumes"| Claude
    CLI -->|"starts / resumes"| Codex

    Claude -->|"ANTHROPIC_BASE_URL"| Proxy["Forge Proxy<br/>(routing, audit, cost evidence)"]
    Claude -->|"hook events"| Hooks["Forge Hooks<br/>(confirmed facts + artifacts)"]
    Codex -->|"hook events / receipts"| Hooks
    Codex -->|"native-direct by default"| OpenAI["OpenAI Responses API"]

    CLI --> Ops["Session / proxy / policy ops"]
    Ops --> State["Forge State<br/>(sessions, proxy registry, runtime config)"]

    Hooks --> Artifacts["Artifacts + transfer memory<br/>(plans, transcripts, prev_sessions)"]
    Hooks --> Queue["Work Queue"]
    Queue --> Workers["Deferred workers<br/>(memory writer + search indexer)"]

    Proxy --> Providers["Model providers<br/>(Anthropic, LiteLLM, OpenRouter)"]
    Proxy --> Telemetry["Telemetry<br/>(downstream, upstream, caps)"]
    Hooks --> Telemetry
    Workers --> Usage["Usage attribution<br/>(usage/events)"]

    Status["Status line / activity views"] --> State
    Status --> Telemetry
    Status --> Usage
    Status --> Proxy

    classDef runtime fill:#eceff1,stroke:#78909c
    classDef state fill:#c8e6c9,stroke:#2e7d32
    classDef artifacts fill:#d1c4e9,stroke:#5e35b1
    classDef telemetry fill:#b2dfdb,stroke:#00796b
    classDef proxy fill:#bbdefb,stroke:#1565c0
    classDef external fill:#fff3e0,stroke:#ef6c00

    class Claude,Codex runtime
    class State state
    class Artifacts artifacts
    class Telemetry,Usage telemetry
    class Proxy proxy
    class OpenAI,Providers external
```

Color note: white nodes are Forge control-plane components; blue is the proxy/model-traffic boundary; green, purple, and
teal are durable state/artifact/telemetry stores; orange is external model infrastructure.

**Runtime asymmetry:** Claude Code routes model traffic through the Forge proxy (`ANTHROPIC_BASE_URL`), so Forge sees
its usage on the wire. Codex runs `codex exec` native-direct to OpenAI's Responses API by default; Forge governs it at
the session and hook seams, not the wire (`--proxy` is rejected unless that proxy already serves Responses on its
Codex-facing endpoint — Forge adds no `/v1/responses` route). Both runtimes share the same hooks, state, and artifact
paths.

**Deployment note:** Sidecar mode is omitted from this overview because it packages proxy/runtime lifecycle without
changing the data-flow boundaries shown here.

**Telemetry planes:** model traffic and operation outcomes land in two planes joined to sessions by run-tree identity —
`telemetry/downstream/` (per-attempt model-call evidence + spend caps, written by the proxy and direct runtime emitters)
and `telemetry/upstream/` (per-operation policy/boundary outcomes). The `usage/events/` attribution ledger is written by
every Forge subprocess consumer (supervisor, memory writer, workflow verbs, tagger) and read by the status line
(`forge +$Y`) and `forge telemetry activity`.

---

## 2. Session vs Proxy Separation

This is the fundamental architectural principle: proxy requests lack stable session IDs, so routing must be
proxy-scoped.

```mermaid
flowchart LR
    subgraph SessionScope["Session Scope<br/>(user intent & artifacts)"]
        Intent["intent<br/>- forge_root / launch<br/>- policy bundles / verification<br/>- memory behavior<br/>- consumer lanes (requested)"]
        Overrides["overrides<br/>(live toggles)"]
        Confirmed["confirmed<br/>- artifacts<br/>- started_with_proxy<br/>- consumer lanes (frozen)<br/>- runtime facts"]
    end

    subgraph ProxyScope["Proxy Scope<br/>(routing & defaults)"]
        Identity["proxy.yaml identity<br/>- template + template_digest<br/>- proxy_endpoint / upstream_base_url"]
        Routing["routing<br/>- default_tier<br/>- tier → model mapping"]
        Defaults["proxy-owned defaults<br/>- tier_overrides<br/>- provider_settings<br/>- prompt_caching"]
    end

    subgraph ProxyRequest["Proxy Request"]
        BaseURL["ANTHROPIC_BASE_URL<br/>(only reliable key)"]
    end

    ProxyRequest -->|identifies| ProxyScope
    SessionScope -.->|references only| ProxyScope

    style ProxyScope fill:#e1f5fe
    style SessionScope fill:#fff3e0
```

---

## 3. Configuration Model

Two independent config tracks — proxy routing and runtime preferences never mix.

```mermaid
flowchart LR
    subgraph ProxyTrack["Proxy Config Track"]
        direction TB
        T1["Template YAML<br/>defaults/templates/*.yaml<br/>(creation time only)"]
        T2["Proxy file<br/>~/.forge/proxies/&lt;id&gt;/proxy.yaml<br/>(self-contained runtime config)"]
        T3["Secret env vars<br/>*_API_KEY, *_AUTH_URL<br/>(runtime only; not persisted)"]
        T1 -->|copied on create| T2
    end

    subgraph RuntimeTrack["Runtime Config (RuntimeConfig)"]
        direction TB
        R1["Built-in defaults<br/>(dataclass fields)"]
        R2["~/.forge/config.yaml<br/>(optional, fail-open)"]
        R3["Env overrides<br/>FORGE_DEBUG"]
        R1 -->|overridden by| R2
        R2 -->|overridden by| R3
    end

    ProxyCfg["Effective proxy config<br/>(proxy.yaml + secrets)"]
    RuntimeCfg["Effective runtime config"]

    T2 --> ProxyCfg
    T3 -->|read at runtime| ProxyCfg
    R1 --> RuntimeCfg
    R2 --> RuntimeCfg
    R3 --> RuntimeCfg

    ProxyTrack -.->|"separate ownership"| RuntimeTrack

    Proxy["Proxy Server"] --> ProxyCfg
    CLI["CLI / Hooks / Status Line"] --> RuntimeCfg

    style ProxyTrack fill:#e1f5fe
    style RuntimeTrack fill:#fff3e0
```

**Proxy track**: `proxy.yaml` is self-contained at runtime; templates are copied only when the proxy is created, and
secret env vars are read without being written back into the file. **Runtime track**: `RuntimeConfig` resolves built-in
defaults -> `~/.forge/config.yaml` -> env overrides. Separate modules prevent runtime preferences from leaking into
proxy routing.

---

## 4. Ownership Boundaries

```mermaid
flowchart TB
    subgraph Writers["Component Ownership"]
        subgraph ForgeSession["Session + Policy CLI write:"]
            W1["~/.forge/sessions/active.json"]
            W2["~/.forge/sessions/index.json"]
            W3["intent + overrides in session manifest"]
        end

        subgraph ForgeHooks["Lifecycle hooks write:"]
            W4["confirmed.* in session manifest"]
            W4b[".forge/artifacts/*"]
            W4c["~/.forge/pending-work/*.json"]
        end

        subgraph DirectHooks["UserPromptSubmit direct commands write:"]
            W5["session overrides<br/>(e.g. policy.enabled,<br/>verification.bypass)"]
        end

        subgraph Deferred["Deferred workers write:"]
            W6[".forge/search-index/*"]
            W6b["designated project docs<br/>(memory writer)"]
        end

        subgraph ForgeProxy["Proxy orchestrator writes:"]
            W7["~/.forge/proxies/index.json"]
            W8["~/.forge/proxies/&lt;id&gt;/proxy.yaml"]
        end

        subgraph ForgeCLI["Installer/config CLI write:"]
            W9["~/.forge/config.yaml (runtime config)"]
            W10["~/.forge/installed.json"]
            W11["extension files + merged settings"]
        end

        subgraph Telemetry["Telemetry + usage emitters write:"]
            W12["~/.forge/telemetry/downstream/*<br/>(proxy + runtime: model-call evidence)"]
            W13["~/.forge/telemetry/upstream/*<br/>(operation / policy boundaries)"]
            W14["~/.forge/telemetry/{caps,audit_state}/*<br/>(proxy spend + drift baselines)"]
            W15["~/.forge/usage/events/*<br/>(attribution ledger)"]
        end
    end

    W4c --> W6
    W4c --> W6b

    style ForgeSession fill:#c8e6c9
    style ForgeHooks fill:#fff9c4
    style DirectHooks fill:#fff3e0
    style Deferred fill:#d1c4e9
    style ForgeProxy fill:#bbdefb
    style ForgeCLI fill:#f8bbd9
    style Telemetry fill:#b2dfdb
```

**Policy split:** `forge policy enable/disable` mutates `intent.policy`; the policy-check hook writes
`confirmed.policy`; and `%policy ...` direct commands mutate session overrides.

**Telemetry split (by direction, not feature):** the proxy owns `telemetry/downstream/` (per-attempt model-call
evidence) plus cap/drift state; operation and policy boundaries own `telemetry/upstream/` (per-operation outcomes);
Forge subprocess consumers append the `usage/events/` attribution ledger. Downstream is session-blind and joins to a
session only through run-tree identity.

---

## 5. Hook Deployment Model

```mermaid
flowchart LR
    subgraph Installation["Install Surface"]
        Installer["forge extension enable<br/>or forge hook enable"]
        Settings["Claude settings file<br/>(settings.json / settings.local.json)"]
        CodexCfg["Codex config.toml managed block<br/>(user: $CODEX_HOME; project/local: &lt;project&gt;/.codex)"]
        Installer -->|writes hook config| Settings
        Installer -->|appends managed block| CodexCfg
    end

    subgraph Triggers["Runtime triggers"]
        ClaudeEvt["Claude Code event<br/>(SessionStart, PreToolUse, Stop, ...)"]
        CodexEvt["Codex event<br/>(SessionStart, PreToolUse)"]
        Enroll(["one-time trust ceremony<br/>(registration alone is inert)"])
    end

    subgraph Execution["Forge executes"]
        CLI2["forge hook &lt;name&gt;"]
        Handler["Python handler<br/>(in forge package)"]
        Outputs["confirmed.* + artifacts<br/>+ pending-work markers"]
    end

    Settings -->|configures| ClaudeEvt
    CodexCfg -->|registers| CodexEvt
    Enroll -.->|enables firing| CodexEvt
    ClaudeEvt -->|invokes| CLI2
    CodexEvt -->|"codex-session-start /<br/>codex-policy-check"| CLI2
    CLI2 -->|runs| Handler
    Handler -->|produces| Outputs
```

Claude hooks fire as soon as the settings file is written. Codex hooks are **enrollment-gated**: the installer appends a
marker-delimited block to the Codex `config.toml` its install scope maps to, registering two hooks
(`codex-session-start`, `codex-policy-check`), but they fire only after the user completes Codex's one-time interactive
trust ceremony — registration alone is inert. Both runtimes converge on the same `forge hook` handlers.

---

## 6. Proxy Routing Flow

```mermaid
sequenceDiagram
    participant CC as Claude Code
    participant Proxy as Forge Proxy
    participant Config as proxy.yaml / loader
    participant LLM as LLM Provider

    CC->>Proxy: POST /v1/messages<br/>(via ANTHROPIC_BASE_URL)

    Note over Proxy: Proxy identity is implied by<br/>base URL / port.<br/>Registry is not consulted per request.

    Proxy->>Config: Load effective proxy config<br/>(proxy.yaml + secret envs)
    Config-->>Proxy: default_tier, tiers,<br/>tier_overrides, provider_settings

    Note over Proxy: Precedence:<br/>1. request explicit model/tier<br/>2. proxy.default_tier

    Proxy->>Proxy: Resolve tier → backend model
    Proxy->>Proxy: Apply proxy-owned defaults<br/>(tier_overrides, prompt_caching, provider settings)

    Proxy->>LLM: Forward request<br/>(converted format)
    LLM-->>Proxy: Response

    Proxy-->>CC: Response<br/>(Anthropic format)
```

---

## 7. Multi-Proxy Workflow

The core use case motivating Session/Proxy separation:

```mermaid
flowchart TB
    subgraph Planning["Session A: Planner"]
        PA["Template / proxy<br/>litellm-openai"]
        Plan["Approved plan + artifacts"]
    end

    subgraph Execution["Session B: Executor"]
        PB["Proxy relaunch<br/>litellm-anthropic"]
        Code["Implementation"]
    end

    subgraph Review["Session C: Reviewer"]
        PC["Proxy relaunch<br/>litellm-gemini-local"]
        Feedback["Independent review"]
    end

    Planning -->|fork / resume transfer| Execution
    Planning -->|plan artifacts| Review
    Execution -->|changes| Review
    Review -->|feedback| Execution

    subgraph SharedState["Shared project state"]
        Repo["Forge projects in worktrees<br/>(code + branch isolation)"]
        Artifacts["&lt;forge_root&gt;/.forge/artifacts/<br/>(plans, transcripts)"]
        Search["&lt;forge_root&gt;/.forge/search-index/"]
    end

    Planning --> SharedState
    Execution --> SharedState
    Review --> SharedState

    style Planning fill:#fff3e0
    style Execution fill:#e8f5e9
    style Review fill:#e3f2fd
```

When a child session must target a specific running proxy instance, switch to that session and use
`forge claude start --proxy <proxy_id>`.

---

## 8. Implementation Status

```mermaid
flowchart LR
    subgraph Complete["Implemented capability groups"]
        P1["Foundation<br/>(installer, tracking, extensions)"]
        P2["Sessions + Proxies<br/>(worktrees, sidecar, full proxy files)"]
        P3["Auth + Credentials"]
        P4["Hooks + Policy<br/>(direct commands, verification, workflow policy)"]
        P5["Deferred work<br/>(stop pipeline, queue, search, memory writer)"]
        P6["Workflow runners<br/>(review, panel, analyze, debate)"]
        P7["Status line + runtime config"]
        P8["Codex runtime<br/>(alternate frontend: seam, enroll, sessions, hooks, transfer)"]
    end

    subgraph Dropped["Not consolidated into Forge"]
        D1["Zen MCP stays external"]
        D2["Full containerized sessions<br/>(sidecar + native sandbox cover current needs)"]
    end

    style Complete fill:#c8e6c9
    style Dropped fill:#ffcdd2
```

---

## 9. Workflow Runner Architecture

Runner-backed workflows currently have two entry surfaces: CLI commands, and skills that compose prompts/resources and
then call those CLIs.

```mermaid
flowchart TB
    subgraph Layer3["Layer 3: Entry Points"]
        RunPanel["forge workflow panel"]
        RunAnalyze["forge workflow analyze"]
        RunDebate["forge workflow debate"]
        RunConsensus["forge workflow consensus"]
        SkillPanel["/forge:panel"]
        SkillAnalyze["/forge:analyze"]
        SkillDebate["/forge:debate"]
        SkillConsensus["/forge:consensus"]
    end

    subgraph Layer2["Layer 2: Prompt / Resource Inputs"]
        Prompt["prompt / target"]
        ThinkRes["thinkdeep.md"]
        DocReviewRes["docreview.md / codereview.md"]
        DebateTemplate["debate evaluation template<br/>(has {stance_prompt})"]
        SynthRes["panel/synthesis.md<br/>(post-processing guidance)"]
    end

    subgraph Layer1["Layer 1: Abstract Runners"]
        FanOut["Fan-out Runner<br/>run_multi_review()<br/>N workers in parallel"]
        Adversarial["Adversarial Runner<br/>run_adversarial()<br/>stance injection + blinding"]
    end

    RunPanel -->|target+framework| FanOut
    RunAnalyze --> ThinkRes
    RunAnalyze -->|N=1 worker| FanOut
    RunPanel --> DocReviewRes
    RunDebate --> DebateTemplate
    RunDebate --> Adversarial
    RunConsensus -->|two-round convergence| FanOut

    Prompt --> RunPanel
    SkillPanel -->|pass target, call CLI| RunPanel
    SkillPanel --> SynthRes
    SkillAnalyze -->|pass topic, call CLI| RunAnalyze
    SkillDebate -->|pass proposal, call CLI| RunDebate
    SkillConsensus -->|pass subject, call CLI| RunConsensus

    Adversarial -->|delegates to| FanOut

    style Layer1 fill:#e3f2fd
    style Layer2 fill:#fff3e0
    style Layer3 fill:#e8f5e9
```

**Key relationships:**

- `forge workflow analyze` is a specialized fan-out with one worker and a bundled resource
- `forge workflow debate` layers stance injection and blinding on top of fan-out
- `forge workflow consensus` runs two fan-out rounds (evaluate, then reconcile)
- `/forge:panel`, `/forge:analyze`, `/forge:debate`, and `/forge:consensus` prepare prompts/resources and then call the
  corresponding CLI entry point
- `/forge:review` and `/forge:review-docs` are local review skills; their optional multi-model path uses
  `forge workflow panel`

---

## 10. Project Identity Hierarchy

Four scoping levels that determine where session state, artifacts, and search indexes live. See
[design.md §3: Project identity model](design.md#project-identity-model) for normative rules.

```mermaid
flowchart TB
    subgraph LogicalRepo["project_root (Logical Repo)"]
        direction TB
        Git[".git (shared identity)<br/>get_main_repo_root()"]

        subgraph CheckoutA["checkout_root A (main checkout)"]
            direction TB
            subgraph ForgeA["forge_root A (.claude/ + .forge/)"]
                Sessions_A[".forge/sessions/"]
                Artifacts_A[".forge/artifacts/"]
                Search_A[".forge/search-index/"]
            end
        end

        subgraph CheckoutB["checkout_root B (git worktree)"]
            direction TB
            subgraph ForgeB["forge_root B (.claude/ + .forge/)"]
                Sessions_B[".forge/sessions/"]
                Artifacts_B[".forge/artifacts/"]
                Search_B[".forge/search-index/"]
            end
        end
    end

    subgraph GlobalState["Global (~/.forge/)"]
        Index["sessions/index.json<br/>(project_root, checkout_root,<br/>forge_root, relative_path)"]
        Proxies["proxies/index.json"]
    end

    ForgeA -.->|"fork --into<br/>(preserves relative_path)"| ForgeB
    ForgeA -.->|"cross-project resume<br/>(reads parent artifacts)"| ForgeB
    Index -->|"session list --scope workspace<br/>(filters by project_root)"| LogicalRepo

    style LogicalRepo fill:#fafafa,stroke:#999
    style CheckoutA fill:#e3f2fd
    style CheckoutB fill:#e3f2fd
    style ForgeA fill:#e8f5e9
    style ForgeB fill:#e8f5e9
    style GlobalState fill:#fff3e0
```

**Key relationships:**

- Each Forge project (`forge_root`) is self-contained: sessions, artifacts, and search live under its `.forge/`
- Cross-project operations (fork, resume) are allowed within the same logical repo (`project_root`)
- `session list` defaults to workspace scope (shows sessions across all worktrees and Forge projects in the logical
  repo)
- `relative_path` = `forge_root` relative to `checkout_root`; preserved when forking `--into` another worktree
