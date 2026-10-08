# Forge Session Design

Canonical session-state, launch, transfer, hook, queue, Codex, and event-journal contracts.

The session domain is partitioned by ownership:

- This document owns the durable session schema, identity, and store invariants.
- [Session context](design_session_context.md) owns plans/transcripts, resume strategies, and transfer schemas.
- [Session execution](design_session_execution.md) owns hooks, the work queue, Codex runtime guards, and event journals.

---

## Session contracts

### 3.3 Session file schema (`forge.session.json`)

A Forge session is a durable workflow record, not a process-invocation record. A Claude-runtime session records its
current or last-seen conversation in `confirmed.claude_session_id`; multiple process invocations may reattach to that
conversation, and hooks reconcile the identity when Claude rolls it over. Codex-runtime sessions use the analogous
`confirmed.codex.thread_id` and leave `claude_session_id` unset.

For Claude, `confirmed.claude_session_id` has field-specific CLI/hook ownership depending on the launch path.
`forge session start` **pre-seeds** it: the CLI generates a UUID, writes it to the manifest at creation, and imposes it
on Claude via `--session-id`; the SessionStart hook then **validates** that UUID. The same pre-seed applies to
**transfer/fresh children** (the cross-worktree default for `session fork` and `resume --fresh`): Forge mints a **new**
UUID and imposes it via `--session-id`. The exception is a **native** fork (`--resume-mode native`, which passes
`--fork-session`): Forge does **not** pre-seed — Claude mints the child UUID and SessionStart **discovers and records**
it (`native-relocate` instead reuses the parent's UUID). A third origination path is `forge session adopt`, which
**binds** an existing native UUID: the conversation already exists, so the CLI neither mints nor discovers, it records
what the user names and cross-checks the transcript's recorded `cwd` before writing (§3.3 identity is unchanged — one
manifest per conversation, and reattach behaves exactly as it does for a Forge-born session).

The same command adopts a native **Codex** thread: the runtime is decided by which store holds a matching conversation,
never by the shape of the id (both runtimes use UUIDs, and their differing versions are an undocumented third-party
detail), and a match in both is refused rather than guessed. The Codex arm records
`confirmed.codex.rollout_source="adopted"` and leaves `claude_session_id`/`confirmed.launch` unset; its lookup scans
every thread-id match and filters by the rollout head's `cwd`, refusing an ambiguous result instead of taking
`find_rollout_path`'s newest-mtime tie-break. The id must be a canonical UUID: it is the only caller-supplied component
of every path adoption reads or writes. Omitting it previews the unbound Claude conversations whose recorded `cwd` is
the current directory — a read-only CLI scan of one encoded project directory, which does not relax §3.10: hooks still
resolve sessions by identity and never scan. Adoption also inverts transcript ownership, so
`SessionManager.delete_session` exempts an adopted session's native transcript from `delete_transcripts` (including the
`delete_transcripts=True` automatic retention sweep) using the same filter that spares transcripts shared with another
session. Relocated transcripts use the same ownership scan; a cached owner remains conservatively protected, while a
cached absence is rescanned at the unlink boundary after another process may have published a sibling during ordinary
cleanup. The final negative scan and unlink share the global index-publication lock, so a sibling manifest cannot be
published between the ownership decision and removal. When the current and relocated UUIDs alias, ordinary cleanup
excludes that UUID; the locked final scan owns removal of its transcript and preidentified agent logs. Adoption resolves
the `.forge/artifacts` root before enforcing destination containment, so relocating that root with a symlink is
supported; a descendant destination that escapes the resolved root or aliases the native transcript is refused, and
rollback only unlinks an artifact created by the current copy attempt. Stop and StopFailure also reconcile
`claude_session_id` and `transcript_path` from their hook payloads to correct fork-session launches where SessionStart
sees an inherited parent UUID. Because the start path pre-seeds, a non-null `claude_session_id` does **not** by itself
mean the session ran (a `--no-launch` or not-yet-launched start session already carries a pre-seeded UUID);
"used"/resumable requires hook confirmation or transcript-backed evidence (see Default resume behavior).

