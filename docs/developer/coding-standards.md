# Coding Standards

Python coding conventions for Multi-Forge.

---

## 1. Code Organization

- **Public before Private**: Put public methods before private ones
- **Class Structure**: Constants -> class variables -> `__init__` -> public methods -> private methods
- **Module Structure**: Imports -> constants -> classes -> functions -> main block

---

## 2. Naming Conventions

- **snake_case**: Variables, functions, methods (`get_context`, `create_session`)
- **CamelCase**: Classes (`SessionManager`, `ModelCatalog`)
- **UPPER_CASE**: Constants (`MAX_TOKENS`, `DEFAULT_PORT`)
- **\_leading_underscore**: Private methods/variables (`_build_manifest`, `_cache`)

---

## 3. Type Safety

- **Type Hints Required**: Public functions must annotate params + return types
- **Type Narrowing**: Accept base types; narrow with `isinstance()` at runtime
  ```python
  # Good (LSP)
  async def process(self, config: BaseConfig) -> Result:
      if not isinstance(config, SessionConfig):
          raise TypeError(f"Expected SessionConfig, got {type(config)}")
      session_config: SessionConfig = config  # Now safe

  # Bad (violates LSP)
  async def process(self, config: SessionConfig) -> Result:
  ```
- **No TYPE_CHECKING workarounds**: Fix circular imports instead of `if TYPE_CHECKING:` blocks

---

## 4. Async/Await Pattern

- **No Event Loop Nesting**: Don't create loops to sync async (except app top-level)
- **Propagate async**: If a function uses async, make it async and `await`
- **Sync Wrappers**: API boundaries only, when necessary

---

## 5. Interface Changes

### Public surface (CLI commands/options, file formats, documented Python API)

Multi-Forge is currently a research preview, as stated in `README.md`. Until a command, file format, or Python API is
explicitly marked stable, prefer clear clean breaks over compatibility layers when the architecture benefits.

Research-preview breaking changes require:

- **Direct update**: update the command, schema, docs, tests, and examples to the new shape.
- **No default shims**: do not keep old aliases, adapters, or compatibility wrappers unless the proposal explicitly
  justifies them.
- **Helpful failure**: removed CLI commands/options and rejected stale durable state should fail with an actionable
  message that names the replacement command or reset path. A hidden tombstone command that only errors is acceptable
  when it prevents a generic "unknown command" dead end; it must not execute old behavior.
- **Clear reset/migration instructions**: tell users what to delete, recreate, or re-run.
- **Changelog entry**: document the breaking change and the reset/migration path.

Pre-OSS Forge installs are not supported in-place. New public `multi-forge` formats may intentionally reset ownership or
schema shape when a proposal calls for it.

Stable public surfaces, once declared stable or after a future 1.0 line, require:

- **Deprecation period**: at least one minor release with a deprecation warning before removal.
- **CLI aliases**: old command/option name kept as a hidden alias during the deprecation period when possible.
- **File format migration**: schema version bump + `forge migrate` command or clear upgrade instructions.
- **Changelog entry**: every breaking change documented with migration steps.

For stable deprecations, use visible CLI output (`click.echo("Deprecated: ...", err=True)` or Rich stderr) so users see
command changes before they break. For documented Python APIs, use `FutureWarning` or a project-specific warning with
`stacklevel=2`; `DeprecationWarning` is usually hidden outside `__main__`.

### Internal surface (module-to-module, private APIs)

Internal code not exposed to users follows a clean-break policy:

- **Update callers directly**: don't add adapters or compatibility wrappers.
- **No fallback logic**: when replacing a component, remove the old one.
- **Change interfaces atomically**: update all callers in the same commit.

### Tests

