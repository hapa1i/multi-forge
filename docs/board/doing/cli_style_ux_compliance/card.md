# cli_style_ux_compliance -- fix CLI style-guide violations + close help/consistency UX gaps

**Lane**: `doing/` -- active Step 3 coordinator/index on branch `feat/cli-style-ux-compliance`. The items are
**independently shippable** and span different review risk, so this card is not one monolithic implementation unit:
execute selected rows as focused slices grouped by review concern in [`checklist.md`](checklist.md).

**Scheduling status (2026-07-03)**: **A1 shipped in PR #70** and is archived at
[`docs/board/done/cli_error_stream_stderr/`](../../done/cli_error_stream_stderr/card.md). **Step 2** shipped in PR #71
and is archived at [`docs/board/done/backend_runtime_cleanup/`](../../done/backend_runtime_cleanup/card.md), including
the backend-help slice of B1. **Step 3 is active**: resume cli_style for A2/A4/A5, B2-B5, C. **A1 correction
(AST-verified 2026-07-02):** this row's grep model was wrong -- there were **0 bare `print_error*` calls** (so the
default flip fixed no current site; it was a forward guard), **240** (not 173) `console=console` explicit-stdout
overrides, and a missed **handler-default** gap (`handle_session_error` resolved to stdout at `output.py:108`, 11 bare
sites). The shipped card owns the corrected root strategy and verification.