**Default resume behavior.** `forge session resume <name>` reattaches to the same Claude conversation without creating a
child when the session has resumable evidence (hook confirmation or transcript-backed state) and is not currently
active. Reattach refreshes `confirmed` runtime facts such as `confirmed_at` and `transcript_path`; those fields reflect
last-seen state rather than immutable launch facts. A never-launched session with no durable confirmation or transcript
evidence launches in place, even though `session start --no-launch` may have pre-seeded its UUID. Use `--fresh` to
derive a new child session with context assembly. `--force` against an active, resumable session launches a lineage
child instead of attaching a second process to that conversation.

The session file has three sections:

> Schema is intentionally strict: unknown fields and unknown override keys are rejected.

Before strict decoding, a no-write allowlist migration strips legacy `intent.memory.generated_file` only at that path;
new writes omit it.

Session manifests write schema v2 when representable without the new supervisor fields, otherwise v3.
`forge.session.store::manifest_for_write` owns that compatibility projection;
`forge.session.store::_SUPPORTED_SCHEMA_VERSIONS` admits v1, v2, and v3 on read. Strict legacy validation precedes
in-memory projection: v1 gains `intent.launch.model_route=null` when launch exists; v1/v2 supervisors gain
`auth_mode="inherit"` and `supervisor_model=null`. Legacy positive timeouts above 45 seconds clamp to 45 in both intent
and overrides; Codex bindings discard formerly ignored Claude proxy/base-URL fields. No read rewrites a manifest. These
defaults preserve existing frozen bindings and runtime-selected models; an old nominal lane model is not an explicit
model request. V3 requires both supervisor fields when a supervisor object exists. Older Forge versions cannot read v3
manifests; downgrade requires restoring the pre-upgrade manifest backup, not deleting unknown fields from a live
session. Unknown versions and extra fields remain errors.

Ordinary host writes remain readable by existing v2 sidecars. Sidecar launch checks the image's schema support before
mounting user state; conversation supervision also requires the current isolated reviewer implementation and CLI flags.
An incompatible image refuses launch with rebuild guidance. Reading launch preferences does not decode unrelated
overrides or reject a legacy sidecar plan; the selected launch path returns an actionable host-executor error.

`intent` and `overrides` are required objects. Missing `confirmed` defaults empty; when present, it must be an object.
Other values are corruption, surfaced without rewriting.

| Section         | Definition                    | Written by              | Semantics                                    |
| --------------- | ----------------------------- | ----------------------- | -------------------------------------------- |
| **`intent`**    | Baseline config Forge *wants* | `forge session start`   | Session-owned fields only                    |
| **`overrides`** | Live toggles on top of intent | `forge session set`     | Diff (can be cleared)                        |
| **`confirmed`** | Ground truth of what happened | CLI and hooks, by field | Recorded facts; mutability is field-specific |

`confirmed` ownership and mutability are not section-wide. The CLI owns bootstrap, derivation, launch, and Codex runtime
facts; hooks own observed Claude runtime facts, artifacts, and enforcement state. Some fields are write-once or frozen
(`launch`, explicit consumer-lane bindings), some are additive (`artifacts`), and some are reconciled or refreshed as
the runtime advances (`claude_session_id`, `transcript_path`, `confirmed_at`, and Codex turn facts). The field-level
rules in §3.5 are normative.

**`intent.launch`**: Forge-owned relaunch preferences for reproducible session launch:

```yaml
launch:
  mode: sidecar
  sidecar:
    mounts: [/data:/mnt/data:ro]
    image: my-dev-image:latest
  model_route: null
```

This keeps `forge session resume <name>` honest for sidecar sessions without overloading `confirmed` with user-owned
preferences.

In schema v2/v3, a present `intent.launch` object must include `model_route`, either `null` or the complete neutral
route selection:

```yaml
model_route:
  requested_model: gpt-5.6-sol # canonical model-catalog id when written
  selected_tier: opus # haiku | sonnet | opus
  kind: proxy # direct | proxy
  source_id: openrouter # proven backend source; null for direct or unproven proxy routes
```

