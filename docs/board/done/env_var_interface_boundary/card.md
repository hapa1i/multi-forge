# Env-var interface boundary (`FORGE_SESSION` out of user vocabulary)

**Lane**: `done/`. Independent of `epic_global_forge_runtime` (no member link), but **sequence-sensitive to it**: land
before T4/T5/T6 author new user-facing strings (dispatcher messages, doctor extensions, migration output), so those
surfaces are born speaking "managed session" instead of needing a later sweep.

## Goal

Declare the `FORGE_*` launch environment an **internal launcher-to-runtime contract** and remove internal env-var names
from normal-flow user surfaces. The public interfaces for session targeting are command-specific session operands,
`--session <name>`, and ambient current-session resolution; the public env surface is an explicit, documented
classification table -- not whatever strings happen to leak into help text.

## Why

Normal-flow CLI surfaces currently teach users the wiring -- and three error messages give **unsupported advice**: "Set
FORGE_SESSION" suggests manually exporting a launch-owned variable, which puts an unmanaged Claude session into a
half-managed hybrid state the design never contemplates (`FORGE_SESSION` is set by `forge session start`/`resume`;
design.md §3.10: hooks use it as the authoritative session identity). The `--session` flag exists precisely so users
never touch the env var, yet the errors route users around the flag to the mechanism. Separately, no doc owns the
question "which `FORGE_*` vars is a user allowed to set?" -- `FORGE_HOME` is legitimately public (state relocation,
already in end-user docs), the T8 dev override will add another, and everything else is Forge-set wiring whose semantics
are still moving (T4's `FORGE_SESSION` short-circuit makes it *more* load-bearing). An explicit internal declaration
lets those semantics evolve without user-migration concerns (research-preview clean-break, coding_standards §5).

## Design

**1. Classification table (new, in design docs)** -- the deliverable that outlives the string sweep. Known families
(full inventory during execution; ~70 `FORGE_*` names in `src/`):

| Class             | Families                                                                                                                                                                                                                                                                                                                        | Rule                                                                                        |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Public            | `FORGE_HOME`; `FORGE_PROFILE`; T8's planned dev override                                                                                                                                                                                                                                                                        | User-settable, documented in end-user docs                                                  |
| Public diagnostic | `FORGE_DEBUG`                                                                                                                                                                                                                                                                                                                   | User-settable for troubleshooting/config override; allowed in diagnostic docs/help          |
| Internal wiring   | `FORGE_SESSION`, `FORGE_FORK_NAME`, `FORGE_PARENT_SESSION`, `FORGE_FORGE_ROOT`; `FORGE_DEPTH`; `FORGE_RUN_ID`/`FORGE_PARENT_RUN_ID`/`FORGE_ROOT_RUN_ID`; `FORGE_SUBPROCESS_*`; `FORGE_SIDECAR`/`FORGE_LAUNCH_MODE`; `FORGE_OMIT_INTERACTIVE_KEY`; `FORGE_CODEX_PROXY_TOKEN*`; `FORGE_DEFAULT_PROXY_*`; `FORGE_PROXY_WIRE_SHAPE` | Forge-set; never named in normal-flow user surfaces; semantics changeable without migration |
| Test/QA harness   | `FORGE_TEST_REPO`, `FORGE_QA_*`, `FORGE_MANUAL_TEST_SYSTEM_PROMPT`, `FORGE_REV`                                                                                                                                                                                                                                                 | Never user-facing; out of scope                                                             |
| Classify at exec  | `FORGE_STATUS_TRUNCATE`                                                                                                                                                                                                                                                                                                         | Decide public/internal/diagnostic during inventory                                          |

**2. Tiered visibility rule (normal vs diagnostic).** Normal-flow surfaces (CLI help, errors, tips, assistant-facing `%`
help payloads) speak "current session" / "Forge-managed session" / `--session`. **Diagnostic surfaces stay explicit**:
`hook.md` troubleshooting (resolution-order tables, "confirm `FORGE_SESSION` is set"), debug logs
(`status_line.py:1653`), and doctor-class commands may name internals -- that is what they are for. Hidden means
*tiered*, not *secret*: the var stops being vocabulary, not inspectable.

**3. String rewrites (~8 sites + docs).** Error shape: "Run inside a Forge-managed session or pass --session <name>."
Help shape: "Target session (default: the current session)." Concept passages in end-user docs reword to "records the
session identity in the launch environment"; `hook.md` troubleshooting keeps explicit names.

**4. Guard test.** A style guard asserting internal env-var names do not appear in user-visible strings: terminal CLI
help/error/tip text **and** direct-command handled response payloads (`%h`, `%session show`, policy responses). The
classification table is the allowlist source. Precedent: `test_cli_rich_tips_go_through_output_helpers` /
`test_cli_rich_errors_go_through_print_error` (`tests/src/cli/test_output.py`) already pin literal-string boundaries to
`output.py`.

**Non-goals / no behavior change:** no env var is renamed, removed, or re-resolved; resolution order (`FORGE_FORK_NAME`
-> `FORGE_SESSION` -> UUID) is untouched; developer docs, board cards, code comments, and internal constants
(`_FORGE_SESSION_VAR` and kin) are out of scope. **Design docs are in scope only for the classification table and owned
cross-references.**

## Grounding (verified 2026-07-07)

- "Set FORGE_SESSION" advice: `core/ops/session.py:333`, `cli/memory.py:753,817`.
- Env-var-naming errors/help: `cli/session_memory.py:52,73,86,97`, `cli/session_lane.py:118`,
  `core/ops/session_context.py:202`. Direct-command emitted payloads are mostly clean today, but the guard should cover
  them because `%` responses are user-visible; `cli/hooks/direct_commands.py:120,182` are internal docstrings/comments
  and stay out of the string sweep.
- End-user docs: ~14 mentions -- concept passages (`end-user/README.md:17`, `session.md:86,287`, `skills.md:219`) vs
  troubleshooting material (`hook.md:41-58,307-353`, `session.md:44,891`) that must stay explicit.
- `FORGE_HOME` is already public in end-user docs (`proxy.md`, `manual_testing.md`).
- `FORGE_PROFILE` is already public in auth help/docs (`auth.py`, `authentication.md`); `FORGE_DEBUG` is already a
  public diagnostic config override (`config.md`, `runtime_config.py`).
- Guard precedent lives in `tests/src/cli/test_output.py`.
- ~70 distinct `FORGE_*`-looking tokens in `src/` include real env vars plus constants/headers (for example `FORGE_DIR`,
  `FORGE_*_HEADER`, `_FORGE_*` constants); execution must inventory real environment variables separately from names
  that only satisfy the regex. This table already drops three regex-only false positives: `FORGE_MAX_DEPTH` (a `= 2` int
  constant in `env.py`, not an env var), `WT_FORGE_LOG_SNAPSHOTS` (a walkthrough-skill shell var, not a `FORGE_*` name),
  and `FORGE_REV` (a QA container build-arg, filed under Test/QA harness).

## Risks

- **Over-hiding degrades debugging**: the exit-127 epic exists because hook-env wiring fails in practice; the
  diagnostic-surface exception list is load-bearing, not optional.
- **Guard false positives**: a future public var (T8) legitimately appears in help text; the classification table must
  be the guard's single allowlist source or the two drift.
- **T4/T5 drift**: new epic surfaces written before this lands re-leak the vocabulary; the guard catches it
  mechanically, but landing first is cheaper.

## Open questions

- Classification of the remaining diagnostic-ish toggle (`FORGE_STATUS_TRUNCATE`) -- public-diagnostic (documented,
  allowed in troubleshooting docs only) is the likely answer. `FORGE_DEBUG` is already classified as public diagnostic.
- Guard mechanics: literal scan of user-visible strings (the `test_output.py` pattern) vs AST walk over help/error call
  sites -- pick whichever survives f-string composition.
- Classification table home: `design_appendix.md` (reference material) with a pointer from design.md §3.4/§3.10, or a
  new appendix section -- decide at execution per documentation_guidelines' one-authority rule.

## Acceptance tests

| Test                                     | Fixture                                                      | Assertion                                                                                                                                                                                                                                                                         | Test File                                    |
| ---------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| Guard: no internal names                 | scan of CLI help/error/tip strings and `%` response payloads | internal-class env names absent outside allowlisted diagnostic sites                                                                                                                                                                                                              | `tests/src/cli/test_env_vocabulary.py` (new) |
| Error rewrite                            | no ambient session, no `--session`                           | error says "Forge-managed session" + `--session`; names no env var                                                                                                                                                                                                                | existing session/memory CLI suites (updated) |
| Help rewrite                             | `--session` flag help                                        | reads "default: the current session"; names no env var                                                                                                                                                                                                                            | same                                         |
| Unsupported advice gone                  | repo-wide string scan                                        | no user-visible string instructs setting `FORGE_SESSION`                                                                                                                                                                                                                          | guard test                                   |
| Classification table complete + accurate | design docs                                                  | every `FORGE_*` name read/written via `os.environ` in `src/` (per an `rg FORGE_ src/` inventory) is classified; regex-only tokens (`FORGE_MAX_DEPTH`, `FORGE_*_HEADER`, QA-shell vars) are excluded, not miscategorized as env vars; `FORGE_HOME` public, session family internal | doc check                                    |
| Troubleshooting stays explicit           | `hook.md` resolution/troubleshooting tables                  | env-var names retained in diagnostic sections                                                                                                                                                                                                                                     | doc check                                    |
