<!-- prereq: 0.3, 5.1 -->

## 13. Policy (`forge policy`)

### 13.1 Policy Status

<!-- auto -->

```bash
# Clear policy overrides left by earlier sections (e.g. %policy disable in 9.x);
# overrides outrank intent, so a stale policy.enabled=false would mask 13.2's enable.
forge session reset 'policy.*' --session test-session-1 2>/dev/null || true

# Target the canonical QA session explicitly: $FORGE_TEST_REPO accumulates many
# sessions by section 13, so bare 'forge policy' would fail on session ambiguity.
forge policy status --session test-session-1
```

- [ ] Shows enabled/disabled state
- [ ] Shows active bundles (if any)
- [ ] Shows fail mode (if policy was previously enabled; omitted when never configured)

### 13.2 Enable TDD Enforcement

<!-- auto -->

```bash
# Enable TDD bundle
forge policy enable --bundle tdd --session test-session-1

# Verify
forge policy status --session test-session-1
```

- [ ] TDD bundle activated
- [ ] `tests-before-impl` and `no-skip-tests` rules listed

### 13.3 Enable with Permissive Mode

<!-- auto -->

```bash
# Enable TDD in warn-only mode
forge policy enable --bundle tdd --permissive --session test-session-1

# Verify
forge policy status --session test-session-1
```

- [ ] TDD in permissive mode (warns instead of blocks)

### 13.4 Enable Coding Standards

<!-- auto -->

```bash
forge policy enable --bundle coding_standards --session test-session-1

forge policy status --session test-session-1
```

- [ ] Coding standards bundle activated
- [ ] `no-type-checking` and `no-backward-compat` rules listed

### 13.5 On-Demand Policy Check

<!-- auto -->

```bash
# Create a second commit so HEAD~1 is valid
echo 'print("new")' >> src/main.py
git add -A && git commit -q -m "add code for policy diff test"

# Check a diff against policies
git diff HEAD~1 | forge policy check --bundle tdd --bundle coding_standards --diff

# Check with JSON output
git diff HEAD~1 | forge policy check --bundle tdd --diff --json

# A multi-file check must evaluate a later Python file rather than applying the
# first file's path to the whole diff.
cat >/tmp/qa-policy-multifile.diff <<'EOF'
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1,2 @@
 # Forge QA
+Harmless documentation.
diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1,2 @@
 print("new")
+if TYPE_CHECKING:
EOF
set +e
forge policy check --bundle coding_standards --diff --json \
  </tmp/qa-policy-multifile.diff >/tmp/qa-policy-multifile.json
MULTIFILE_RC=$?
set -e
test "$MULTIFILE_RC" -eq 1
jq -e '
  .files_checked == 2
  and any(.violations[]; .file_path == "src/main.py" and .rule_id == "coding_standards.no-type-checking")
' /tmp/qa-policy-multifile.json

# Check the independent single-file source mode from the installed wheel.
forge policy check --bundle coding_standards --file src/main.py --json \
  | jq -e 'has("passed") and has("clean")'

# Exactly one content source is required.
set +e
forge policy check --bundle coding_standards \
  >/tmp/qa-policy-no-source.stdout 2>/tmp/qa-policy-no-source.stderr
NO_SOURCE_RC=$?
git diff HEAD~1 | forge policy check --bundle coding_standards --file src/main.py --diff \
  >/tmp/qa-policy-two-sources.stdout 2>/tmp/qa-policy-two-sources.stderr
TWO_SOURCES_RC=$?
set -e
test "$NO_SOURCE_RC" -ne 0
test "$TWO_SOURCES_RC" -ne 0
rg 'Provide --file or --diff' /tmp/qa-policy-no-source.stderr
rg 'cannot be used together' /tmp/qa-policy-two-sources.stderr
rm -f /tmp/qa-policy-no-source.stdout /tmp/qa-policy-no-source.stderr \
  /tmp/qa-policy-two-sources.stdout /tmp/qa-policy-two-sources.stderr \
  /tmp/qa-policy-multifile.diff /tmp/qa-policy-multifile.json
```

- [ ] Evaluates every file in a diff against the specified bundles, including path-scoped rules after the first file
- [ ] `--json` produces structured output with `passed` and `clean` fields
- [ ] `--file` independently evaluates one installed source path
- [ ] Zero sources and `--file` plus `--diff` both fail before evaluation with actionable diagnostics