**Origin**: full-CLI audit, 2026-07-01. A 19-unit parallel fan-out (one auditor per command group + 4 cross-cutting
lanes) enumerated all **135 commands/subcommands** via live `forge ... --help`, checked each against four dimensions
(style-guide compliance, help sufficiency, missing examples/tips, cross-command consistency), then a per-unit
**adversarial verifier** tried to *refute* each finding against the live help, source, the style guide's own exception
list, `docs/board/impl_notes.md`, and the guard tests. 90 candidates -> **63 survivors** (27 refuted, 30%). Every
high-severity survivor was then independently re-verified against code (file:line) on the current checkout before this
card -- which **corrected two auditor claims** (see [Provenance](#provenance)).

**Type**: single **batch** card, deliberately **not an epic**. The items share a *theme* (CLI-surface correctness +
polish), not a shared contract, sequencing decision, or code seam (`board_contract.md` epic test). Batch A is one
coherent bug family; B/C are grouped by risk. Coupling notes under [Sequencing & coupling](#sequencing--coupling).

**Relation to sibling cards**: distinct file surfaces from `doing/accidental_complexity_cleanup` (that card removes dead
code + duplication; this fixes output routing + help text) and `proposed/session_op_layer_extraction` (that restructures
the Claude launch path). One overlap: item **A2** edits a help string in `session_lifecycle.py`, which
`session_op_layer_extraction` will refactor -- see [Sequencing & coupling](#sequencing--coupling).

**References**: `docs/developer/cli_style_guidelines.md` (the authority every Batch-A item cites, by section);
`docs/developer/coding_standards.md` §5 (research-preview clean-break rules -- Batch C relies on these);
`docs/board/impl_notes.md` ("Unified backend: source catalog invariants" -- the source-id vs runtime-instance-id
distinction that constrains item B1).

**Addendum (maintainer review, 2026-07-01)**: a manual review pass expanded the card after code-verification. **A1 was
re-scoped from "~37 sites" to systemic** (a whole-CLI sweep: only ~95 of ~400 error paths route to stderr; the fix is to
flip the `print_error` default, not hand-edit call sites). **A5** (the `forge logs` read/destructive split) and **B5**
(`session lane set` lane discovery + raw `LaneError`) were added -- both missed by the original fan-out. **B1** gained
three verified backend traps (the group example teaches an adapter id to source-id leaves; `show`'s only example is a
runtime instance; `_source_record` emits `backend_id == source_id`). All addendum items were checked against source
file:line.

---

## Why (the audit's thesis)

The `forge` CLI surface is largely compliant -- the 30% refutation rate reflects a mature surface where many apparent
"violations" are documented-intentional (`proxy` has no `reset` by design; `telemetry activity [session]` uses a
positional correctly; `session reset` is `--yes`-exempt). The real defects cluster into a clear signature:

1. **One rule broken systemically, hiding behind a green test.** The single largest theme is *errors/diagnostics leaking
   to stdout instead of stderr* (`cli_style_guidelines.md` "Output Streams"). A whole-CLI sweep (A1) shows only **~1 in
   4** error paths reaches stderr (~95 of ~400 calls). It survived because the guard (`test_output_streams.py`) only
   exercises **pre-flight** errors -- which fire *before* the `--json` branch and route through `err_console` correctly
   -- and never the **in-branch** exception paths that hit the bug. A passing test masks a real scripting-breakage:
   `forge ... --json | jq` chokes when an error object lands in the data stream.
2. **Help-text drift and undefined identifiers.** New users cannot tell what several commands do or what id to pass. The
   archetype (the reason this audit was requested): a command needs a `source-id` but its help never defines what a
   "source" is or where to find one.

Batch A is the genuine-bug set (fix now). Batch B is a pure help/docstring pass (zero behavior change). Batch C are
three small research-preview breaking changes (batch separately).

---

## Batch A -- compliance bugs (High confidence, verified file:line) -- do first

### ~~A1 -- Errors leak to stdout, not stderr~~ (**shipped via PR #70**)

`cli_style_guidelines.md` "Output Streams" (lines 122, 146): *results (incl. all `--json`) -> stdout;
diagnostics/warnings/errors -> stderr*, and errors "that must not pollute stdout pass `console=err_console`." **Verified
scale (whole-CLI sweep, not the auditors' file-scoped list):** across `src/forge/cli/*.py` only **~95** error/diagnostic
calls route to `err_console` (stderr); **~311** pass a local `console` that is a stdout `Console` (44 module/func-level
`console = Console(width=200)` constructions, none `stderr=True`). So **~1 in 4** error paths reaches stderr. This is
partly a *known deferred migration* -- `err_console` was added in the Slice 11 recovery-output work and the
`print_error` default was deliberately left on stdout ("flipping ~71 bare call sites -- out of scope" at the time) --
but the Output Streams rule is unambiguous, and the scripting-breaking subset is live today. Three families:

| Family                                                      | Pattern                                                                      | Verified sites                                                                                                                                                                                                                                            |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1a: `--json` error -> stdout** (must-fix; breaks `\| jq`) | `click.echo(json.dumps({"error"\|"routing_error": ...}))` with no `err=True` | **13**: `activity.py:58`, `auth.py:358,495`, `gc.py:122`, `policy.py:665,837,872,1606`, `proxy.py:1700,1709`, `session_manage.py:783,789`, `workflow.py:197`                                                                                              |
| **1b: human `print_error` -> stdout** (systemic)            | `print_error(..., console=<local stdout console>)`                           | **~253** across most modules -- e.g. `proxy.py` **27** (`proxy set` errors, `:883`), `session_manage.py` **21** (`session delete`, `:125`), `policy.py` **17**, `config_cmd.py` **14** (`config set`, `:123`), `logs.py` (`:265,270`), `backend.py` **5** |
| **1c: `secho` red -> stdout**                               | `click.secho(..., fg="red")` w/o `err=True`                                  | **4**: `auth.py:191,396,505,508` (note `auth.py:182` gets it right -- copy-paste miss)                                                                                                                                                                    |

**Status**: shipped via PR #70; closeout and verification live in
[`done/cli_error_stream_stderr`](../../done/cli_error_stream_stderr/card.md). The implementation used the corrected
AST-derived root strategy, kept JSON error objects on stderr with `err=True`, and added guards for stdout overrides,
split continuations, red diagnostics, and in-branch `--json` errors.

**Original action** (kept for provenance):

- **Flip the default.** Change `print_error` / `print_error_with_tip` in `output.py` to default their `Console` to the
  shared `err_console` (stderr), then audit the small set of genuinely-*informational* stdout uses and pass an explicit
  stdout console there. One change closes the systemic 1b gap; hand-editing ~253 sites is the wrong lever. Verify
  against the ~44 local `Console(width=200)` constructions (some tables legitimately need width-200 on **stderr** ->
  `Console(stderr=True, width=200)`).
- **1a regardless:** add `err=True` to the 13 JSON sites (JSON error object on stderr, stdout empty, exit non-zero --
  matches the compliant `proxy.py:135` / `session_manage.py:461`).
- **1c:** add `err=True` to the 4 `auth.py` `secho` lines.
- **Close the guard gap (same PR).** `test_output_streams.py` only trips *pre-flight* errors (which fire before the
  `--json` branch and already route to `err_console`); extend it to trigger *in-branch* exceptions and assert clean
  stdout, or every future occurrence re-slips through a green test. If the default is flipped, add a guard that a bare
  `print_error()` lands on stderr.

### A2 -- Leaked ANSI artifact in `forge session start --model` help (trivial)

`session_lifecycle.py:1189` -- the help string literally contains a stray bold marker: `...claude-sonnet-4-6[1m])`,
which renders verbatim in `--help`. One-character fix (delete `[1m]`).

### A3 -- `forge policy enable` warn-and-exits-0 on missing input (**shipped in S3**)

`policy.py:275-278` -- with no `--bundle`, prints a yellow `Warning:` and `return`s (exit 0). Violates "Leaves fail
loudly on missing required input." **Resolution (2026-07-03):** terminal `forge policy enable` fails loud unless
`--bundle` is provided. The planned restore-from-intent behavior belongs to the `%policy enable` dispatcher, not this
terminal CLI leaf.

### A4 -- `forge search clean` lacks `--json`

Its sibling destructive command `forge clean` exposes `--json`; `search clean` (`search.py:381`) does not. Add `--json`
(dest `as_json`) with a stable preview/deleted-count shape matching `forge clean`. Sibling-parity + scriptability gap.

### A5 -- `forge logs` conflates a read surface with a destructive flag; split into a group

Two coupled defects on the same leaf (`logs.py`):

- **Destructive `--clean` dodges the destructive-verb shape.** `logs.py:247` -- `--clean` is an `is_flag` that
  *immediately* deletes log files (`logs.py:275` `if clean: _clean_logs(...)`); there is **no `--yes`** and **no
  preview-default**, and the help actively teaches it (`forge logs --clean # Remove all log files`). It only escapes
  `test_clean_verbs_preview_by_default` because the guard keys on a leaf *named* `clean`, not a `--clean` flag -- but
  from the user's shoe it is still "clean logs."
- **No `--json` on a read/status surface.** `forge logs` shows file locations, retention, and counts (`_show_logs`), yet
  exposes no `--json` (`logs_cmd(clean, older_than)` has no `as_json`). The read-leaf JSON guard misses it because the
  guard keys on names like `list`/`show`/`status`.

**Recommended fix (resolves both at once):** promote `logs` to a group with two leaves -- `forge logs show [--json]`
(read/status, stable JSON shape) and `forge logs clean [--older-than N] --yes` (destructive, previews by default). This
satisfies groups-earn-depth (2 leaves), gives the read surface its `--json`, and puts the destructive path behind the
standard `clean`-verb shape + guard. Clean break: `--clean`/`--older-than` flags on the bare `logs` leaf are removed.
(`logs` is currently in `_EXEMPT_SUBCOMMANDS`/`_SESSION_CLEANUP_EXEMPT` in `main.py` -- keep the exemption on the
group.)

---

## Batch B -- help & consistency doc-pass (pure `help=`/docstring edits, no behavior change)

### B1 -- Undefined identifiers (the "source_id needed but source not defined" archetype)

**Status (2026-07-03)**: the backend help/definition slice shipped via
[`done/backend_runtime_cleanup`](../../done/backend_runtime_cleanup/card.md): the `model backend` group defines the
then-current source-id vs runtime-instance-id vs adapter split, the backend examples use valid id spaces, `reconcile`
mentions `forge model backend list` for source ids, and the source-row `backend_id == source_id` JSON shape is
documented at the emitters. **C2 draft decision:** revise public CLI terminology toward backend/backend-instance
language, but keep the deeper storage/domain migration out of this UX card; that migration is parked in
[`todo/backend_instance_identity_model`](../../todo/backend_instance_identity_model/card.md). That parked domain card
does **not** close C2: the public wording pass must either ship in this card or be explicitly deferred to a separate
public-wording follow-up before this card moves to `done/`.

| Command(s)                                                                                      | Problem                                                                                                                                                                                                                                                                                                                                                                                                                                                     | Action                                                                                                                                                                       |
| ----------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `model backend` group                                                                           | Metavars for the id argument differ (`show BACKEND_ID`, `test-auth`/`reconcile SOURCE_ID`, `start`/`stop SOURCE_OR_ADAPTER`, `create`/`delete ADAPTER`) **and** the help never defines the id-spaces. **NOTE (verified):** this is *not* pure drift -- the variance encodes a real distinction (source-only vs source-or-adapter vs adapter-only; `show` also accepts a runtime-instance id like `litellm-4000`). Do **not** blindly rename to `SOURCE_ID`. | Make each metavar *communicate its accepted id-space precisely and consistently*, and define "source id vs runtime-instance id vs adapter" once in the `backend` group help. |
| `model backend reconcile`                                                                       | `--request-id` help references `<source-id>` but never says what it is or that `forge model backend list` shows them                                                                                                                                                                                                                                                                                                                                        | Clarify: "...scoped to the SOURCE_ID positional; run `forge model backend list` for source ids."                                                                             |
| `session fork PARENT`, `session transfer ... PARENT`                                            | `PARENT` undefined -- name or UUID? auto-resolves from `$FORGE_SESSION`?                                                                                                                                                                                                                                                                                                                                                                                    | Document the accepted forms in help.                                                                                                                                         |
| `memory track`/`passport ... PATH`                                                              | `PATH` undefined -- file/dir/repo-relative?                                                                                                                                                                                                                                                                                                                                                                                                                 | Add metavar clarity + example.                                                                                                                                               |
| `session show [SESSION_ID]` vs `policy shadow show [SESSION]` vs `telemetry activity [SESSION]` | Same concept, two metavar names                                                                                                                                                                                                                                                                                                                                                                                                                             | Standardize the metavar spelling.                                                                                                                                            |

**Additional backend naming concern (surfaced 2026-07-02):** `source id` is technically correct in the code
(`ModelSource.id`), but `source` is not a first-class CLI noun. There is no `forge model source ...` command; users
encounter these ids through `forge model backend list`, `test-auth`, `start`, `stop`, and `reconcile`. Treat bare
`SOURCE_ID` / "source id" wording as an internal vocabulary leak unless the help defines "source" inline as the upstream
model endpoint/capacity unit shown by `forge model backend list`. The wording decision belongs here, not in individual
behavior cards such as `backend_runtime_cleanup`, which should follow whatever naming this batch chooses.

**C2 draft decision (2026-07-03):** use only first-class CLI nouns in the public surface. `runtime` is reserved for the
agent/frontend runtime (`codex`, `claude_code`). Under `forge model backend`, call configured inference targets
**backends**, concrete usable endpoints/processes **backend instances**, and implementation/config families
**adapters**. Remote backends are still instances conceptually: while Forge has only one configured singleton remote,
the backend name can also be its instance id; when Forge supports multiple remotes of the same kind, those remotes
should get distinct backend instance ids. For this card, C2 is a help/metavar/table/prose cleanup only: leave
internal/storage and JSON names such as `ModelSource.id`, `source_id`, `runtime_instance`, and
`BackendInstance.backend_id` unchanged. The underlying abstraction migration is intentionally split to
[`todo/backend_instance_identity_model`](../../todo/backend_instance_identity_model/card.md). **Closure path:** after
review, C2 exits by shipping the public wording pass here, or by creating/linking a separate follow-up for that wording
pass and marking C2 deferred. The deeper identity-model card is only the architecture/schema follow-up.

**Verified backend traps (sharper than the table row -- these actively fail, not just confuse):**

- **The group example teaches the wrong id for its own leaves.** `backend.py:58` (group help) uses `litellm` (an
  **adapter**) as the example, but `test-auth` (`:736`) and `reconcile` (`:977`) take a **catalog source id** --
  `forge model backend test-auth litellm` *fails*. `test-auth` has no leaf-level example. Fix: use a real source id in
  the example (e.g. `openrouter`), and add a leaf example to `test-auth`/`reconcile`.
- **`show`'s only example is a runtime instance, never a source.** `backend.py:623` -- arg `BACKEND_ID`, sole example
  `forge model backend show litellm-4000` (an instance), though it accepts sources too. Add a source example.
- **JSON contract redundancy.** `_source_record` (`backend.py:314`) emits
  **`{"backend_id": source.id, "source_id": source.id, ...}`** -- both keys set to the same value for a source row. This
  is the literal "source_id defined as == backend_id" confusion in the machine contract. Decide whether both keys are
  load-bearing (downstream telemetry uses `backend_id`) or one is a leftover, and document the distinction; don't
  silently ship two names for one value.

### B2 -- Wording/terminology drift (cosmetic, but user-visible)

| Drift                             | Detail                                                                                                                                                             | Action                                                                    |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| `--json` help text                | >=5 variants across read leaves (`Output as JSON` / `Output structured JSON` / `Output raw JSON` / `Output records as a JSON array` / `Output the record as JSON`) | Pick one canonical form; only deviate where the format genuinely differs. |
| `workflow --check`                | 4 terminologies for the same gate (`results`/`verdict`/`verdicts`/`positions`), inconsistent phrasing                                                              | Unify the template, preserve the per-verb semantics.                      |
| `workflow panel --prompt`         | Missing the `(alternative to positional)` annotation its 3 siblings carry (`workflow.py:334`)                                                                      | Add it.                                                                   |
| `codex start` vs `session start`  | `--sandbox` = "sandbox **policy**" vs "sandbox **mode**"                                                                                                           | Align wording.                                                            |
| `memory shadows list/show/review` | `Scope for discovery` vs `Scope for shadow discovery`                                                                                                              | Unify.                                                                    |
| `extension sync/disable/status`   | `--scope` help is detailed on `enable` (local=gitignored, ...) but bare "Installation scope" on the siblings                                                       | Reuse the detailed text.                                                  |
| `model backend reconcile` tip     | `Use --request-id <id> or --remote-id <id>` deviates from the `Use --flag` tip form (`backend.py:1005`)                                                            | Reword to the guide's tip form.                                           |
| `config show --json`              | Help does not document the (stable) JSON shape                                                                                                                     | Document `{path, env_sources, config}`.                                   |

### B3 -- Thin one-liners / undocumented options / hidden enums

| Command                             | Gap                                                                                                                                             |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `model backend start`/`stop`        | No hint that `--port` is required for an *adapter* but optional for a *source id*; no example                                                   |
| `model backend show`                | `BACKEND_ID` accepts both `openrouter` (source) and `litellm-4000` (instance) -- help says neither                                              |
| `search query`                      | Doesn't say `TERMS` is a phrase query (AND/OR/phrase ambiguity)                                                                                 |
| `config set`                        | Help shows only top-level examples; the nested-key feature (`statusline.cost_mode=...`, `provider_trace.inject_provider_user=...`) is invisible |
| `session lane set`                  | Doesn't say whether `--runtime`/`--backend` are both-optional or which is required; no example                                                  |
| `memory shadows show/review --for`  | "official doc" + path format unexplained                                                                                                        |
| `workflow list-models --available`  | "ready" undefined (vs `unavailable`/`error`)                                                                                                    |
| `runtime preflight RUNTIME`         | Only `codex` valid, but no enum and no cross-ref to `runtime list`                                                                              |
| `memory track --writers`/`--intent` | Writer-spec format + intent purpose vague                                                                                                       |

### B4 -- Missing examples/tips (highest value)

Add an example to: `model backend start`/`stop` (source-vs-adapter + `--port`), `search query` (phrase syntax),
`workflow panel --context resume:<uuid>` (Forge name vs Claude UUID), `session lane set`/`clear` (consumer + backend
combos). Add actionable next-step tips on error/empty paths: `telemetry activity --json` currently drops the human-mode
"run `forge session list`" tip in JSON mode. The old `logs --older-than` validation tip was folded into A5/S2 with the
`logs clean` redesign.

### B5 -- `session lane set` gives no way to discover valid lanes, and the invalid-lane error is raw

`session_lane.py` -- `--runtime TEXT` / `--backend TEXT` (`:100,:115`) are free strings with no `click.Choice`, no enum
in help, and no discovery command; the group's single `claude-max` example is the only hint of a valid value. The error
paths are *asymmetric*: an invalid **consumer** yields a helpful tip, but an invalid **lane** just re-prints the raw
`LaneError` (`:141` `print_error(str(e), console=err_console)`; the message originates in `consumer_lanes.py:102`). So a
user trying `--consumer team_supervisor --runtime codex` (team-supervisor has **no** codex lane) learns it is invalid,
not what *is* valid. **Fix:** enumerate each consumer's declared lanes in the `set` help (or a `--list`), and make the
`LaneError` say "valid lanes for `<consumer>`: `<runtime/backend/model>`, ..." (the `Consumer.allowed_lanes` data is
already available at the call site). This is a help + error-message quality fix, not a logic change; the stream routing
here is already correct (`err_console`).

---

## Batch C -- small breaking changes (research-preview clean breaks; batch separately)

Each needs a changelog entry per `coding_standards.md §5` and is higher-friction than a help edit.

| #   | Change                                                                | Rationale / caveat                                                                                                                                                                                                                                                                                                                                                                                        |
| --- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | `telemetry activity --days N` -> `--period [today\|week\|month\|all]` | Sibling telemetry commands (`trace list`, `costs show`, `proxy audit`) all use `--period`. Align, or add `--period` and deprecate `--days`.                                                                                                                                                                                                                                                               |
| C2  | `model backend` positional metavar standardization                    | **Draft decision:** public terminology should say backend/backend instance/adapter and avoid unexplained `source` or overloaded `runtime`; implementation should stay help/metavar/table/prose-only. Exit by shipping that wording pass here or explicitly deferring it to a named public-wording follow-up. Storage/JSON/domain migration is separately split to `todo/backend_instance_identity_model`. |
| C3  | `--scope` value-set/ordering canonicalization                         | **Draft decision:** no global reorder. The observed value sets are semantic families (`workspace\|project\|all`, `project\|workspace\|all`, `project\|all`, `local\|project\|user`, `user\|project\|local`), not one accidental enum. Only normalize local drift inside a family.                                                                                                                         |

**C3 draft decision (2026-07-03):** do not force one canonical `--scope` order across the CLI. The verified orderings
map to different objects:

- `session list` / `forge clean`: `workspace|project|all` (workspace-default session/state cleanup).
- `memory shadows` / `session memory status`: `project|workspace|all` (project-default memory discovery).
- `search query`: `project|all` (no workspace scope exists for indexed-project search).
- `extension enable|sync|disable|status`: `local|project|user` (installation specificity).
- `codex status`: `user|project|local` (runtime-install reporting order, matching install tracking).

So C3 is likely record-only for this card unless a local help string drifts from its own family.

---

## Do not "fix" (refuted -- recorded so a future reader does not re-flag)

27 candidates were refuted by the verifier and are **correct as-is**:

- `proxy` has no `reset` verb -- documented partial-lifecycle exception (`cli_style_guidelines.md` editable-config
  table).
- `session reset` has no `--yes` -- documented exemption (it rewinds the override layer, deletes nothing).
- Positional `[session]` selectors on `session show` / `policy shadow show` / `telemetry activity` -- correct per the
  positional-vs-`--session` rule (session is each command's primary object).
- `telemetry activity [session]` / `costs show [proxy_id]` positionals -- correct-by-rule (each applies the rule to its
  own primary object; audited compliant 2026-06-23).
- The "consistent terminology across all commands" complaints where the guide states **no** such rule -- kept as B2
  polish (low), not compliance violations.

---

## Decisions from open questions

| Q                                                                                                                                                                       | Area          | Decision                                                                                                                                         |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| A3: make `policy enable --bundle` **required** (fail loud) or implement **restore-configured-bundles-from-intent** (the `design_workflows.md §3.6` "planned" behavior)? | policy        | Resolved 2026-07-03: fail loud in the terminal CLI; restore-from-intent stays with the `%policy enable` dispatcher.                              |
| B1/C2: is the `model backend` metavar variance worth a rename at all, given it encodes a real source/adapter/instance distinction?                                      | model backend | Draft resolved 2026-07-03: yes for public backend/backend-instance wording; no for opportunistic internal/storage/JSON renames in this UX slice. |
| C3: which `--scope` divergences are semantic (user vs workspace) vs cosmetic ordering?                                                                                  | scope         | Draft resolved 2026-07-03: semantic families; do not globally canonicalize. Only fix local drift inside a family if review finds any.            |

---

## Sequencing & coupling

- **This card is the active Step 3 coordinator, not one execution unit.** The rows span very different review risk:
  auth/config output routing, telemetry/money-path-adjacent commands, a `session --json` shape change (A4/B), the `logs`
  group redesign (A5), pure docs (B2), and clean-break removals (C). Execute selected rows as focused slices in the
  checklist grouped by review concern (for example, "A5 logs group", "Batch B help-text pass", "Batch C breaks") -- each
  with its own verification guard. The batch card stays the durable index while individual slices graduate out of it.
- **Batch A is independent and high-value.** A1 shipped with the guard-test extension in PR #70. A2/A4 shipped as
  trivial correctness fixes; A3 shipped as the fail-loud terminal-CLI path.
- **A3 \<-> the `accidental_complexity_cleanup` "WorkflowPolicy product boundary" item.** Both touch `policy enable`:
  this card's A3 fixes its warn-and-exit-0; that card decides whether `--bundle`'s `Choice(["tdd","coding_standards"])`
  should gain a `workflow` path. The shipped A3 fail-loud path must not preempt that card's demote-vs-graduate decision.
- **A2 \<-> `session_op_layer_extraction`.** A2 edits a help string in `session_lifecycle.py:1189`, which that card will
  refactor. It is a one-character fix -- land A2 first (independently), or let the refactor absorb it; do not block A2
  on the refactor.
- **Batch B is pure help/docstring edits.** Zero behavior change, no test risk beyond help-snapshot updates; ship
  anytime, in any order.
- **Batch C are breaking changes where code changes ship.** C1 shipped as a clean break. C2 should be a public
  help/metavar/table cleanup after review, while the deeper backend-instance abstraction is a separate todo card. If C2
  is not shipped here, it must be explicitly deferred to a named public-wording follow-up before closeout. C3 is likely
  record-only unless review identifies local drift inside a semantic scope family.

---

## Provenance (how to trust the classifications)

- **Independently re-verified** against source on the current checkout before this card. The re-verification **corrected
  two auditor claims**: the A1 `--json`-error cluster is **13 sites, not 14** (the auditors cross-counted one site
  across two units), and the `model backend` positional finding was **downgraded from "rename to SOURCE_ID" to a
  help/metavar fix** after confirming (`backend.py:623-993` + `impl_notes.md`) that the variance encodes a real id-space
  distinction.
- The guard-gap finding (A1) was confirmed by reading `test_output_streams.py`: its failure-path cases all trigger
  *pre-flight* errors that never reach the in-branch `click.echo(json.dumps({"error": ...}))`.
- 27 refuted candidates are listed above so they are not re-flagged.
- **A1 shipped check**: PR #70 added CI-facing guards for JSON error `err=True`, `print_error*(console=console)`, split
  error continuations, red diagnostics, and in-branch `--json` errors with empty stdout.

---

## Acceptance (per-item assertion pattern)

A slice is ticked only when: (a) the fix is verified by a focused test (for A1, a stream test that trips the in-branch
error path and asserts clean stdout + error on stderr; for A4/B-`--json`, a stable-shape test); (b) `make pre-commit`
clean; (c) for help-text items (Batch B), the rendered `forge <cmd> --help` shows the new text and any help-snapshot
tests are updated; (d) for Batch C breaking changes, a changelog entry names the replacement and old paths error via
Click.
