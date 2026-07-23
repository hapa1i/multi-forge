# cross_runtime_skills -- run Forge skills under Codex (and other Agent-Skills runtimes), not just Claude Code

**Lane**: `done/` -- shipped through PR #107 on 2026-07-17 after implementation, verification, and human review.

**Branch**: `cross-runtime-skills`, merged into `main` as `d2a94bf7`. Execution record: [`checklist.md`](checklist.md).

This is a standalone follow-up to the shipped runtime-abstraction lineage (`core/runtime/registry.py`;
`done/codex_frontend/`, `done/runtime_abstraction/`) and the closed installer/scope redesign in
[`epic_global_forge_runtime`](../../done/epic_global_forge_runtime/card.md). It consumes those contracts but cannot join
the closed epic as a live member.

**Type**: portability + install-surface work, structured as a **compile model, not a strip pass**: neutral skill content

- a per-runtime template/adapter + a build step that emits each runtime's package (see "Compose, don't strip"). **Two
  independent axes**: the playbook/install axis (this compile model) and the fan-out worker runtime (a separate engine
  change).

**Origin**: user request (2026-07-06) -- "`src/skills/` only works in Claude Code now." Framing verified against the
code, the Agent-Skills spec, and OpenAI's Codex docs. Review rounds (2026-07-06) corrected the discovery paths, the
`name`-conformance gap, the frontmatter-strip requirement, and the "behavior-preserving" claim, and steered the approach
from a per-file strip pass to the compile model below.

**Key external facts (verified 2026-07-06):**

- **Agent Skills is an open cross-vendor standard** (Anthropic published `SKILL.md` 2025-12-18; ~32 tools by 2026). The
  format is shared -- this is **not** "invent a skill mechanism for Codex."
- **The spec constrains `name` and defines a closed field set.** `agentskills.io/specification`: `name` **must match the
  parent directory** and be lowercase alphanumeric + hyphens (\<=64, no leading/trailing/consecutive hyphens). The
  frontmatter allowlist is exactly `name`, `description`, `license`, `compatibility`, `metadata` (arbitrary map), and
  `allowed-tools` (**space-separated, experimental**) -- there is **no `when_to_use`** and no Claude extension. The
  packager validator **may reject** unknown keys and Codex support for `allowed-tools` varies, so the Codex/spec build
  must **validate against this allowlist itself** rather than rely on any runtime tolerating extra keys.
- **Codex discovery paths.** Codex scans `.agents/skills` (repo, cwd -> repo-root), `$HOME/.agents/skills` (personal),
  `/etc/codex/skills`, plus bundled system skills. `~/.codex/config.toml` only **disables** skills via
  `[[skills.config]]` -- **not** a discovery dir. (The first draft's `~/.codex/skills` target was wrong -> invisible
  skills.)
- **Codex has native invocation metadata.** Per-skill `agents/openai.yaml` carries
  `policy.allow_implicit_invocation: false` -- the real control for "user-only" skills.

**Forge already documents the coupling.** `src/skills/review/references/skills-writing-guide.md` lists "Extended
frontmatter fields (Claude Code)" beyond the open standard (`:361-374`), warns the packager validator "may reject" them
(`:823-826`), and calls `$ARGUMENTS` / `${CLAUDE_SKILL_DIR}` / `context: fork` / dynamic injection "Claude Code-only"
(`:1300-1314`). This card acts on what the guide already knows.

---

## Why

At proposal time, Forge's 11 skills were authored in the open Agent-Skills format, yet nothing Forge shipped reached a
non-Claude runtime:

- **Install target is Claude-only.** `install/installer.py` writes every skill to `~/.claude/skills/` /
  `<project>/.claude/skills/` via `get_target_root()` + the `SKILLS` module (`install/models.py:58`). No
  `.agents/skills` target. `codex-hooks` (`install/codex_hooks.py`) is settings-only -- it installs **zero** skills.
- **The runtime registry doesn't model skills.** `RuntimeSpec` (`core/runtime/registry.py:105-139`) has seven capability
  axes -- **none** about a skill surface.
- **`name` is non-conformant and bodies use Claude-only built-ins**, some baked into resource files (below).

