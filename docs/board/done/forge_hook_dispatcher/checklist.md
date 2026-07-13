# Execution checklist: T4 `forge_hook_dispatcher`

Execution plan for the user-scope hook dispatcher. Coordination/contract lives in the epic
[`card.md`](../../done/epic_global_forge_runtime/card.md); this member's problem framing is [`card.md`](card.md).

> **Revised 2026-07-07** after a code-cited review: three-rule behavioral parity (not byte-parity), codegen drift-guard,
> the structural (not latency) no-import framing, shim-staleness ownership, `$HOME`-normalized golden, two new
> acceptance rows, and a populated-registry benchmark. See "Open decisions" for the reframed (c).

## Current focus

**Closed after PR merge.** Phase 0 resolved the shim-vs-symlink decision before production code, and Phases 1-6 are
implemented/verified. The card has moved to `done/`; T5 still owns the user-scope registration flip and detection
update.

**Scope boundary (do not cross):** T4 ships the *mechanism* — dispatcher entrypoint, `forge` resolver, no-op gate,
metadata home, and the rendered command-byte form + golden. It does **not** flip hook registration to user-scope-only
(that is T5 `user_scope_hook_ownership`), does **not** handle `FORGE_SIDECAR` in-container resolution (that is T10
`forge_hook_sidecar_resolution`), and does **not** touch `statusLine` (epic D3: statusLine stays project-scoped, is not
a hook, and does not route through this dispatcher).

## Grounding (verified 2026-07-07 on `main`)

Reuse seams, confirmed by symbol on this branch:

- **T3 registry — the exact behavior the shim mirrors:** `src/forge/install/project_registry.py`.
  `ProjectRegistryStore.lookup_enrolled_root` (:251) *is* the enrollment decision, and already the fail-open path:
  `find_forge_root` walk-up (:256) → `read_for_hook` (:216, catches corrupt/unreadable → empty registry + `degraded`) →
  `project_paths_match` (:130) against enrolled roots. Its **three rules** — walk-up+git-stop, canonicalize, match — are
  what the shim replicates (Phase 0(c)); the shim's parity target is this function's *behavior*, not a one-liner.
  `contains_root` (:245), `canonicalize_project_path` (:111), `project_path_lookup_key` (:117), `project_paths_match`
  (:130, `samefile` fallback via `_same_existing_path` :123) are the helpers — **all pure `pathlib`, so embeddable**.
  `read_strict` is the CLI (strict) path; `read_for_hook` is the fail-open path the dispatcher needs.
- **cwd → project resolution (rule 3):** `find_forge_root` (`core/ops/context.py:106`) walks up and **stops at a `.git`
  boundary, returning `None`** (:121-122), so a walk never escapes into a parent repo's `.forge/`. Pure `pathlib`.
- **Binary-location helpers:** `install/doctor.py` owns the global-tool bin candidates (`~/.local/bin` /
  `UV_TOOL_BIN_DIR` / `XDG_BIN_HOME` / `PIPX_BIN_DIR`) and the launcher-vs-realpath distinction from T1. Factor/reuse
  that candidate logic for dispatcher resolution; do **not** use `find_forge_installation` (`installer.py:280`) as the
  binary resolver — it detects extension installation scope/tracking evidence, not the executable path.
- **Detection needle (T5-owned, flagged here):** `has_forge_hook` (`install/hooks.py:104`) matches the substring
  `"forge hook"` **with a space**; `is_forge_hook_command` (`:49`) is the shared predicate.
- **Managed-session marker reaches the hook env:** `FORGE_SESSION` — `cli/hooks/commands.py:1306` (probe-verified).
- **Trust-byte surface (golden):** `install/codex_hooks.py:16-19,66-67`; existing golden `test_codex_hooks.py:71`.
- **Frequency the ceiling is measured against:** hooks fire on every `PreToolUse:Read` + `UserPromptSubmit`, in every
  repo — 13 event keys, `preset.py:47-217`.

> Note: line numbers are the 2026-07-07 snapshot; re-grep the symbol before relying on an exact line.

## Phase 0 — Benchmark + shape decision (DECISION GATE)

**No production code in this phase.** Throwaway harness under `scripts/experiments/hook-dispatcher/` only.

- [x] Set the **absolute no-op ceiling first**, before measuring, and record it (propose ~15–30 ms cold — justify
  against the per-Read / per-prompt cadence of `preset.py:47-217`, not a per-session cost).
  - _Decision recorded before measuring (2026-07-08):_ the hot no-op path must stay at **p95 \<= 30 ms** cold-process
    wall time on this host. The ceiling is intentionally tied to `PreToolUse:Read` / prompt cadence, where several
    invocations can occur during one active editing burst; a once-per-session budget would hide the user-scope cost.