`requested_model` records user intent independently of transport. Forge writes the then-canonical model id. `source_id`
records an automatic, explicit, or preserved proxy source only when Forge can prove its then-canonical identity; direct
routes require `null`. Catalog membership is a writer- and relaunch-time invariant, not a manifest-decode dependency. A
later model- or source-catalog removal therefore leaves the durable session record readable while relaunch reports the
unavailable route contextually. `intent.launch.direct_model` remains the Claude Code execution pin, including an
optional `[1m]` transport modifier, and `intent.proxy` remains the concrete proxy template/base URL.
`forge.core.ops.session_model_routing` owns the pure transition that replaces `intent.proxy`,
`intent.launch.direct_model`, and `intent.launch.model_route` together for a resolved route. Clearing neutral route
intent alone does not change the legacy proxy or Claude-pin fields. Legacy creation, adoption, `default_direct_model`,
and Codex paths do not synthesize `model_route`.

Bare replay treats `model_route` as the model, tier, kind, and source authority. It may restore `[1m]` only from a
matching Claude `direct_model` execution projection; a mismatched projection fails instead of changing the neutral
model. Proxy replay requires the stored template and any proven `source_id` to remain exact. Same-URL registry entries
cannot substitute another template, and later source inference cannot enrich an originally unproven route. Explicit
`--model` plus `--proxy` or `--no-proxy` is a replacement constraint and therefore does not inspect malformed stored
routing first.

**`intent.authority`**: optional, session-owned artifact authority:

```yaml
authority:
  role: advisory        # advisory | producer
  tier: shell_closed    # advisory only; named_tools | shell_closed
```

Absence is `unmarked` and retains legacy behavior. Advisory defaults to `shell_closed`; producer must not carry a tier.
The role is provider- and model-neutral. It is mutated only by authority-bearing creation flags or the typed inactive-
session `authority set|clear` operations, never by generic overrides. Fresh derivation inherits advisory authority and
its tier; producer authority is deliberately dropped. An explicit child designation wins before first launch.
`authority show` reads the manifest, authority journal, and runtime active registry without repairing any of them. A
malformed active registry is therefore an actionable read error; `session list` remains the explicit runtime-state
self-healing path.

**`intent.subprocess_proxy`**: optional proxy ID used only by Forge-spawned subprocesses:

```yaml
subprocess_proxy: openrouter-anthropic
```

This supports direct-mode main sessions that still need panel, supervisor, or memory-writer subprocesses routed through
a proxy for API-key auth and cost visibility. It is session-owned launch intent, not a proxy-owned tier/model override.
Resume, fork, and relaunch children inherit it unless the launch path explicitly chooses different routing.

**`confirmed.started_with_proxy`**: the proxy this session is running with (set at start, immutable for the run):

```yaml
started_with_proxy:
  proxy_id: my-high-reasoning        # optional, same-machine convenience
  template: litellm-openai           # which template this proxy came from
  base_url: http://localhost:8085    # the actual routing identity
```

**Normative semantics:** `proxy_id` is optional. The portable fields are `template/base_url`.

#### Effective vs Confirmed (normative distinction)

| Term            | What it answers                | How computed                       | Stored?                |
| --------------- | ------------------------------ | ---------------------------------- | ---------------------- |
| **`effective`** | "What *should* the config be?" | `intent` with `overrides` applied  | No (derived on-demand) |
| **`confirmed`** | "What *actually happened*?"    | CLI/hooks record field-owned facts | Yes (persisted)        |

**Override rules** (for session `intent + overrides` only):

- Scalars: override replaces
- Lists: override replaces entirely (no concat)
- Dicts: recurse into nested keys (untouched keys preserved)
- Explicit `null`: clears the field
- `intent.launch.runtime` is immutable dispatch identity: set rejects the direct key, a parent `launch` object carrying
  `runtime`, and `launch.*` before mutation. A whole-launch null clear remains valid because the section is optional and
  dispatch reads raw intent; reset accepts `launch` or `launch.runtime` so stale illegal overrides remain recoverable.
- Resolved `intent.launch.model_route` is lifecycle-owned: set rejects its subtree and enclosing `launch` objects; reset
  accepts stale paths.
- `intent.authority` is not overrideable: set and keyed reset reject the parent, wildcard, and concrete leaves.
  `reset --all` clears only overrides and cannot alter authority intent.

> **Note:** There is no "merging"—overrides simply win. The only subtlety is nested dicts: you can override
> `memory.tags` without losing `memory.auto_recall`. This applies to session-owned fields only (`tdd_mode`, `memory.*`,
> etc.). Proxy-owned fields come directly from the proxy.