The prize: the workflow skills are Forge's user-facing scripting layer -- a Codex user (and every other Agent-Skills
runtime) gets none of them despite reading the identical format.

## Compose, don't strip (the core design decision)

A per-file *strip pass* (author a Claude `SKILL.md`, then remove/rewrite Claude-isms for Codex) is a **denylist** -- and
this card's own review history is the proof it fails: each round surfaced another missed Claude-ism
(`${CLAUDE_SKILL_DIR}` -> `Explore` in rubrics -> `name` -> frontmatter keys). Instead, **compose from neutral content**
(an allowlist -- the neutral layer *cannot* contain Claude-isms):

| Layer                               | Owns                                                | Notes                                                                                                                                                                                             |
| ----------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1. Neutral content**              | rubric/body text + resources, capability-abstracted | No tool names, path vars, `$ARGUMENTS`, or `subagent_type`. Model-target variants (`openai`/`gemini`/`anthropic`) live here -- orthogonal to runtime                                              |
| **2. Per-runtime template/adapter** | frontmatter dialect + capability bindings           | Emits `name` transform, `allowed-tools` (Claude) vs `agents/openai.yaml` (Codex), resource-path convention; binds "explore" -> Claude `Agent`/`Explore` vs Codex-native. Plugs into `RuntimeSpec` |
| **3. Build + install**              | compose (content x template) -> package -> install  | One package per runtime, to that runtime's dir; tracked in `installed.json`                                                                                                                       |

**The real work is layer 1 (behavioral neutralization), not layer 2.** Frontmatter and paths are easy to template. The
hard coupling is *behavior* embedded in content: the `!` model-family **pre-step** (`review:45-57`, a deterministic
branch into `code-{family}.md`) and the `subagent_type: "Explore"` instructions **inside the rubrics**
(`understand/resources/docs-openai.md:55-57`). These must be lifted into a **capability vocabulary** the content
references abstractly and each runtime template binds.

**Combinatorics trap (must-not-break):** the family variants already exist per model-target. If the runtime binding is
*not* factored out of them, you get a **family x runtime matrix** (`code-openai-claude.md`, `code-openai-codex.md`,
...). Keeping the runtime binding in layer 2 (not layer 1) is what prevents the blow-up -- today the family variants
leak `subagent_type: Explore`, so that extraction is the concrete first task.

## Axis 1 -- the per-runtime coupling the compile model must resolve