- **Delete obsolete tests**: when removing functionality, delete its tests (don't skip).
  - Removed code → delete test
  - Moved behavior → update test
  - Don't accumulate skips

### Boundary framework (reject vs degrade)

Three boundary types determine error-handling policy:

#### Internal boundaries (module-to-module)

- Reject invalid input. Raise specific exceptions.
- No warn+ignore. No silent defaults. No fallback logic.
- Proxy/resource lookups by config reference are internal — if a configured name can't resolve, the lookup raises. Only
  the outermost caller (hook adapter, CLI) decides whether that failure is blocking or a warning.

#### Forge-owned durable state

Forge-owned durable state = registries, indexes, manifests, session files — anything Forge writes to disk for later
reads.

- Version fields are mandatory on all persisted schemas.
- Read with strict deserialization. Unknown fields are corruption, not forward compat.
- Unsupported schema versions produce a clear error ("written by newer Forge — upgrade").
- The first OSS release may reset public state formats to version `1`, but version `1` must mean exactly the public v1
  shape. If pre-OSS files at the same path also used `1`, readers must distinguish by structure and either:
  - Reject with a clear reset/migration message for durable state, or
  - Discard and recreate runtime-only state (for example `active.json`).
- Research-preview (`0.x`) schema changes may be clean breaks: bump the version or document the reset, reject stale
  durable state with a clear message, and update docs/tests in the same change.
- Known legacy state that is intentionally ignored must still be detected and surfaced with a one-time notice or
  actionable warning. Do not let stale recognized config degrade into an apparently valid empty/default state.
- Stable schema changes require a version bump plus either:
  - An explicit migration command (`forge migrate`), or
  - A documented breaking release for intentionally non-migrated state.
- Never use `strict=False` or silent entry skipping on durable state.
- All schema breaks still need strict shape validation and clear changelog/reset instructions.

#### System boundaries (external data)

External data: user-edited config, LLM responses, subprocess output, Claude Code hook payloads.

- **Critical path**: Fail with a clear error message.
- **Best-effort (non-critical path)**: Warn and degrade to a safe default. Example: unknown key in user config YAML →
  warn, ignore. Example: supervisor parse failure → "aligned" (design.md §4.1.2 mandates fail-open for policy
  evaluations).

Best-effort patterns MUST:

1. Log at warning or debug level (never silent)
2. Document the degradation intent in a comment
3. Degrade to a safe default (not an arbitrary one)

---

## 6. Error Handling

- **Specific Exceptions**: Prefer `TypeError`/`ValueError` (not `Exception`)
- **Meaningful Messages**: Include context in error messages
- **Context Managers**: Use `with` for cleanup

---

## 7. Code Comments

AI-assisted coding often produces oververbose comments. Every comment must earn its place.

### The Rule: Comment the Why, Not the What

Code shows **how**. Comments explain **why**. Restating code is noise.

```python
# Bad — duplicates the code
user_count = len(users)  # Count users

# Good — explains WHY, not what
active_users = [u for u in users if not u.is_service_account]  # Service accounts skew metrics

# Good — documents a non-obvious constraint
def get_session_by_name(name: str) -> Session:
    """Look up session; fall back to partial match.

    Needed because Claude Code truncates session names to 40 chars
    in .claude/settings.json.
    """
```

### When to Comment

- **Non-obvious "why"**: Rules, constraints, performance
- **Workarounds and bug fixes**: Link issue; explain workaround
- **Unidiomatic code**: If you deviate, say why
- **External references**: Link specs/RFCs/docs
- **Invariants and assumptions**: Non-obvious constraints (caller holds lock, sorted, max 100 entries)
- **Lint/type suppressions**: Any `# noqa` or `# type: ignore` must include a reason.
  `# type: ignore[arg-type]  # Pydantic coerces str→Path at runtime`
- **TODO markers**: `# TODO(#issue): ...` with context (not bare `# TODO`)

### When NOT to Comment

- **Obvious operations**: `i += 1`, `return result`, `self.name = name`
- **What the function signature already says**: Type hints + clear name > restating docstring
- **Commenting out dead code**: Delete it (git remembers). Includes debugging leftovers (`# print(...)`,
  `# import pdb`).
- **Apologetic comments**: `# This is a hack` / `# Sorry, this is ugly` — fix the code
- **Section separators**: `# ===== HELPERS =====` — use module structure, not ASCII art
- **Closing bracket labels**: `# end if` / `# end for` — if you need these, the block is too long; extract a function

### Docstrings

- **Public API**: Required. One-line summary; add detail only if name + signature aren't enough. Include
  Args/Returns/Raises when semantics aren't obvious from types (side effects, units, ranges, errors).
- **Private methods**: Optional. Skip if the name is self-explanatory. Add if the logic is non-trivial.
- **Modules**: Optional. Use if the module's purpose isn't obvious from name + contents.
- **Format**: Use imperative mood ("Return the session" not "Returns the session").

```python
# Good — tells you something the signature doesn't
def resolve_model(tier: str, family: str) -> str:
    """Map user-facing tier (haiku/sonnet/opus) to backend model ID.

    Falls back to family default if tier is missing. Raises ValueError
    if family is unknown (no silent degrade).
    """

# Bad — Args/Returns that restate type hints add nothing
def resolve_model(tier: str, family: str) -> str:
    """Resolve a model from a tier and family.

    Args:
        tier: The tier to resolve.
        family: The family to resolve.
    """
```

### AI-Generated Comment Hygiene

When AI generates code, watch for these comment anti-patterns:

- **Play-by-play narration**: Comment on every line explaining Python syntax
- **Redundant section headers**: `# Initialize variables` above three obvious assignments
- **Filler preambles**: `# First, we need to...` / `# Now let's...` — code speaks for itself
- **Docstrings that restate the function name**: `def create_session` → `"""Create a session."""` — delete this, it adds
  nothing
- **Over-qualifying with "Note:"**: `# Note: returns None if not found` — just say `# Returns None if not found`
- **Invented rationales**: `# for performance` / `# for safety` without evidence — delete unless verified

Strip these during review. Don't add comments to untouched code.
