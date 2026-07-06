"""Dataclasses for Forge Session module.

All timestamps are stored as ISO8601 strings for trivial JSON roundtripping.
Use forge.core.state.now_iso() to generate timestamps and parse_iso()
for runtime conversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forge.core.effort import validate_claude_effort
from forge.core.state import now_iso
from forge.policy.team.config import TeamSupervisorConfig
from forge.policy.types import FailMode

from .config import LAUNCH_MODE_HOST, LAUNCH_MODE_SIDECAR

# Schema version for session state files.
SCHEMA_VERSION = 1
INDEX_VERSION = 1

# Mirror of forge.core.llm.types.ReasoningEffort. Kept inline so this foundational
# module's import chain stays free of the heavy core.llm package (litellm clients);
# tests/src/core/test_effort.py is the drift guard that asserts equality.
_CHECKER_EFFORT_LEVELS = ("none", "low", "medium", "high", "xhigh")


# --- Worktree metadata (embedded in SessionState) ---


@dataclass
class Worktree:
    """Git worktree metadata.

    ``path`` is the checkout root (git ``--show-toplevel``), not the Forge
    project root.  The Forge project root is stored separately as
    ``SessionState.forge_root`` and ``SessionIndexEntry.forge_root``.
    """

    path: str  # Absolute path to checkout root (git --show-toplevel)
    branch: str  # Git branch name (may contain slashes)
    is_worktree: bool = False  # True only if this is a git worktree (not main repo)
    owns_worktree: bool = True  # False for --into (session is a guest, not the creator)


# --- Intent section - what Forge requested ---


@dataclass
class ProxyIntent:
    """Proxy configuration intent. Both fields are required."""

    template: str  # e.g., "litellm-gemini"
    base_url: str  # e.g., "http://localhost:8084"


@dataclass
class SystemPromptIntent:
    """System prompt configuration intent."""

    mode: str = "append"  # "append" or "replace"
    file: str | None = None  # Path to custom system prompt file


@dataclass
class SidecarLaunchIntent:
    """Persisted sidecar launch preferences for reproducible relaunches."""

    mounts: list[str] = field(default_factory=list)  # Raw CLI mount specs: host:container[:ro|rw]
    image: str | None = None  # Optional sidecar image override


@dataclass
class LaunchIntent:
    """How Forge should relaunch this session."""

    mode: str = LAUNCH_MODE_HOST  # "host" or "sidecar"
    sidecar: SidecarLaunchIntent | None = None
    direct_model: str | None = None  # Claude Code env-ready direct model pin (e.g. claude-opus-4-8[1m])
    # Runtime registry id ("claude_code" | "codex") driving launcher dispatch. Immutable
    # launch identity: `forge session set launch.runtime` is rejected (overrides.py) and
    # dispatch reads this raw intent field, never effective state.
    runtime: str = "claude_code"


@dataclass
class MemoryWriterConfig:
    """Memory writer configuration for automatic memory doc updates.

    The memory writer runs after session stop to update designated
    project memory documents (e.g., project-state.md) using ``claude -p``.

    Fields:
        enabled: Whether the memory writer should run on session stop.
        mode: "augment" (add missing info) or "review-only" (report only, no edits).
        proxy: Optional proxy (proxy_id or template name) to route the writer's
               LLM calls through. If None, inherits the session's confirmed proxy.
        direct: When True, force direct Anthropic routing regardless of session proxy.
        min_turns: Minimum conversation turns before triggering the writer.
                   Sessions below this threshold are skipped (too short to be useful).
    """

    enabled: bool = False
    mode: str = "augment"  # "augment" | "review-only"
    proxy: str | None = None
    direct: bool = False
    min_turns: int = 5
    effort: str | None = None  # `claude --effort` level for the writer's claude -p run; None = tier default

    def __post_init__(self) -> None:
        validate_claude_effort(self.effort)


@dataclass
class DesignatedDoc:
    """Runtime type for a doc the memory writer should update.

    Not persisted in session manifests. Produced by ``scan_passported_docs()``
    and consumed by ``run_memory_writer()``.

    Fields:
        path: Worktree-relative path (e.g., "docs/checklist.md").
              Must NOT be absolute. Resolved against worktree_path at runtime.
        strategy: Built-in augmentation strategy (see MemoryStrategy enum).
        shadows: When set, switches to shadow/propose mode (Mode 2).
                 Path to the official document this doc proposes changes for.
    """

    path: str
    strategy: str = "generic"
    shadows: str | None = None


@dataclass
class MemoryIntent:
    """Memory/context injection intent."""

    auto_recall: bool = False
    tags: list[str] = field(default_factory=list)
    strategy: str = "summary"  # "summary", "full", or "off"
    max_chars: int = 6000
    generated_file: str | None = None  # e.g., ".claude/forge.context.generated.md"
    auto_update: MemoryWriterConfig | None = None


@dataclass
class SupervisorConfig:
    """Semantic supervisor configuration.

    The supervisor is an LLM session (typically forked from the planner) that
    validates executor actions against the approved plan.
    """

    resume_id: str | None = None  # Claude session UUID, or a Forge session name resolved to a UUID at runtime
    proxy: str | None = None  # Optional: proxy_id or template name for base_url lookup
    direct: bool = False  # When True, force direct Anthropic routing
    base_url: str | None = None  # Optional: explicit base_url override
    forge_root: str | None = None  # Scope for name-based lookups (set at wiring time)
    timeout_seconds: int = 45  # Max time to wait for supervisor response (15s margin within 60s hook timeout)
    throttle_seconds: int = 30  # Min time between supervisor calls (for caching)
    fork_session: bool = True  # Fork supervisor session to avoid polluting planner context
    suspended: bool = False  # True = supervision paused, config preserved
    plan_override_path: str | None = None  # Absolute path to plan file that supersedes session context
    cascade: bool = False  # Opt-in tier-1 plan check before the frontier supervisor
    checker_model: str | None = None  # Tier-1 model (prefixed id); None = provider-specific default
    checker_provider: str | None = None  # Tier-1 provider override (openrouter/litellm_local/litellm_remote)
    checker_budget_tokens: int | None = None  # Approx total token budget for the tier-1 checker prompt
    checker_effort: str | None = (
        None  # Tier-1 checker reasoning effort (core.llm: none/low/medium/high/xhigh); None=model default
    )
    supervisor_effort: str | None = (
        None  # Frontier `claude --effort` level (low/medium/high/xhigh/max); None=tier default
    )
    # Shadow sampling (audit the cascade's false-aligned rate): run the frontier supervisor on a random sample of
    # tier-1 allows post-hoc, verdict recorded but never enforced. 0.0 = off (default).
    shadow_sample_rate: float = 0.0  # [0,1] probability of shadowing an uncached tier-1 allow
    shadow_max_per_session: int = 10  # Hard cap on shadow candidates persisted per session (bounds frontier spend)
    shadow_seed: str | None = None  # Optional salt for deterministic sampling (tests); session_name supplies entropy

    def __post_init__(self) -> None:
        # Range validation lives here (the broadest shared construction path) rather than on the CLI surface: dacite
        # runs __post_init__ on every manifest read / session set / start / fork, and compute_effective_intent's
        # strict branch auto-wraps this ValueError into the typed InvalidOverrideValueError.
        if not 0.0 <= self.shadow_sample_rate <= 1.0:
            raise ValueError(f"shadow_sample_rate must be in [0.0, 1.0], got {self.shadow_sample_rate}")
        if self.shadow_max_per_session < 1:
            raise ValueError(f"shadow_max_per_session must be >= 1, got {self.shadow_max_per_session}")
        # Frontier supervisor runs via `claude -p --effort`; tier-1 checker is a core.llm call.
        validate_claude_effort(self.supervisor_effort)
        if self.checker_effort is not None and self.checker_effort not in _CHECKER_EFFORT_LEVELS:
            raise ValueError(
                f"checker_effort must be one of {', '.join(_CHECKER_EFFORT_LEVELS)}, got {self.checker_effort!r}"
            )


@dataclass
class PolicyIntent:
    """Policy configuration for the session.

    Policies are enforced at PreToolUse:Write/Edit boundaries. They can be
    deterministic (fast local checks) or semantic (LLM-based supervisor).
    """

    enabled: bool = False
    fail_mode: FailMode = "open"  # "open" = allow on error, "closed" = deny on error
    bundles: list[str] = field(default_factory=list)  # e.g., ["tdd", "coding_standards"]
    bundle_config: dict[str, dict[str, Any]] = field(default_factory=dict)  # per-bundle options
    supervisor: SupervisorConfig | None = None
    team_supervisor: TeamSupervisorConfig | None = None


@dataclass
class VerificationConfig:
    """Verification policy configuration (Ralph-Wiggum pattern).

    Verification runs at the Stop boundary and can block exit until
    the assistant produces a completion signal.

    Fields:
        type: Verification type.
              - "completion_promise": Check for promise string in last assistant message.
              - "test_suite": Run `uv run pytest` and check exit code.
        promise: (completion_promise only) The exact string that must appear on a
                 standalone line in the last assistant message.
        max_iterations: Maximum number of blocked Stop attempts before auto-bypass.
        max_minutes: Maximum minutes from first block before auto-bypass (None = no limit).
        bypass: If True, skip verification entirely (escape hatch).
        on_incomplete: What to do when verification fails:
                       - "block": sys.exit(2) with stderr guidance
                       - "warn": print warning, allow Stop
                       - "allow": skip verification entirely
        re_inject_prompt: Custom message to print to stderr when blocking.
                          If None, a default message is used.
        test_timeout_seconds: (test_suite only) Timeout for pytest command in seconds.
    """

    type: str = "completion_promise"  # "completion_promise" | "test_suite"
    promise: str | None = None
    max_iterations: int = 50
    max_minutes: int | None = None
    bypass: bool = False
    on_incomplete: str = "block"  # "block", "warn", "allow"
    re_inject_prompt: str | None = None
    test_timeout_seconds: int = 300  # 5 minutes default (test_suite only)


# --- Consumer lanes (epic consumer_lanes, T1b) ---


@dataclass(frozen=True)
class LaneRecord:
    """Persisted ``(runtime, backend, model)`` lane placement -- an inert manifest DTO.

    Storage twin of ``forge.core.lanes.Lane``: identical fields, but deliberately
    **no** catalog/runtime validation, so a manifest read never depends on today's
    ``RUNTIMES`` / ``ModelSource`` catalogs (a renamed backend leaves a stale
    binding, not corrupt state). The binding write path converts ``LaneRecord ->
    Lane`` once to validate; dispatch/status revalidate on demand. Field parity
    with ``Lane`` is drift-guarded (``tests/src/core/test_lanes.py``).
    """

    runtime_id: str
    backend_id: str
    model: str

    def __post_init__(self) -> None:
        for name, value in (
            ("runtime_id", self.runtime_id),
            ("backend_id", self.backend_id),
            ("model", self.model),
        ):
            # Enforce the `str` annotation at runtime, not just truthiness: Slice 2
            # setters build LaneRecord directly (bypassing dacite's type check), and
            # a non-str like 123 is truthy.
            if not isinstance(value, str) or not value:
                raise ValueError(f"LaneRecord requires a non-empty string {name}")


@dataclass
class ConsumerLaneIntent:
    """Requested per-consumer lane overrides (session-owned intent).

    Named field per consumer (never a ``dict``) so strict deserialization and
    override-path validation stay per-field. T1b wired the supervisor; T0 added the
    three sibling consumers for subscription billing.
    """

    supervisor: LaneRecord | None = None
    memory_writer: LaneRecord | None = None
    shadow_curation: LaneRecord | None = None
    team_supervisor: LaneRecord | None = None


@dataclass
class ConsumerLaneBinding:
    """A consumer's frozen, resolved lane -- written once at first dispatch.

    Inert record plus the anchor the "already bound" reject checks. A binding exists
    iff an *explicit* lane choice was frozen (the default lane never freezes), so
    ``source`` is currently always ``"intent"``; it stays a plain ``str`` per the
    fail-open ``*Confirmed`` style and as a forward slot for future provenance (T6).
    """

    lane: LaneRecord
    source: str
    resolved_at: str


@dataclass
class ConsumerLaneConfirmed:
    """Frozen per-consumer lane bindings (hook-written, write-once per consumer)."""

    supervisor: ConsumerLaneBinding | None = None
    memory_writer: ConsumerLaneBinding | None = None
    shadow_curation: ConsumerLaneBinding | None = None
    team_supervisor: ConsumerLaneBinding | None = None


@dataclass
class SessionIntent:
    """What Forge intends for this session.

    NOTE: Proxy-owned routing and LLM hyperparameters are intentionally excluded
    from the session schema. Sessions may express only session-owned intent.
    """

    agent: str = "claude-code"
    proxy: ProxyIntent | None = None
    subprocess_proxy: str | None = None  # proxy_id for routing subprocesses (supervisor, panel, etc.)
    launch: LaunchIntent | None = None
    system_prompt: SystemPromptIntent | None = None
    memory: MemoryIntent | None = None
    policy: PolicyIntent | None = None
    verification: VerificationConfig | None = None
    # Frozen-at-first-dispatch consumer-lane overrides (epic consumer_lanes, T1b).
    consumer_lanes: ConsumerLaneIntent | None = None


# --- Confirmed section - what Claude Code actually did (filled by hooks) ---


@dataclass
class PolicyConfirmed:
    """Hook-owned policy state persisted across hook invocations.

    Since hooks are short-lived processes, stateful policy data must be
    persisted to the session manifest between invocations.

    Fields:
        forge_version: Version for provenance tracking
        bundles: Active bundle names at last evaluation
        rules_active: Active rule IDs at last evaluation
        decisions: Log of recent policy decisions (bounded to MAX_DECISION_LOG)
        policy_states: Generic per-policy state dict keyed by policy_id
    """

    forge_version: str | None = None
    bundles: list[str] = field(default_factory=list)
    rules_active: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    policy_states: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class VerificationConfirmed:
    """Hook-owned verification state persisted across Stop invocations.

    Tracks runtime verification state for the Ralph-Wiggum feedback loop.

    Fields:
        started_at: ISO8601 timestamp of first blocked Stop (for max_minutes).
        iterations: Number of times Stop was blocked (not total Stop invocations).
        last_result: Outcome of last verification check:
                     - "passed": promise found, Stop allowed
                     - "failed": promise not found, Stop blocked
                     - "warned": promise not found, Stop allowed (on_incomplete=warn)
                     - "max_iterations": limit exceeded, auto-bypassed
                     - "max_minutes": time limit exceeded, auto-bypassed
                     - "bypassed": manually bypassed via %cancel-verification
                     - "error": verification check failed due to internal error
        last_error: Short description of last failure (for debugging).
    """

    started_at: str | None = None
    iterations: int = 0
    last_result: str | None = None
    last_error: str | None = None


@dataclass
class CompactionConfirmed:
    """Compaction tracking state persisted across hook invocations.

    Records compaction events and pre-compact transcript snapshots for
    session metadata, search indexing, and transcript lineage.
    PreCompact captures the full transcript before compaction; PostCompact
    records the completion timestamp.
    """

    compact_count: int = 0
    last_compact_at: str | None = None  # ISO8601, set by PostCompact
    last_compact_type: str | None = None  # "auto" | "manual" | "unknown"
    transcript_snapshots: list[dict[str, Any]] = field(default_factory=list)
    # Each entry: {captured_at, reason, source_path, snapshot_path, copied}


@dataclass
class SubagentConfirmed:
    """Subagent activity tracking persisted across hook invocations.

    Records subagent stop events for session observability and future
    policy enforcement. Currently observe-only (no blocking).
    """

    total_count: int = 0
    by_type: dict[str, int] = field(default_factory=dict)  # {"Explore": 2, "Bash": 1}
    last_agent_id: str | None = None
    last_agent_type: str | None = None
    last_stop_at: str | None = None  # ISO8601
    last_transcript_path: str | None = None  # Agent-specific transcript
    last_message_preview: str | None = None  # Truncated last_assistant_message (~200 chars)


@dataclass
class StartedWithProxy:
    """Proxy identity snapshot captured at session start.

    This is hook-owned runtime truth for UX/traceability only.
    The proxy remains the authoritative source of routing behavior.
    """

    base_url: str
    proxy_id: str | None = None
    template: str | None = None
    port: int | None = None


@dataclass
class Derivation:
    """Context derivation tracking for resumed or forked sessions.

    Records how this session was derived from its parent(s), enabling
    audit trails and context reconstruction. This is CLI-owned (written
    by `forge session resume` and `forge session fork`), not hook-owned.

    Fields:
        parent_session: Parent session name (same as SessionState.parent_session).
        parent_transcript: Repo-relative path to parent's transcript artifact.
        inherited_proxy: Template from parent's started_with_proxy (if any).
        resume_mode: "native" (--resume --fork-session), "native-relocate" (worktree fork that
            relocates the parent JSONL into the child CWD's encoded dir, then resumes), or
            "transfer" (assembled context). None is treated as transfer (no reader branches on a
            loaded parent's mode token). Authoritative field for how context was transferred.
        strategy: Context assembly strategy (minimal|structured|full|ai-curated|rewind).
            Historically set only when resume_mode is "transfer" (or None), with null for
            native resumes. "rewind" intentionally combines native-relocate history with a
            generated context file.
        depth: How many ancestors were traversed (1 = parent only).
        resumed_at: ISO8601 timestamp when resume was executed.
        lineage: Ancestry chain from parent to oldest ancestor traversed.
        context_file: Repo-relative path to generated context file.
        relocated_parent_session_id: For resume_mode "native-relocate" only -- the parent UUID
            whose transcript was copied into the child's encoded project dir. Lets cleanup remove
            that relocated copy (dir-scoped to the child) without touching the parent's original.
        dropped_turns: For strategy "rewind", how many tail turns were dropped from the relocated
            transcript prefix.
        rewind_relocated_session_id: For strategy "rewind", the fresh UUID used for the truncated
            relocated transcript copy. Distinct from relocated_parent_session_id because it is not
            the parent's UUID and is not a shared byte-for-byte native-relocate copy.
    """

    parent_session: str
    parent_transcript: str | None = None
    inherited_proxy: str | None = None
    resume_mode: str | None = None
    strategy: str | None = "structured"
    depth: int = 1
    resumed_at: str | None = None
    lineage: list[str] = field(default_factory=list)
    context_file: str | None = None
    relocated_parent_session_id: str | None = None  # Set only for resume_mode "native-relocate"
    dropped_turns: int | None = None
    rewind_relocated_session_id: str | None = None
    # Project identity fields for cross-project resume (see design.md §3)
    parent_forge_root: str | None = None  # Where to find parent artifacts
    parent_project_root: str | None = None  # Must match child's project_root


@dataclass
class LaunchConfirmed:
    """Immutable launch facts captured by the CLI when the interactive session starts.

    CLI-owned (like Derivation), written once at launch: how the session reached the
    model and whether an ANTHROPIC_API_KEY was made available to the child. Lets the
    status line describe route + auth honestly without inferring a payer from key
    presence. Plain ``str`` (not ``Literal``) to match the sibling *Confirmed style
    and stay fail-open under strict dacite reads.

    Fields:
        routing_mode: "direct" | "proxy" | "custom_base_url".
        proxy_id / base_url: route identity when proxied (None for direct).
        proxy_cost_baseline_micros: cumulative proxy-reported cost at launch.
        proxy_cost_baseline_started_at: proxy metrics process timestamp at launch.
        api_key_available_to_child: whether the child can see an ANTHROPIC_API_KEY.
        api_key_source: "env" | "credential_file" | "none" | "omitted_by_config".
    """

    routing_mode: str | None = None
    proxy_id: str | None = None
    base_url: str | None = None
    proxy_cost_baseline_micros: int | None = None
    proxy_cost_baseline_started_at: str | None = None
    api_key_available_to_child: bool = False
    api_key_source: str | None = None


@dataclass
class CodexConfirmed:
    """Codex runtime facts captured by the CLI (hook-free), refreshed per run.

    CLI-owned like ``LaunchConfirmed``: Codex hooks only fire from trust-enrolled
    homes (registry ``native_hooks="enrollment_gated"``), so the CLI records these
    from the ``codex exec --json`` stream and filesystem discovery instead.

    Fields:
        thread_id: the ``codex exec resume`` id, from the stream's ``thread.started``.
        rollout_path: absolute path to the matching ``$CODEX_HOME/sessions/.../
            rollout-*-<thread_id>.jsonl``, when discovered.
        rollout_source: how ``rollout_path`` was obtained: "discovered_by_thread_id"
            (filesystem glob) or "session_start_hook" (the hook payload's
            transcript_path, reported by codex itself); None when no rollout was found.
        auth_method / auth_source / billing_mode: the secret-free auth posture from
            ``CodexPreflight``. ``confirmed.launch`` stays None for Codex sessions
            (it describes the ANTHROPIC key posture of interactive Claude), so this
            is the manifest's only auth breadcrumb.
        last_run_at: ISO8601 of the most recent ``codex exec`` turn.
        context_delivery: how the start turn's transfer context reached the model:
            "initial_message" | "session_start_hook" | "hook_undelivered". Still
            CLI-written -- the hook's only write is the delivery receipt file, which
            the CLI reconciles into this field after the turn.
    """

    thread_id: str | None = None
    rollout_path: str | None = None
    rollout_source: str | None = None
    auth_method: str | None = None
    auth_source: str | None = None
    billing_mode: str | None = None
    last_run_at: str | None = None
    context_delivery: str | None = None


@dataclass
class SessionConfirmed:
    """What Claude Code actually reported via hooks.

    Ownership: hook-owned runtime facts only (see docs/design.md ownership boundaries).

    Notes:
    - Paths recorded in `artifacts` are repo-root-relative (e.g., `.forge/artifacts/...`) unless
      otherwise specified.
    """

    claude_session_id: str | None = None  # Pre-seeded at launch when possible; validated by SessionStart hook
    transcript_path: str | None = None

    # Proxy identity snapshot (optional; only set in proxy mode)
    started_with_proxy: StartedWithProxy | None = None

    # Plan tracking
    latest_plan_path: str | None = None  # Worktree-relative path to the latest plan file (e.g., ".claude/plans/x.md")

    # Session artifacts captured by hooks (repo-root-relative paths)
    artifacts: dict[str, Any] = field(default_factory=dict)

    # Policy enforcement state (decisions log, per-policy states)
    policy: PolicyConfirmed | None = None

    # Verification state (iterations, timing for Ralph-Wiggum feedback loop)
    verification: VerificationConfirmed | None = None

    # Compaction tracking (transcript snapshots, event count)
    compaction: CompactionConfirmed | None = None

    # Subagent activity tracking (counts, last agent info)
    subagents: SubagentConfirmed | None = None

    # Sidecar execution mode (proxy bundled in Docker container)
    is_sandboxed: bool = False

    # Immutable launch facts (route + api-key posture), CLI-owned, set once at start.
    # Stays None for Codex-runtime sessions (codex below is their auth breadcrumb).
    launch: LaunchConfirmed | None = None

    # Codex runtime facts (thread_id, rollout, auth posture), CLI-owned, hook-free.
    codex: CodexConfirmed | None = None

    # Context derivation tracking (for resumed or forked sessions)
    derivation: Derivation | None = None

    # The exact CWD Claude Code was launched from. Set at launch time by the
    # CLI (not the hook) because the hook runs inside the Claude process which
    # already inherited the CWD. Used by resume to match Claude's project
    # namespace (~/.claude/projects/<encoded-cwd>/).
    claude_project_root: str | None = None

    # Frozen consumer-lane bindings (epic consumer_lanes, T1b). Hook-written
    # (policy-check `_mutate`), write-once per consumer dispatch.
    consumer_lanes: ConsumerLaneConfirmed | None = None

    confirmed_at: str | None = None  # ISO8601 string
    confirmed_by: str | None = None  # e.g., "hook:SessionStart"


# --- Main session state structure ---


@dataclass
class SessionState:
    """Complete session state stored in .forge/sessions/<name>/forge.session.json.

    Schema is intentionally strict:
    - No unknown top-level fields
    - No unknown nested fields
    - No unknown override keys

    This keeps the file a clear contract rather than an unbounded blob.
    """

    schema_version: int
    name: str
    created_at: str  # ISO8601 string
    last_accessed_at: str  # ISO8601 string
    parent_session: str | None = None
    is_fork: bool = False
    is_incognito: bool = False
    worktree: Worktree | None = None
    intent: SessionIntent = field(default_factory=SessionIntent)
    # Sparse overrides - same shape as intent, only changed fields present
    overrides: dict[str, Any] = field(default_factory=dict)
    confirmed: SessionConfirmed = field(default_factory=SessionConfirmed)
    # Project identity (see design.md §3). Optional for backward compat with existing manifests.
    forge_root: str | None = None  # Forge project root (where .forge/ lives)


# --- Index structures (for ~/.forge/sessions/index.json) ---


@dataclass
class SessionIndexEntry:
    """A single entry in the session index.

    UUID fields enable fast reverse lookup (find session by UUID) without
    scanning all manifests. These are lazily synced by CLI commands.
    """

    worktree_path: str  # Absolute path to worktree (legacy; prefer forge_root)
    project_root: str  # Absolute path to main repo (logical repo identity)
    last_accessed_at: str  # ISO8601 string
    is_fork: bool = False
    is_incognito: bool = False
    parent_session: str | None = None
    # UUID field for reverse lookup (set by SessionStart hook)
    claude_session_id: str | None = None
    # Empty string (not None) because strict dacite requires str type match;
    # use entry.root for the resolved path (prefers forge_root, falls back to worktree_path).
    forge_root: str = ""  # Forge project root (where .forge/ lives)
    checkout_root: str = ""  # Git checkout root (--show-toplevel)
    relative_path: str = "."  # forge_root relative to checkout_root

    @property
    def root(self) -> str:
        """Resolved project root: forge_root if set, else worktree_path (pre-identity-model fallback)."""
        return self.forge_root or self.worktree_path


@dataclass
class SessionIndex:
    """Global session index for fast listing."""

    version: int = INDEX_VERSION
    sessions: dict[str, SessionIndexEntry] = field(default_factory=dict)


# --- Factory functions ---


def session_runtime(state: SessionState) -> str:
    """Return the session's runtime registry id (default ``claude_code``)."""
    launch = state.intent.launch
    return launch.runtime if launch is not None else "claude_code"


def create_session_state(
    name: str,
    *,
    proxy_template: str | None = None,
    proxy_base_url: str | None = None,
    parent_session: str | None = None,
    is_fork: bool = False,
    is_incognito: bool = False,
    worktree_path: str | None = None,
    worktree_branch: str | None = None,
    launch_mode: str = LAUNCH_MODE_HOST,
    sidecar_mounts: list[str] | None = None,
    sidecar_image: str | None = None,
    direct_model: str | None = None,
    runtime: str = "claude_code",
) -> SessionState:
    """Create a new session state with defaults.

    Args:
        name: Session name (must be validated separately).
        proxy_template: Proxy template (e.g., "litellm-gemini"). Optional in direct mode.
        proxy_base_url: Proxy base URL (e.g., "http://localhost:8084"). Optional in direct mode.
        parent_session: Parent session name (for forks).
        is_fork: Whether this is a forked session.
        is_incognito: Whether this is an incognito session.
        worktree_path: Absolute path to git worktree (if any).
        worktree_branch: Git branch name (defaults to session name).
        launch_mode: How Forge should relaunch this session ("host" or "sidecar").
        sidecar_mounts: Raw sidecar mount specs to persist for relaunch.
        sidecar_image: Optional sidecar image override to persist for relaunch.
        direct_model: Optional Claude Code env-ready direct model pin.
        runtime: Runtime registry id driving launcher dispatch ("claude_code" | "codex").

    Returns:
        A new SessionState with timestamps set to now.
    """
    now = now_iso()

    if (proxy_template is None) != (proxy_base_url is None):
        raise ValueError("proxy_template and proxy_base_url must be provided together")

    proxy = None
    if proxy_template is not None and proxy_base_url is not None:
        proxy = ProxyIntent(template=proxy_template, base_url=proxy_base_url)

    launch = LaunchIntent(mode=launch_mode, direct_model=direct_model, runtime=runtime)
    if launch_mode == LAUNCH_MODE_SIDECAR or sidecar_mounts or sidecar_image is not None:
        launch.sidecar = SidecarLaunchIntent(
            mounts=list(sidecar_mounts or []),
            image=sidecar_image,
        )

    worktree = None
    if worktree_path:
        worktree = Worktree(
            path=worktree_path,
            branch=worktree_branch or name,
        )

    return SessionState(
        schema_version=SCHEMA_VERSION,
        name=name,
        created_at=now,
        last_accessed_at=now,
        parent_session=parent_session,
        is_fork=is_fork,
        is_incognito=is_incognito,
        worktree=worktree,
        intent=SessionIntent(
            proxy=proxy,
            launch=launch,
        ),
        confirmed=SessionConfirmed(),
    )


def session_state_to_dict(state: SessionState) -> dict[str, Any]:
    """Convert SessionState to dict.

    This should be used instead of dataclasses.asdict() when serializing
    session state to JSON.
    """
    from dataclasses import asdict

    return asdict(state)