| Coupling                                                                                                               | Codex/spec behavior                                                                                                                       | Compile-model handling                                                                                                                                                           |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name: forge:<x>`                                                                                                      | **non-conformant** (colon; `!=` dir) -- rejected/mis-matched                                                                              | layer 2 emits the runtime's `name`: Claude keeps `forge:<x>`; spec/Codex gets dir-matching `<x>`                                                                                 |
| Claude-only keys: `disable-model-invocation`, `argument-hint`, `context`, `effort`, `agent`, `hooks`, `user-invocable` | **not in the spec allowlist** (packager may reject)                                                                                       | layer 2 **omits** them from the spec/Codex build (non-policy extras -> `metadata`); `disable-model-invocation` -> `agents/openai.yaml` `policy.allow_implicit_invocation: false` |
| `allowed-tools: Read, Grep, Glob, Bash, Agent`                                                                         | **spec field**, but Forge's value is comma-style Claude tool names; the spec wants space-separated, and it's experimental (Codex ignores) | layer 2 rewrites to space-separated + reconciles values, **or** omits it (experimental)                                                                                          |
| read-only `${CLAUDE_SKILL_DIR}/resources/...` references                                                               | **no variable**, but Codex is told the selected `SKILL.md` path                                                                           | layer 1 names a package-relative resource; layer 2 tells the runtime to resolve it from the selected skill root                                                                  |
| executable `${CLAUDE_SKILL_DIR}/scripts/...` references                                                                | **no variable and shell CWD remains the repository**                                                                                      | distinct packaged-script capability; the Codex binding resolves against the loaded `SKILL.md` parent before execution                                                            |
| `$ARGUMENTS`                                                                                                           | **no substitution**                                                                                                                       | layer-1 "read the task"/capability; layer 2 binds the arg source                                                                                                                 |
| inline `` !`forge ...` `` pre-step                                                                                     | **inert text**                                                                                                                            | layer-1 capability ("resolve model family"), pinned + **all three family branches tested**; not "just run it"                                                                    |
| `subagent_type: "Explore"` / `Agent` in rubrics                                                                        | absent                                                                                                                                    | layer-1 "explore" capability; layer-2 binds (Claude `Agent`/`Explore` vs Codex-native)                                                                                           |
| `AskUserQuestion`, `Write`, `$CLAUDE_SESSION_ID`                                                                       | absent                                                                                                                                    | per-skill capability/degrade                                                                                                                                                     |

**Slice by coupling depth.** `challenge` and `smoke-test` are shallow-coupling candidates, not neutral artifacts:
`challenge` needs an argument binding, while `smoke-test` needs both packaged-script resolution and runtime-specific
install-home probes. The approved sequence proves those bindings first, then migrates `review`, `understand`, and
`review-docs`; the rubric neutralization remains the substantive layer-1 work.

## Axis 2 -- fan-out worker runtime (a separate engine change)

`panel`, `analyze`, `debate`, `consensus` shell out to `forge workflow`, whose engine **hardwires `claude -p` workers**
(`review/engine.py:283`, hard binary requirement `:64-67`). A `CodexHeadlessInvoker` exists (`core/invoker/__init__.py`)
but `review/engine.py` does **not** use it -- so these skills need `claude` on PATH for their workers even when driven
from Codex, until the engine dispatches through the runtime registry. That engine change is tracked separately in
[`runtime_neutral_workflow_workers`](../runtime_neutral_workflow_workers/card.md).

## Target shape

1. **Layer-1 neutralization**: extract a capability vocabulary from the skill bodies/rubrics (explore, arg access,
   model-family pre-step, resource load, invocation policy); rewrite content to reference it; keep the
   `openai`/`gemini`/ `anthropic` variants runtime-free. Add a "compose model / capability vocabulary" section to
   `skills-writing-guide.md`.
2. **Layer-2 runtime templates/adapters**: a Claude template (current frontmatter + `Agent`/`Explore` binding) and a
   Codex template (dir-matching `name`, spec-only top-level keys, `agents/openai.yaml`, `.agents/skills` path
   convention). Align the binding surface with `RuntimeSpec`.
3. **Layer-3 build + install**: extend the `SKILLS` module to compose + write per runtime -- Claude to
   `.claude/skills/`, Codex to `.agents/skills` / `$HOME/.agents/skills` (**not** `$CODEX_HOME`). Track per runtime in
   `installed.json`, building on the contracts already shipped by `epic_global_forge_runtime`.
4. **Model skills in `RuntimeSpec`**: add `skill_scopes`, with **per-runtime values, not a mirror of `install_scopes`**.
   Codex skills are **user (`$HOME/.agents/skills`) + project (`.agents/skills`, shared/committed)**; Codex has no
   analog to Forge's personal-per-project `local`, so `local` is **unsupported** for Codex skills (or a named untracked
   convention) -- never mapped onto the shared `.agents/skills`.
5. **Runtime selection**: `forge extension enable --runtime <claude|codex|all>` selects skill-package targets. A new
   automatic enable keeps Claude and adds detected Codex; an existing automatic enable retains managed runtimes, and an
   explicit selection refreshes the selected runtimes while preserving omitted tracked packages. Sync preserves the
   complete managed set. Only disable removes the installation's managed packages.
6. **(Axis 2, separate)** route the fan-out engine's workers through the runtime registry / `CodexHeadlessInvoker` in
   `runtime_neutral_workflow_workers`.

## Non-goals / must-not-break

- **No Claude regression** -- the Claude template must reproduce today's `SKILL.md` byte-for-byte where it matters
  (`/forge:<x>` name, the model-family pre-step, `Agent`/`Explore`).
- **No family x runtime blow-up** -- runtime binding stays in layer 2, never in the family variants.
- **Not the manual-test skills** -- `walkthrough` / `qa` orchestrate Claude Code *itself* (`AskUserQuestion` loop,
  agent-adjudicated checklist, `docker exec`); Claude-by-nature.
- **Not sidecar parity** -- sidecars launch Claude, preserve project-scoped Claude skill visibility through the mounted
  workspace, and do not gain host-user skill mounts or a Codex runtime in this card.
- **Axis 2 is deferred** -- `panel`, `analyze`, `debate`, and `consensus` remain Claude-only until the separate worker
  dispatch card ships; do not label a Claude-worker frontend Codex-native.
- **No plugin marketplace expansion** -- Forge's direct filesystem installer remains the delivery surface. A reusable
  Codex plugin artifact is separate distribution work.

## Ratified Phase 0 decisions

1. **Card shape.** Keep Axis 1 in this card with reviewable compiler, installer/tracking, and migration commits; do not
   reopen the closed `epic_global_forge_runtime`.
2. **Authoring source.** Portable skills use one typed manifest plus neutral templated content/resources. Generated
   Claude and Codex packages are adapter outputs, never independently edited sources. Claude-only skills may retain the
   legacy direct package shape until they gain another runtime.
3. **Generated artifacts.** Compilation is deterministic and installer-facing. Copy mode writes compiled bytes; symlink
   mode may point only to a stable Forge-managed compiled cache, never a temporary directory.
4. **Adapter contract.** One typed adapter interface owns frontmatter, names, invocation policy, task arguments,
   package-relative resource/script resolution, model-family selection, exploration/subagents, user interaction, and
   Forge CLI bindings. Missing required bindings fail compilation. Packaged executables use their shebang or OS entry
   point; adapters do not silently force Bash.
5. **Runtime/scope model.** `RuntimeSpec.skill_scopes` is independent of `install_scopes`. Claude supports
   user/project/local; Codex supports user/project only. Codex local is an explicit unsupported package result, never a
   write to shared `.agents/skills`.
6. **Names and invocation.** Claude keeps `forge:<skill>` and `/forge:<skill>`; Codex emits directory-matching `<skill>`
   and uses explicit `$<skill>` task text. `disable-model-invocation` maps only to the matching `agents/openai.yaml`
   implicit-invocation policy. Neutral sources express this policy only through the typed portable field; raw
   adapter-owned invocation fields are invalid.
7. **Delivery and duplicates.** Forge remains the direct installer. It never overwrites or deletes a same-name Codex
   skill. Duplicate discovery cross-references valid tracking rows with one path-normalization rule: an untracked match
   gets remove-or-rename guidance, while a match managed by another Forge scope stays a conflict whose recovery names
   that scope's exact disable command. An automatic new target may skip; an explicitly requested or already-managed
   target fails for recovery.
8. **Migration tranches.** Prove `challenge` task arguments and `smoke-test` packaged-script/install-home bindings, then
   migrate `review`, `review-docs`, and `understand`. `walkthrough`, `qa`, and the four Claude-worker workflow frontends
   remain Claude-only in this card.
9. **Probe fact (Codex CLI 0.144.5).** Codex loads the selected `SKILL.md` by absolute path, exposes no skill-root
   environment variable, and executes a literal `bash scripts/x.sh` from the repository CWD. A binding that tells Codex
   to resolve `scripts/x.sh` against the loaded `SKILL.md` parent produces and executes the correct absolute path.

## Blast radius / risks

- **Installer + `installed.json`** -- durable state; per-runtime targets must sync/disable cleanly (integration-test the
  Codex install path).
- **Duplicate discovery within Codex's own scan chain** (NOT cross-runtime double-fire): a skill in more than one of
  Codex's scanned dirs does **not** merge -- duplicate `name`s become ambiguous selectors. Install to exactly one Codex
  scope and track it (cf. `design_appendix.md` §C.5).
- **Scope-privacy leak** -- Forge's `local` (personal, gitignored) has no Codex skill home; mapping it onto the shared
  `.agents/skills` would publish a personal skill into the team/committed dir. Codex skills are user + project only (see
  target shape 4).
- **Build correctness is now load-bearing** -- a bad compose degrades the Claude experience or ships an invalid Codex
  package; gate on spec validation (`name`, the closed frontmatter allowlist, `allowed-tools` format) over the whole
  built package + a Claude smoke run.

## Metric / falsifiable prediction

After layers 1--3 for the approved portable tranche, `forge extension enable` on a Codex machine makes `challenge`,
`smoke-test`, `review`, `review-docs`, and `understand` discoverable and explicitly invocable as Codex-native skills --
no `claude -p`. **The gate validates the whole built package** (`SKILL.md` + `resources/` + `references/` + `scripts/` +
`agents/openai.yaml`): falsifiers -- a Codex package leaks `${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`,
`subagent_type: "Explore"`, or a Claude-only top-level frontmatter key; `name` fails spec validation; a packaged script
depends on process CWD; or the skill is absent from Codex discovery. The four fan-out frontends remain Claude-only until
Axis 2; that is an explicit boundary rather than a Codex-native claim.

## References

- Skills: neutral `src/skills/{challenge,smoke-test,review,review-docs,understand}/{forge-skill.yaml,content.md}` plus
  six legacy Claude-only `SKILL.md` packages; rubric coupling `src/skills/understand/resources/docs-openai.md:51-58`,
  `src/skills/review/resources/code-openai.md:52-59`; model-family binding `src/skills/review/content.md:36-48`;
  authoring guide `src/skills/review/references/skills-writing-guide.md:15-61,361-374,823-826,1300-1314` (Forge
  authoring contract, extended fields, packager reject, Claude variables).
- Install: `src/forge/install/installer.py` (`_plan_runtime_skill_packages`), `src/forge/install/models.py`
  (`InstallModule.SKILLS`), `src/forge/install/codex_hooks.py` (Codex settings pattern; installs no skills).
- Engine (Axis 2): `src/forge/review/engine.py` (`run_claude_session`); `src/forge/core/invoker/__init__.py`.
- Registry: `src/forge/core/runtime/registry.py` (`RuntimeSpec.skill_scopes`).
- Design: `docs/design_workflows.md` §3, §4.5; `docs/design_appendix.md` §C, §C.5, §C.6.
- External (verified 2026-07-06): `agentskills.io/specification` -- closed frontmatter allowlist (`name`==dir;
  `description`; `license`; `compatibility`; `metadata`; `allowed-tools` space-separated + experimental; **no**
  `when_to_use`) plus a Validation section; `developers.openai.com/codex/skills` (`.agents/skills` /
  `$HOME/.agents/skills` discovery, no personal-per-project scope; `[[skills.config]]` disable; `agents/openai.yaml`
  `policy.allow_implicit_invocation`).

## Second-review boundary hardening (2026-07-17)

The follow-up review found real fail-open edges beyond the earlier package-root substitution fix. The implemented
remediation now:

- propagates batch-disable failure to callers and makes complete uninstall preserve tracking and `$FORGE_HOME` until
  every tracked extension is removed;
- rejects symlinked source/package roots and applies the checkout's Git eligibility set throughout skill discovery and
  file loading, so ignored packages or bytes cannot enter the stable compiled cache;
- strictly cross-validates package rows against the canonical installation file ledger and reports dangling tracked leaf
  symlinks as missing;
- keeps invocation policy under typed neutral authority, honors executable entry points, makes Codex's `openai` host
  family authoritative, hardens negative Codex probes against false passes, and documents exact tracking-row discovery
  in lifecycle help.

The final affected compiler/cache/lifecycle/CLI/setup/regression suite passed `381` tests. QA parses as v1.0.30 / 589
assertions, and strengthened real-Codex policy/script stages passed on codex-cli 0.144.5. Broad verification passed, and
PR #107 merged to `main` on 2026-07-17.

## Closeout

Implementation was accepted after human review and shipped through PR #107. This card moved to `done/` on 2026-07-17.

### Implemented outcome

- Forge now compiles one typed neutral source into deterministic Claude and Codex packages. `challenge`, `smoke-test`,
  `review`, `review-docs`, and `understand` ship for both runtimes; the other six bundled skills remain explicitly
  Claude-only at the approved Axis 1 boundary.
- Runtime capabilities, scope/profile planning, duplicate discovery, schema-v2 tracking, status, enable/sync/disable,
  copy/symlink modes, clean-package data, and project compatibility now operate per runtime package. Codex supports user
  and project scopes; local scope remains an explicit refusal.
- Whole-package validation fails closed on runtime-token leaks, unsafe references, source/cache symlinks, unusable
  script modes, malformed runtime metadata, and undeclared capability bindings. Installer failures restore new files,
  settings, ownership sidecars, and tracking retryability.
- Architecture, CLI, end-user, manual-testing, QA, walkthrough, and skill-authoring guidance now describe the same
  runtime and operator contracts.
- Review remediation made re-enable runtime selection ownership-aware, distinguished valid cross-scope Forge provenance
  from untracked duplicates, prevented a user package from shadowing tracked project/local packages outside the current
  directory chain, made status recovery executable from any CWD, and rejected conflicting manifest authority. The wheel
  integration now installs the built artifact without mutating the session container's checkout.
- PR review remediation treats package roots and descendant directories as non-symlink ownership boundaries. Status
  reports substitutions as invalid, and enable, sync, apply, rollback, and disable fail before following them.

### Verification

- Initial focused adversarial acceptance: `142 passed`; review-remediation affected suite: `302 passed`; PR symlink-
  boundary suite: `216 passed`. Full unit suite: `8134 passed, 1 skipped, 117 deselected`; full regression suite:
  `515 passed`.
- Initial Docker installer lifecycle: `20 passed`; review-remediation lifecycle: `2 passed`, including an offline-built,
  target-installed wheel that exercised both Claude and Codex enable -> sync -> status -> disable ownership.
- The seven-stage Codex probe and actual compiled user/project `$smoke-test` invocations passed on `codex-cli 0.144.5`;
  each compiled Codex smoke run reported `8/8` from an unrelated or nested CWD.
- Clean wheel project/Codex and sdist user/all-runtime enable -> status -> doctor -> sync -> disable lifecycles passed
  from isolated installs. Claude smoke reported `11/11`, Codex smoke `8/8`, and no bytecode, symlink,
  checkout-reference, compiler-source, or post-disable ownership leak remained.
- The second-review gates passed: `8,158` unit tests with one skip, `521` regression tests, `2` targeted Docker
  lifecycle tests, `uv build`, `make pre-commit`, `make pre-commit-md`, and `git diff --check`. The current QA parser
  reports v1.0.30 / 589 assertions; walkthrough-state reports `93 passed`, and `docs/design_appendix.md` remains below
  its limit at 29,987 tokens.
- Environment notes: one unit test remained skipped; clean build needed approved access to the shared uv cache, while an
  isolated uv cache hit the known macOS `dynamic_store` panic. Codex also printed its non-blocking PATH-alias warning.

### Durable lessons promoted at closeout

- Runtime selection and persisted package ownership are separate state: automatic re-enable and sync retain the managed
  runtime set when a binary is temporarily absent, while explicit narrowing preserves omitted package ownership.
- Packaged script execution is distinct from prose/resource loading: bind it from the selected skill root and require an
  owner-readable, owner-executable packaged file.
- Validate neutral sources and every emitted package as whole trees; exclusions are documentary-only, and compiler/cache
  ownership must never follow untrusted symlink parents or lock files.
- Commit tracking last. A post-write failure must restore newly created files plus settings ownership state, while an
  unchanged-file refresh preserves the original installation timestamp.
- Codex duplicate discovery is an ownership boundary: `--force` never adopts or deletes an untracked same-name package.
- Runtime package directories are ownership boundaries: validate each directory entry with `lstat` near every mutation;
  permit symlink mode only at tracked leaf files.
- Skill source eligibility is a compiler input, not just an installer-copy filter: reject symlinked roots and require
  both a leaf alias and its contained target to be eligible before reading or caching either path.
- Treat `skill_packages` as a strict projection of the canonical file ledger. Empty, outside-root, unbacked, duplicate,
  or multiply claimed package paths are corrupted state and must fail before teardown mutates files or tracking.
- The content-addressed compiled-skill cache currently has no eviction. Symlink-mode installs reference digest
  directories directly, so any future cleanup must prove a digest is not the target of a tracked install before removing
  it.

These reviewed invariants were promoted in compact form to the board's [implementation notes](../../impl_notes.md).