### 13.6 Supervisor CLI Surface

<!-- auto -->

```bash
# Verify CLI is wired up
forge policy supervisor evaluate --help

# Missing file produces clear error (exit 2)
forge policy supervisor evaluate -f /nonexistent/file.py -r 00000000-0000-0000-0000-000000000000 --json
echo "exit: $?"
```

- [ ] `--help` shows usage with `-f`, `-r`, `--json`, `--proxy`, `--timeout` options
- [ ] Missing file produces clear error and exit 2

### 13.7 Manual Supervisor Wiring (Planner -> Supervisor -> Executor)

<!-- prereq: 2.4, 4.2 -->

<!-- requires: api_key -->

<!-- human:guided -->

<!-- evidence: extended-exploratory -->

<!-- paid-operations: 5 -->

This is a hands-on live-Claude smoke test. Do the phases in order. The terminal commands are copy/paste blocks for the
container shell; the prompt blocks are for the Claude session that opens after each `forge session ...` command. If live
Claude launch is unavailable in this environment, mark this step `Skip` rather than inventing evidence.

**Phase 1: create an approved planner session**

```bash
cd $FORGE_TEST_REPO

forge session delete policy-planner --yes --force 2>/dev/null || true
forge session delete policy-supervisor --yes --force 2>/dev/null || true
forge session delete policy-executor --yes --force 2>/dev/null || true
rm -f src/supervisor_demo.py

forge session start policy-planner --proxy "$FORGE_QA_OPENAI_PROXY"
```

In Claude, type:

```text
/plan
```

Then paste:

```text
Skip the exploration step. Create a plan only. Do not edit files or run any write tools.

The exact approved plan should be:
1. Create `src/supervisor_demo.py`
2. Add:
   def greet(name: str) -> str:
       return f"hello, {name}"
3. Do not modify any other files

After showing the plan, wait for my approval.
```

When Claude shows the plan, paste:

```text
I approve this exact plan. Do not implement it in this session. Wait.
```

Then exit Claude:

```text
/exit
```

Back in the container shell, verify that Claude wrote a plan file:

```bash
ls ~/.claude/plans/
```

**Phase 2: promote a dedicated supervisor session**

```bash
cd $FORGE_TEST_REPO

forge session fork policy-planner --name policy-supervisor --no-launch
forge session resume policy-supervisor
```

In Claude, paste:

```text
Reply with this exact phrase: supervisor ready
```

Then exit:

```text
/exit
```

**Phase 3: fork a direct executor and wire the supervisor**

```bash
cd $FORGE_TEST_REPO

forge session fork policy-planner --name policy-executor --no-proxy --no-launch
forge policy supervisor set policy-supervisor --session policy-executor --supervisor-proxy "$FORGE_QA_OPENAI_PROXY"
FORGE_SESSION=policy-executor forge policy status
forge session resume policy-executor
```

In Claude, paste:

```text
Create the file `src/supervisor_demo.py` with exactly this content:

def greet(name: str) -> str:
    return f"hello, {name}"

Do not modify any other files. Do not add tests, docstrings, or imports.
```

After Claude finishes, exit:

```text
/exit
```

**Phase 4: inspect the result and run the one-shot supervisor check**

```bash
cd $FORGE_TEST_REPO

cat src/supervisor_demo.py
forge policy supervisor evaluate -f src/supervisor_demo.py -r policy-supervisor --json
echo "exit: $?"
```

- [ ] Planner and supervisor sessions launch successfully; the planner has an approved plan and the supervisor session
  materializes with a confirmed Claude session
- [ ] Executor forks planner with `--no-proxy`, `forge policy supervisor set` wires `policy-supervisor`,
  `forge policy status` shows `Supervisor: Configured`, and the executor implements the exact tiny planned file
- [ ] `forge policy supervisor evaluate -f src/supervisor_demo.py -r policy-supervisor --json` returns structured output
  for the real tiny task (expected: aligned / exit 0)

### 13.8 Disable Policies

<!-- auto -->

```bash
forge policy disable --session test-session-1

forge policy status --session test-session-1
```

- [ ] All policies disabled
- [ ] Status confirms disabled state

---