- [x] Build minimal representatives of both shapes and measure the **no-op path** cold-start wall-time (report p50/p95
  over N runs on this host):
  1. **Shim** `~/.forge/bin/forge-hook`: stdlib-only script that reads `~/.forge/projects.json` with `json`, does the
     enrollment match (walk-up + git-stop + match), and exits 0 without importing Forge.
  2. **Absolute symlink** to the real `forge`, gate moved inside `forge hook` (pays full Python + Forge import per
     hook).
  - **Methodology (keep the number honest against the "real gate"):** run against a **populated** registry (~10–50
    enrolled entries) at a realistic walk depth, not an empty file — `project_paths_match`'s `samefile` fallback is a
    per-entry `stat` and the walk-up is per-ancestor, so an empty/shallow fixture undercounts (the exact stub-benchmark
    mistake the epic's round-2 correction already fixed once).
  - _Measurement (2026-07-08,
    `uv run python scripts/experiments/hook-dispatcher/benchmark.py --runs 50 --project-count 40 --depth 5`):_ populated
    registry with 40 enrolled roots, unenrolled `.forge/` repo cwd at depth 5, cold subprocess per run.
    - Shim: **p50 20.21 ms / p95 22.13 ms** (min 19.09, max 23.24).
    - Full Forge gate representative: **p50 419.66 ms / p95 611.78 ms** (min 401.95, max 639.91). This imports the
      current Forge CLI assembly and runs the registry lookup as a lower-bound representative of an absolute-symlink
      `forge hook` gate.
- [x] **Decide the shape** against the measured number (card's prior is the shim, but the number decides).
  - _Decision:_ choose the stdlib `forge-hook` shim. Deciding number: shim **p95 22.13 ms**, under the **p95 \<= 30 ms**
    ceiling; the full Forge gate representative is ~27.6x slower at p95.
- [x] Record the three consequences the shape determines:
  - **(a) Detection update needed?** Required **iff** a hyphen `forge-hook` shim wins — the `"forge hook"` (space)
    needle (`hooks.py:104`) would then lie (`session_lifecycle.py`, `policy.py` callers warn wrongly). The update itself
    is **T5-owned**; T4 only records the verdict.
    - _Verdict:_ **yes**, detection must be updated in T5 because the chosen command is the hyphenated `forge-hook`
      shim, not a `forge hook ...` token sequence.
  - **(b) Derived enrollment cache?** Only if a `json` shim still misses the ceiling. The fallback is a CLI-maintained
    pre-canonicalized flat list the shim string-matches — this reduces **stored-side parse cost only** (the query-side
    walk/canonicalize/match still runs; see (c)) and is **never** "fall back to the slower symlink" (card, D-T3-c).
    - _Verdict:_ **no derived cache in T4.** The JSON shim p95 (22.13 ms) is below the 30 ms ceiling with 40 registry
      entries, so the canonical `projects.json` file remains the hot-path source.
  - **(c) Gate-parity strategy** (this member's real sub-decision). The shim **cannot `import forge` at all** — not a
    latency cost but a **structural wall**: `forge` lives in an isolated uv-tool venv, unreachable from the shim's
    ambient `python3`, so `import forge` fails entirely (the tempting "just import the one light module" middle path is
    dead — and would exceed the ceiling anyway). So the shim must **re-implement three rules in stdlib** —
    `find_forge_root`'s walk-up+git-stop, `canonicalize_project_path`, and `project_paths_match` — i.e. **behavioral
    parity with `lookup_enrolled_root`**, not byte-parity of a canonicalizer. The stdlib re-impl is **inevitable in the
    shim shape**; the only real choice is the **drift-guard mechanism**:
    - **Preferred — extract an embed-safe stdlib gate source** owned by the package, then render that source block into
      the shim. The drift guard should compare the embedded block to that source artifact (or another explicit
      generated-source contract), not blindly `inspect.getsource()` arbitrary package functions: the current behavior
      spans `find_forge_root`, registry parsing/fail-open, path matching, and DTO return shapes.
    - **Fallback — two implementations + a behavioral parity test** over the fixture matrix below. A derived cache is
      **not** an alternative here: the registry already stores canonical strings (`EnrolledProject.canonical_path`), so
      a cache only changes stored-side parse cost — it folds into (b) and leaves the query-side duplication untouched.
    - _Decision:_ use the preferred generated-source contract: package-owned, embed-safe stdlib gate/resolver source is
      rendered into the shim, and tests assert the rendered shim source is current plus behavioral parity against
      `ProjectRegistryStore.lookup_enrolled_root` for the matrix below. The rendered source hash catches
      installed-vs-package staleness; the code comment and parity fixtures guard the intentional stdlib copy against
      package-vs-registry drift. No arbitrary `inspect.getsource()` across package functions.
  - **Parity fixture matrix** (drives (c)'s test, whichever mechanism): symlinked root, case-variant spelling,
    subdirectory cwd (walk-up hits the root), **nested un-enrolled git repo inside an enrolled parent** (git-stop →
    no-op), worktree `.git` **file**, missing registry, corrupt/newer registry, registry with unknown top-level fields.
    Assert the shim's verdict equals `lookup_enrolled_root`'s over the matrix.
- [x] Close the **metadata-home** open question: extend `~/.forge/installed.json` (via `install/tracking.py`) vs a new
  `~/.forge/runtime.json`. Record the choice + rationale. If `installed.json` wins, account explicitly for
  `InstalledManifest`'s strict schema (`version` + `installations` today) and whether the change needs a manifest
  version/compatibility path; a separate `runtime.json` avoids coupling dispatcher metadata to extension tracking.
  - _Decision:_ use a dedicated `~/.forge/runtime.json` with its own schema version. Dispatcher binary metadata is
    runtime resolution state, not extension tracking state; keeping it out of `installed.json` avoids widening
    `InstalledManifest`'s strict `version` + `installations` schema and avoids migration coupling with T6 cleanup.
- [x] Write the outcome into the epic: tick the epic checklist `[ ] T4 benchmark` box with the result, and record the
  chosen shape + metadata home in the epic card's **seam 3** (and **seam 2** if the gate-parity strategy is stdlib
  duplication rather than codegen-from-source).
  - _Assertion:_ epic `card.md` seam 2/seam 3 + `checklist.md` benchmark box reflect the decision before Phase 1 starts.

**Blocker:** Phases 1–4 do not begin until every box above is ticked and recorded.

## Phase 1 — `forge` resolver + metadata home

- [x] Add the durable metadata home chosen in Phase 0; record the resolved global `forge` path at install time.
  - _Assertion:_ after `forge extension enable --scope user`, the recorded path resolves to the on-PATH global `forge`.
- [x] Implement the resolver (contract steps 2–4): recorded metadata → known tool locations (reuse `doctor.py`'s set) →
  verify executable → **fail loud** with a diagnostic naming the checked locations. Cross-upgrade durable (survives
  `uv tool upgrade` / `pipx upgrade` moving the binary via metadata + fallback, not a hard-coded path).
  - **Env-var vocabulary (epic coupling):** the fail-loud diagnostic and any dispatcher stderr are **new user-facing
    strings** — the reason `env_var_interface_boundary` was sequenced ahead of T4. They must pass the classification
    guard (`tests/src/cli/test_env_vocabulary.py`): name the checked locations, and treat any internal `FORGE_*` mention
    as a **deliberate diagnostic-tier classification** (a resolution-failure message naming `FORGE_SESSION` is
    defensible as diagnostic — but mark/classify it on purpose, don't leak it by accident).
  - _Assertion:_ fixture with no venv on `PATH` → resolver returns the global `forge` (acceptance: "Dispatcher resolves
    global Forge").
  - _Assertion:_ stale recorded path → tries known locations, else an actionable resolution error naming them
    (acceptance: "Stale target resolved").
  - _Verified:_ `tests/src/install/test_hook_dispatcher.py` covers recorded metadata, stale fallback, and failure
    diagnostics naming checked paths.

## Phase 2 — No-op gate + managed-session short-circuit (fail-open)

- [x] Implement the gate in contract order:
  1. `FORGE_SESSION` set → **dispatch even if cwd is not enrolled** (managed session must not lose hooks;
     `commands.py:1306`).
  2. else cwd not inside an enrolled root → **exit 0 without importing Forge / pydantic** (enrollment via the Phase-0
     gate-parity implementation: walk-up + git-stop + match, mirroring `lookup_enrolled_root`).
- [x] Hot-path registry read is **fail-open**: corrupt/newer `projects.json` → treat as not-enrolled, exit 0, no error
  (mirrors `read_for_hook`'s posture; distinct from `read_strict`'s CLI rejection).
  - _Assertion:_ cwd outside enrolled roots → exits 0 **and** no Forge import (probe the no-op path under
    `python -X importtime` / a tripwire; assert `forge` and `pydantic` absent) (acceptance: "Outside project no-ops").
  - _Assertion:_ `FORGE_SESSION` set + cwd not enrolled → dispatches anyway (acceptance: "Managed session
    short-circuits").
  - _Assertion:_ corrupt/newer `projects.json` + hook run → degrades to not-enrolled, exit 0, does not error
    (acceptance: "Corrupt registry fails open"; integration — the read-helper unit is T3's).
  - _Assertion:_ deleted cwd or other unexpected gate exception → degrades to not-enrolled, exit 0, no traceback
    (acceptance: "Gate exceptions fail open").
  - _Assertion:_ nested un-enrolled git repo inside an enrolled parent → git-stop → not-enrolled → no-op, no Forge
    import (acceptance: "Nested un-enrolled repo no-ops").
  - _Assertion:_ enrolled root reached from a subdirectory cwd → walk-up finds it → dispatches (acceptance:
    "Subdirectory cwd dispatches").
  - _Verified:_ subprocess tests cover managed-session dispatch, outside/non-enrolled no-op with Forge/pydantic
    tripwires, corrupt/newer/unknown-field registry fail-open, deleted-cwd gate exception fail-open, nested git-stop
    no-op, symlink/case/worktree parity, and subdirectory dispatch.

## Phase 3 — Dispatcher entrypoint + runtime-agnostic forwarding

- [x] On dispatch, `exec` the resolved `forge hook <name>` so stdin/stdout/stderr/exit code pass through unchanged.
- [x] One dispatcher, invoked by both Claude and Codex with different stdin payloads; it forwards to `forge hook <name>`
  and must **not** branch on the calling runtime (Risk: runtime-agnostic forwarding).
  - _Assertion:_ a Claude-shaped and a Codex-shaped stdin payload both dispatch to `forge hook <name>`; exit code and
    stdout pass through.
  - _Verified:_ runtime-agnostic subprocess test forwards Claude-shaped and Codex-shaped stdin and preserves stdout,
    stderr, and exit code.

## Phase 4 — Rendered command bytes (renderer + golden) — NOT registration

- [x] Produce the rendered command string as a **literal absolute path, never `~`** (hook runners may not tilde-expand).
- [x] Golden-pin the rendered command **template** (Codex `trusted_hash` surface, `codex_hooks.py:16-19,66-67`).
  **Unlike the existing codex golden** (which pins user-independent `forge hook …` strings), the dispatcher command
  embeds the user's absolute home, so the golden pins the **template with `$HOME` normalized**, plus a separate
  assertion that render substitutes the real home. A byte change to the template must fail the golden.
  - _Assertion:_ user hook install → rendered config contains `/abs/home/.forge/bin/...`, not `~` (acceptance: "Literal
    absolute path").
  - _Assertion:_ `$HOME`-normalized template golden fails on a byte change; render substitutes the real home correctly.
- [x] **Shim-staleness contract (owner: T4).** `uv tool upgrade` updates the package but never re-renders
  `~/.forge/bin/forge-hook`, so embedded gate logic can drift from the package — e.g., a future registry schema v2 that
  a stale shim's fail-open maps to "not enrolled" forever → hooks silently off everywhere (the no-op promise inverted).
  Version-stamp the rendered shim; make `forge extension sync` re-render it; teach `forge extension doctor` to report
  render-vs-installed drift. The source stamp makes installed-vs-package drift visible; the Phase 0 parity matrix guards
  the package-owned stdlib copy against registry-rule drift. If doctor's drift surfacing is deferred, **assign it
  explicitly to T5/T6 here** — do not leave it unowned.
  - _Assertion:_ rendered shim carries a version stamp; `extension sync` re-renders on a version change; a stale-shim
    fixture is reported by `doctor` (or the deferral is recorded with an owner).
- [x] **Do not** alter what `preset.py` / `codex_hooks.py` currently register at project scope — the flip to
  user-scope-only registration is **T5**. T4 provides the renderer + installed shim/symlink artifact + metadata only.
  - _Verified:_ no changes to `preset.py` or `codex_hooks.py`; T5 detection update remains recorded as a consequence of
    the shim shape.

## Phase 5 — Design-doc sync

- [x] `design.md §3.10` (Hook handlers / Deployment model): hooks resolve the global `forge` via the dispatcher; note
  the no-op gate + `FORGE_SESSION` short-circuit.
- [x] `design_appendix §C` (install model): metadata home, resolution contract, the rendered absolute-path form, and the
  shim-staleness (stamp + sync-re-render + doctor drift) contract.
- [x] Epic `card.md` shared-contract **seam 3** (Forge-binary resolution): record chosen shape, metadata home, and
  gate-parity strategy; amend **seam 2** if parity is stdlib-duplication rather than codegen-from-source.

## Phase 6 — Closeout

- [x] All acceptance rows green in `tests/src/install/test_hook_dispatcher.py` (new); benchmark script remains the
  authority for the Phase-0 ceiling, while the in-suite no-op test asserts populated-registry no-dispatch/no-import
  behavior without a flaky wall-clock bound.
- [x] `make pre-commit` clean.
- [x] Install/hook integration run (this touches install + hook wiring — testing_guidelines mandates integration for
  installer/hook changes): `./scripts/test-integration.sh tests/integration/docker/test_installer.py` plus any
  hook-reachability integration added here.
- [x] Epic checklist `[ ] T4 benchmark` ticked with outcome; epic card seam 3 recorded.
- [x] `change_log.md` entry (Goal / Key changes / Verification); durable lessons proposed for `impl_notes.md` (human
  review before promotion).
- [x] Lane move `doing/ -> done/` completed after the PR merged; inbound board links repointed (epic forward-link and
  member back-link).

## Acceptance tests

Grounded on the card's contract; all in `tests/src/install/test_hook_dispatcher.py` (new).

| Test                             | Fixture                                              | Assertion                                                                       | Phase |
| -------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------- | ----- |
| Dispatcher resolves global Forge | dispatcher installed, no venv on `PATH`              | hook command exits 0 and dispatches to the global `forge`                       | 1     |
| Stale target resolved            | recorded `forge` path stale                          | tries known tool locations, else an actionable resolution error naming them     | 1     |
| Outside project no-ops           | cwd outside enrolled roots                           | exits 0 without loading project state / importing Forge (`-X importtime` probe) | 2     |
| Managed session short-circuits   | `FORGE_SESSION` set, cwd not enrolled                | dispatches anyway (managed session keeps hooks)                                 | 2     |
| Nested un-enrolled repo no-ops   | enrolled parent, un-enrolled git repo nested inside  | walk-up hits the nested `.git` → not-enrolled → exits 0, no Forge import        | 2     |
| Subdirectory cwd dispatches      | cwd is a subdir of an enrolled root                  | walk-up finds the enrolled root → dispatches to `forge hook <name>`             | 2     |
| Corrupt registry fails open      | corrupt/newer `projects.json`, hook run              | degrades to not-enrolled, exits 0, does not error (integration)                 | 2     |
| Gate exceptions fail open        | deleted cwd or unexpected gate exception             | degrades to not-enrolled, exits 0, no traceback                                 | 2     |
| Runtime-agnostic forwarding      | Claude-shaped and Codex-shaped stdin payloads        | both forward to `forge hook <name>`; stdin + exit code pass through             | 3     |
| Literal absolute path            | user hook install                                    | rendered config contains `/abs/home/.forge/bin/...`, not `~`                    | 4     |
| Rendered command template golden | rendered dispatcher command (`$HOME`-normalized)     | golden pins the template; a byte change fails (guards Codex trust-byte)         | 4     |
| Shim staleness detected          | shim rendered by an older version than installed     | `doctor` reports render-vs-installed drift (or deferral recorded)               | 4     |
| No-op path is cheap              | non-Forge repo, per-Read cadence, populated registry | benchmark records the Phase-0 ceiling; in-suite test asserts no dispatch/import | 0/2   |

## Open decisions (close in Phase 0)

- **Shim vs absolute-symlink** — benchmark decides; also decides (a) whether T5's detection update is required and (b)
  whether a derived enrollment cache is introduced.
- **Metadata home** — extend `installed.json` vs new `~/.forge/runtime.json`.
- **Gate-parity drift-guard** — codegen the three gate rules into the shim from package source (drift impossible) vs two
  implementations + a behavioral parity test against `lookup_enrolled_root`. The stdlib re-impl itself is **not**
  optional (`import forge` is structurally unreachable from the shim); a derived cache is only a stored-side parse
  optimization, not a parity strategy.

## Blockers / deferred (owned elsewhere)

- **Detection update** (`has_forge_hook` + callers) — owned by **T5**, gated on Phase 0's shape.
- **In-container (sidecar) resolution** — owned by **T10** (`FORGE_SIDECAR`-keyed); T4 is host-only and does not handle
  it.
- **statusLine** — out of scope (epic D3): not a hook, stays project-scoped, does not route through the dispatcher.
- **Doctor drift-surfacing for a stale shim** — T4 owns the version stamp + `sync` re-render; if the `doctor` drift
  report is deferred, it is reassigned to T5/T6 explicitly in Phase 4 (not left unowned).
