# The Complete Guide to Building Skills for Claude

## Contents

- [Forge repository authoring contract](#forge-repository-authoring-contract)

1. [Introduction](#introduction)
2. [Fundamentals](#chapter-1-fundamentals)
3. [Planning and design](#chapter-2-planning-and-design)
4. [Testing and iteration](#chapter-3-testing-and-iteration)
5. [Distribution and sharing](#chapter-4-distribution-and-sharing)
6. [Patterns and troubleshooting](#chapter-5-patterns-and-troubleshooting)
7. [Claude Code specifics](#chapter-6-claude-code-specifics)
8. [Resources and references](#chapter-7-resources-and-references)

## Forge repository authoring contract

This chapter is the source-authoring rule for skills under Forge's `src/skills/`. The rest of this document describes
the general Agent Skills package format and Claude-specific features; do not copy its generated-package examples into a
portable Forge source unchanged.

A skill intended for more than Claude Code is authored as one neutral source package:

```text
src/skills/<name>/
  forge-skill.yaml  # typed identity, runtime eligibility, capabilities, adapter metadata
  content.md        # neutral instructions; the compiler owns generated SKILL.md
  resources/        # shared auxiliary files, templated only when declared
  references/
  scripts/
```

The installer compiles that source into complete runtime packages. Generated `SKILL.md` files and `agents/openai.yaml`
are outputs and must not be checked in or edited as parallel sources. A package with no `forge-skill.yaml` may retain a
checked-in `SKILL.md`, but that is the legacy Claude-only bridge, not a portable skill.

Neutral Markdown expresses runtime behavior through declared capabilities. Wrap each marker below in two opening and two
closing braces; the delimiters are omitted here so this documentary file is not mistaken for a template input:

- `forge:task_arguments` for invocation text.
- `forge:resource_loading:path/to/file` for a read-only package-relative resource.
- `forge:packaged_script:path/to/script` for an executable bundled script. This is separate from resource loading
  because the runtime resolves and directly executes the installed file from an arbitrary working directory. Give the
  file executable mode and a shebang for its interpreter; do not assume the adapter wraps every script in Bash.
- `forge:model_family`, `forge:exploration`, `forge:subagents`, `forge:user_interaction`, and `forge:forge_cli` for the
  corresponding runtime behavior.
- Invocation policy is declared structurally in `forge-skill.yaml`; it is not handwritten into neutral content.

List every used capability in the manifest's `capabilities`. Shared `license`, `compatibility`, `metadata`, and
`allowed_tools` values belong in their typed manifest fields. Put genuinely Claude-only frontmatter such as
`argument-hint`, `effort`, or a Claude-tool-specific `allowed-tools` value under `claude_frontmatter`, but never declare
the same field in both places. Declare invocation policy once with `allow_implicit_invocation`; the adapter derives
Claude's `disable-model-invocation` and Codex's matching policy. The Claude field is forbidden in a neutral
`claude_frontmatter` block. Put optional Codex UI metadata under `codex_interface`. Runtime bindings stay in compiler
adapters, never in model-family resources; adding a runtime must not create files such as `code-openai-codex.md`.

The neutral-source and emitted-package gates scan the whole tree. Do not place `$ARGUMENTS`, `${CLAUDE_SKILL_DIR}`,
Claude tool names/invocation syntax, or other runtime-specific instructions in neutral content or shared auxiliaries.
`token_allowances` cannot suppress the neutral-source or Codex token gates. Use `runtime_excluded_files` only for
explicit Markdown documentary references under `references/` that do not belong in a runtime package; it is not a way to
hide scripts, resources, or incomplete neutralization. Unknown, undeclared, unbound, malformed, or leftover placeholders
fail compilation with a source path and recovery.

When Forge runs from a repository checkout, Git-tracked and unignored untracked paths form the source eligibility set
for package discovery and every compiler read. Keep ignored secrets, generated outputs, and whole ignored packages out
of skill inputs; a contained source symlink is usable only when both the link and its target are eligible.

Keep a skill Claude-only when its behavior has no reviewed runtime binding. Today that includes Forge's workflow
frontends whose engine still launches `claude -p` workers and the `walkthrough`/`qa` manual-test frontends. Portability
is an explicit eligibility decision backed by whole-package compile, discovery, and invocation tests.

---

## Introduction

A [skill](https://claude.com/blog/skills) is a set of instructions - packaged as a simple folder - that teaches Claude
how to handle specific tasks or workflows. Skills follow the [Agent Skills](https://agentskills.io) open standard, which
works across multiple AI tools. Instead of re-explaining your preferences, processes, and domain expertise in every
conversation, skills let you teach Claude once and reuse that guidance every time.

Skills are most useful for repeatable workflows: frontend design, research, document creation, and multi-step processes.
They pair well with Claude's built-in capabilities and with MCP integrations.

**What you'll learn:**

- Skill structure and writing guidance
- Patterns for standalone and MCP-backed skills
- Testing, iteration, and distribution

**How to use this guide:** For standalone skills, focus on Fundamentals, Planning and Design, and category 1-2. For MCP
integrations, read the "Skills + MCP" section and category 3. For Claude Code-specific features like subagent execution,
dynamic context injection, and permission control, see Chapter 6.

---

## Chapter 1: Fundamentals

### What is a skill?

A skill is a folder containing:

- **SKILL.md** (required): Instructions in Markdown with YAML frontmatter
- **scripts/** (optional): Executable code (Python, Bash, etc.)
- **references/** (optional): Documentation loaded as needed
- **assets/** (optional): Templates, fonts, icons used in output
- **agents/** (optional): Subagent prompts for delegating specialized tasks (e.g., grading, comparison, analysis)

### Core design principles

#### Progressive Disclosure

Skills use a three-level system:

- **First level (YAML frontmatter):** Always loaded in Claude's system prompt. Provides just enough information for
  Claude to know when each skill should be used without loading all of it into context.
- **Second level (SKILL.md body):** Loaded when Claude thinks the skill is relevant to the current task. Contains the
  full instructions and guidance. Keep under 500 lines; if approaching this limit, add hierarchy with clear pointers to
  reference files.
- **Third level (Linked files):** Additional files bundled within the skill directory that Claude can choose to navigate
  and discover only as needed. Scripts can execute without loading into context.

This progressive disclosure minimizes token usage while maintaining specialized expertise.

**Context budget:** Skill descriptions share a pool of approximately 2% of the context window (with a 16K character
fallback). If you have many skills enabled, they may exceed this budget. In Claude Code, run `/context` to check for
warnings about excluded skills. Override the limit with the `SLASH_COMMAND_TOOL_CHAR_BUDGET` environment variable.

#### Composability

Claude can load multiple skills simultaneously. Your skill should work well alongside others, not assume it's the only
capability available.

#### Portability

Skills work identically across Claude.ai, Claude Code, and API. Create a skill once and it works across all surfaces
without modification, provided the environment supports any dependencies the skill requires. Claude Code extends the
open standard with additional features like invocation control, subagent execution (`context: fork`), and dynamic
context injection -- see Chapter 6.

### For MCP Builders: Skills + Connectors

> *Building standalone skills without MCP? Skip to Planning and Design.*

If you already have a
[working MCP server](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop),
skills add the workflow layer: the steps, conventions, and guardrails Claude should follow when using those tools.

**How they work together:**

| MCP (Connectivity)                                            | Skills (Knowledge)                                 |
| ------------------------------------------------------------- | -------------------------------------------------- |
| Connects Claude to your service (Notion, Asana, Linear, etc.) | Teaches Claude how to use your service effectively |
| Provides real-time data access and tool invocation            | Captures workflows and conventions                 |
| What Claude can do                                            | How Claude should do it                            |

In practice, this reduces prompt variance, inconsistent tool use, and support overhead.

---

## Chapter 2: Planning and design

### Start with use cases

Before writing any code, identify 2-3 concrete use cases your skill should enable.

**Good use case definition:**

```
Use Case: Project Sprint Planning
Trigger: User says "help me plan this sprint" or "create sprint tasks"
Steps:
1. Fetch current project status from Linear (via MCP)
2. Analyze team velocity and capacity
3. Suggest task prioritization
4. Create tasks in Linear with proper labels and estimates
Result: Fully planned sprint with tasks created
```

**Ask yourself:**

- What does a user want to accomplish?
- What multi-step workflows does this require?
- Which tools are needed (built-in or MCP?)
- What domain knowledge or conventions should be embedded?

### Common skill use case categories

At Anthropic, we've observed three common use cases:

#### Category 1: Document & Asset Creation

Used for: Creating consistent output -- documents, presentations, apps, designs, code.

*Real example:* [frontend-design skill](https://github.com/anthropics/skills/tree/main/skills/frontend-design) (also see
[skills for docx, pptx, xlsx, and ppt](https://github.com/anthropics/skills/tree/main/skills))

"Create distinctive frontend interfaces with polished design. Use when building web components, pages, artifacts,
posters, or applications."

**Key techniques:**

- Embedded style guides and brand standards
- Template structures for consistent output
- Quality checklists before finalizing
- No external tools required - uses Claude's built-in capabilities

#### Category 2: Workflow Automation

Used for: Multi-step processes that benefit from consistent methodology, including coordination across multiple MCP
servers.

*Real example:* [skill-creator skill](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md)

"Interactive guide for creating new skills. Walks the user through use case definition, frontmatter generation,
instruction writing, and validation."

**Key techniques:**

- Step-by-step workflow with validation gates
- Templates for common structures
- Built-in review and improvement suggestions
- Iterative refinement loops

#### Category 3: MCP Enhancement

Used for: Workflow guidance to enhance the tool access an MCP server provides.

*Real example:*
[sentry-code-review skill (from Sentry)](https://github.com/getsentry/sentry-for-claude/tree/main/skills)

"Automatically analyzes and fixes detected bugs in GitHub Pull Requests using Sentry's error monitoring data via their
MCP server."

**Key techniques:**

- Coordinates multiple MCP calls in sequence
- Embeds domain expertise
- Provides context users would otherwise need to specify
- Error handling for common MCP issues

### Define success criteria

#### How will you know your skill is working?

These are aspirational targets - rough benchmarks rather than precise thresholds. Aim for rigor but accept that there
will be an element of vibes-based assessment. Anthropic is developing better measurement guidance and tooling.

**Quantitative metrics:**

- Skill triggers on 90% of relevant queries - *How to measure:* Run 10-20 test queries that should trigger your skill.
  Track how many times it loads automatically vs. requires explicit invocation.
- Completes workflow in X tool calls - *How to measure:* Compare the same task with and without the skill enabled. Count
  tool calls and total tokens consumed.
- 0 failed API calls per workflow - *How to measure:* Monitor MCP server logs during test runs. Track retry rates and
  error codes.

**Qualitative metrics:**

- Users don't need to prompt Claude about next steps - *How to assess:* During testing, note how often you need to
  redirect or clarify. Ask beta users for feedback.
- Workflows complete without user correction - *How to assess:* Run the same request 3-5 times. Compare outputs for
  structural consistency and quality.
- Consistent results across sessions - *How to assess:* Can a new user accomplish the task on first try with minimal
  guidance?

### Technical requirements

#### File structure

```
your-skill-name/
  |-- SKILL.md                # Required - main skill file
  |-- scripts/                # Optional - executable code
  |   |-- process_data.py     # Example
  |   |-- validate.sh         # Example
  |-- references/             # Optional - documentation
  |   |-- api-guide.md        # Example
  |   |-- examples/           # Example
  |-- agents/                 # Optional - subagent prompts
  |   |-- grader.md           # Example: evaluates assertions against outputs
  |   |-- comparator.md       # Example: blind A/B quality comparison
  |-- assets/                 # Optional - templates, etc.
      |-- report-template.md  # Example
```

#### Critical rules

**SKILL.md naming:**

- Must be exactly `SKILL.md` (case-sensitive)
- No variations accepted (SKILL.MD, skills.md, etc.)

**Skill folder naming:**

- Use kebab-case: `notion-project-setup`
- No spaces: ~~`Notion Project Setup`~~
- No underscores: ~~`notion_project_setup`~~
- No capitals: ~~`NotionProjectSetup`~~

**No README.md:**

- Don't include README.md inside your skill folder
- All documentation goes in SKILL.md or references/
- Note: when distributing via GitHub, you'll still want a repo-level README for human users -- see Distribution and
  Sharing.

### YAML frontmatter: The most important part

The YAML frontmatter is how Claude decides whether to load your skill. Get this right.

**Minimal required format:**

```yaml
---
name: your-skill-name
description: What it does. Use when user asks to [specific phrases].
---
```

That's all you need to start.

#### Field requirements

**name** (required):

- kebab-case only
- No spaces or capitals
- Should match folder name
- Max 64 characters
- Note: Claude Code treats `name` as optional (defaults to directory name), but include it for cross-platform
  portability

**description** (required):

- **MUST include BOTH:** what the skill does and when to use it (trigger conditions)
- Under 1024 characters (hard limit -- descriptions over this are truncated)
- No XML tags (< or >)
- Include specific tasks users might say
- Mention file types if relevant
- If omitted, Claude uses the first paragraph of markdown content

**license** (optional):

- Use if making skill open source
- Common: MIT, Apache-2.0

**compatibility** (optional):

- 1-500 characters
- Indicates environment requirements: e.g. intended product, required system packages, network access needs, etc.

**allowed-tools** (optional):

- Restrict which tools Claude can use without asking permission when this skill is active
- Example: `allowed-tools: Read, Grep, Glob` (read-only mode)

**metadata** (optional):

- Any custom key-value pairs
- Suggested: author, version, mcp-server
- Example:
  ```yaml
  metadata:
      author: ProjectHub
      version: 1.0.0
      mcp-server: projecthub
  ```

#### Extended frontmatter fields (Claude Code)

Claude Code supports additional frontmatter fields beyond the open standard:

| Field                      | Description                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------- |
| `argument-hint`            | Hint shown during autocomplete. Example: `[issue-number]` or `[filename] [format]`                |
| `disable-model-invocation` | Set `true` to prevent Claude from auto-loading. Use for side-effect skills (`/deploy`, `/commit`) |
| `user-invocable`           | Set `false` to hide from `/` menu. Use for background knowledge Claude should auto-apply          |
| `model`                    | Model to use when this skill is active                                                            |
| `effort`                   | Effort level override: `low`, `medium`, `high`, `max` (Opus 4.6 only)                             |
| `context`                  | Set to `fork` to run in a forked subagent context                                                 |
| `agent`                    | Subagent type when `context: fork` is set (e.g., `Explore`, `Plan`, or custom agent name)         |
| `hooks`                    | Hooks scoped to this skill's lifecycle                                                            |

**Invocation control matrix:**

| Frontmatter                      | You invoke | Claude invokes | When loaded into context                               |
| -------------------------------- | ---------- | -------------- | ------------------------------------------------------ |
| (default)                        | Yes        | Yes            | Description always in context; full skill when invoked |
| `disable-model-invocation: true` | Yes        | No             | Description NOT in context; loads when you invoke      |
| `user-invocable: false`          | No         | Yes            | Description always in context; loads when invoked      |

#### Security restrictions

**Forbidden in frontmatter:**

- XML angle brackets (< >)
- Skills with "claude" or "anthropic" in name (reserved)

**Why:** Frontmatter appears in Claude's system prompt. Malicious content could inject instructions.

### Writing effective skills

#### The description field

According to Anthropic's
[engineering blog](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills): "This
metadata...provides just enough information for Claude to know when each skill should be used without loading all of it
into context." This is the first level of progressive disclosure.

**Structure:**

```
[What it does] + [When to use it] + [Key capabilities]
```

**Examples of good descriptions:**

```yaml
# Good - specific and actionable
description: Analyzes Figma design files and generates
developer handoff documentation. Use when user uploads .fig
files, asks for "design specs", "component documentation", or
"design-to-code handoff".

# Good - includes trigger phrases
description: Manages Linear project workflows including sprint
planning, task creation, and status tracking. Use when user
mentions "sprint", "Linear tasks", "project planning", or asks
to "create tickets".

# Good - clear value proposition
description: End-to-end customer onboarding workflow for
PayFlow. Handles account creation, payment setup, and
subscription management. Use when user says "onboard new
customer", "set up subscription", or "create PayFlow account".
```

**Examples of bad descriptions:**

```yaml
# Too vague
description: Helps with projects.

# Missing triggers
description: Creates sophisticated multi-page documentation
systems.

# Too technical, no user triggers
description: Implements the Project entity model with
hierarchical relationships.
```

#### Combating undertriggering

Claude tends to undertrigger skills -- to not use them when they would be useful. To combat this, make descriptions
slightly "pushy" by explicitly listing trigger scenarios. Instead of:

> "How to build a simple fast dashboard to display internal data."

Write:

> "How to build a simple fast dashboard to display internal data. Use this skill whenever the user mentions dashboards,
> data visualization, internal metrics, or wants to display any kind of company data, even if they don't explicitly ask
> for a 'dashboard.'"

Claude only consults skills for tasks it cannot easily handle on its own -- simple, one-step queries may not trigger a
skill even if the description matches, because Claude can handle them directly with basic tools. Complex, multi-step, or
specialized queries reliably trigger skills when the description matches.

### Writing the main instructions

After the frontmatter, write the actual instructions in Markdown.

**Recommended structure:**

*Adapt this template for your skill. Replace bracketed sections with your specific content.*

```markdown
---
name: your-skill
description: [...]
---
# Your Skill Name
## Instructions
### Step 1: [First Major Step]
Clear explanation of what happens.
```

*Example:*

````markdown
```bash
python scripts/fetch_data.py --project-id PROJECT_ID Expected output: [describe what success looks like]
```
````

(Add more steps as needed)

**Examples:**

*Example 1: [common scenario]*

User says: "Set up a new marketing campaign"

Actions:

1. Fetch existing campaigns via MCP
2. Create new campaign with provided parameters

Result: Campaign created with confirmation link

(Add more examples as needed)

**Troubleshooting:**

*Error: [Common error message]*

Cause: [Why it happens]

Solution: [How to fix]

(Add more error cases as needed)

### Best practices for instructions

#### Be Specific and Actionable

Good:

```
Run `python scripts/validate.py --input {filename}` to check
data format.
If validation fails, common issues include:
- Missing required fields (add them to the CSV)
- Invalid date formats (use YYYY-MM-DD)
```

Bad:

```
Validate the data before proceeding.
```

#### Explain the why, not MUST/NEVER

Explain the **why** behind instructions rather than using heavy-handed imperatives. Today's LLMs have good theory of
mind and can go beyond rote instructions when given reasoning. If you find yourself writing ALWAYS or NEVER in all caps,
or using rigid structures, that is a yellow flag. Reframe and explain the reasoning so the model understands why the
thing you are asking for is important. This is a more effective approach than blunt directives.

For example, instead of "NEVER use inline styles", write "Avoid inline styles because they break the design system's
theming and make future redesigns require touching every component."

#### Extract bundled scripts from repeated work

When testing a skill, read the transcripts from test runs. If subagents or test executions all independently write
similar helper scripts (e.g., every test run creates its own `create_docx.py` or `build_chart.py`), that is a strong
signal the skill should bundle that script in `scripts/`. Write it once and tell the skill to use it -- this saves every
future invocation from reinventing the wheel.

#### Include error handling

```markdown
## Common Issues
### MCP Connection Failed
If you see "Connection refused":
1. Verify MCP server is running: Check Settings > Extensions
2. Confirm API key is valid
3. Try reconnecting: Settings > Extensions > [Your Service] >
Reconnect
```

#### Reference bundled resources clearly

```markdown
Before writing queries, consult `references/api-patterns.md`
for:
- Rate limiting guidance
- Pagination patterns
- Error codes and handling
```

#### Use progressive disclosure

Keep SKILL.md focused on core instructions (under 500 lines). Move detailed documentation to `references/` and link to
it. For large reference files (>300 lines), include a table of contents.

---

## Chapter 3: Testing and iteration

Skills can be tested at varying levels of rigor depending on your needs:

- **Manual testing in Claude.ai** - Run queries directly and observe behavior. Fast iteration, no setup required.
- **Scripted testing in Claude Code** - Automate test cases for repeatable validation across changes.
- **Programmatic testing via skills API** - Build evaluation suites that run systematically against defined test sets.

Choose the approach that matches your quality requirements and the visibility of your skill. A skill used internally by
a small team has different testing needs than one deployed to thousands of enterprise users.

> **Pro Tip:** Iterate on a single task before expanding

We've found that the most effective skill creators iterate on a single challenging task until Claude succeeds, then
extract the winning approach into a skill. This leverages Claude's in-context learning and provides faster signal than
broad testing. Once you have a working foundation, expand to multiple test cases for coverage.

### Recommended Testing Approach

Based on early experience, effective skills testing typically covers three areas:

#### 1. Triggering tests

**Goal:** Ensure your skill loads at the right times.

**Test cases:**

- Triggers on obvious tasks
- Triggers on paraphrased requests
- Doesn't trigger on unrelated topics

**Example test suite:**

```
Should trigger:
- "Help me set up a new ProjectHub workspace"
- "I need to create a project in ProjectHub"
- "Initialize a ProjectHub project for Q4 planning"

Should NOT trigger:
- "What's the weather in San Francisco?"
- "Help me write Python code"
- "Create a spreadsheet" (unless ProjectHub skill handles sheets)
```

**Automated trigger testing (Claude Code):** You can test whether a skill triggers programmatically by running
`claude -p` as a subprocess with the skill installed and checking if Claude chose to use it. Remove the `CLAUDECODE`
environment variable to allow nesting `claude -p` inside a Claude Code session. Run each query multiple times (3x is a
good default) for reliable trigger rates, and track precision/recall/accuracy across iterations.

#### 2. Functional tests

**Goal:** Verify the skill produces correct outputs.

**Test cases:**

- Valid outputs generated
- API calls succeed
- Error handling works
- Edge cases covered

**Example:**

```
Test: Create project with 5 tasks
Given: Project name "Q4 Planning", 5 task descriptions
When: Skill executes workflow
Then:
    - Project created in ProjectHub
    - 5 tasks created with correct properties
    - All tasks linked to project
    - No API errors
```

#### 3. Performance comparison

**Goal:** Prove the skill improves results vs. baseline.

Use the metrics from Define Success Criteria. Here's what a comparison might look like.

**Baseline comparison:**

```
Without skill:
- User provides instructions each time
- 15 back-and-forth messages
- 3 failed API calls requiring retry
- 12,000 tokens consumed

With skill:
- Automatic workflow execution
- 2 clarifying questions only
- 0 failed API calls
- 6,000 tokens consumed
```

#### Blind A/B comparison (advanced)

For rigorous comparison between two skill versions, use a blind evaluation approach: give two outputs (with-skill and
without-skill, or old-skill and new-skill) to an independent evaluator without revealing which produced which. The
evaluator judges purely on output quality using a rubric covering content (correctness, completeness, accuracy) and
structure (organization, formatting, usability). Then a post-hoc analyzer "unblinds" the results and identifies what
made the winner better -- specific instruction changes, script usage, or error handling differences.

This prevents bias toward a particular skill version and produces actionable improvement suggestions. The skill-creator
skill includes ready-made agents for this workflow (`agents/comparator.md` and `agents/analyzer.md`).

### Using the skill-creator skill

The [skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) skill - available in Claude.ai
via plugin directory or download for Claude Code - can help you build and iterate on skills. If you have an MCP server
and know your top 2-3 workflows, you can build and test a functional skill in a single sitting - often in 15-30 minutes.

**Creating skills:**

- Generate skills from natural language descriptions
- Produce properly formatted SKILL.md with frontmatter
- Suggest trigger phrases and structure

**Reviewing skills:**

- Flag common issues (vague descriptions, missing triggers, structural problems)
- Identify potential over/under-triggering risks
- Suggest test cases based on the skill's stated purpose

**Iterative improvement:**

- After using your skill and encountering edge cases or failures, bring those examples back to skill-creator
- Example: "Use the issues & solution identified in this chat to improve how the skill handles [specific edge case]"

**Advanced features** (in the skill-creator source):

- **agents/ directory** with specialized subagent prompts for grading, blind comparison, and post-hoc analysis
- **Workspace iteration structure** organizing results by iteration (`iteration-1/`, `iteration-2/`) with per-eval
  directories containing `with_skill/` and `without_skill/` outputs
- **Eval viewer** (`generate_review.py`) that builds an interactive HTML viewer with output review, feedback textboxes,
  and benchmark statistics
- **`.skill` packaging** (`package_skill.py`) that validates and packages skills as distributable ZIP files

**To use:**

```
"Use the skill-creator skill to help me build a skill for
[your use case]"
```

*Note: skill-creator helps you design and refine skills but does not execute automated test suites or produce
quantitative evaluation results.*

### Iteration based on feedback

Skills are living documents. Plan to iterate based on:

**Undertriggering signals:**

- Skill doesn't load when it should
- Users manually enabling it
- Support questions about when to use it

> **Solution:** Add more detail and nuance to the description - this may include keywords particularly for technical
> terms. See Combating undertriggering above.

**Overtriggering signals:**

- Skill loads for irrelevant queries
- Users disabling it
- Confusion about purpose

> **Solution:** Add negative triggers, be more specific

#### Improvement philosophy

When iterating on a skill based on test feedback:

1. **Generalize from feedback.** Skills may be used millions of times across many different prompts. You and the user
   are iterating on only a few examples because it is faster, but if the skill works only for those examples, it is
   useless. Rather than fiddly, overfitty changes or oppressively constrictive MUSTs, try branching out with different
   metaphors or recommending different patterns of working.

2. **Keep the prompt lean.** Remove instructions that are not pulling their weight. Read the transcripts, not just the
   final outputs -- if the skill is making the model waste time on unproductive steps, remove those parts.

3. **Look for repeated work across test runs.** See "Extract bundled scripts from repeated work" above.

### Automated description optimization

For systematic improvement of skill triggering accuracy (requires Claude Code with `claude -p`):

1. **Create eval queries** -- Generate ~20 queries: half should-trigger, half should-not-trigger. Make them realistic
   with concrete details (file paths, personal context, typos, casual speech). The most valuable negative cases are
   near-misses -- queries that share keywords but need something different.

2. **Train/test split** -- Split 60% train, 40% held-out test to prevent overfitting. The optimization loop only sees
   train results; test scores select the best description.

3. **Optimization loop** -- Evaluate current description (running each query 3x for reliability), call Claude to propose
   improvements based on failures, re-evaluate, iterate up to 5 times. Best description selected by test score, not
   train score.

4. **Metrics** -- Track precision (correct triggers / total triggers), recall (correct triggers / should-trigger),
   accuracy (all correct / total). Description must stay under 1024 characters.

The skill-creator includes a ready-made optimization loop (`scripts/run_loop.py`) that handles this automatically. See
the [skill-creator source](https://github.com/anthropics/skills/tree/main/skills/skill-creator) for details.

---

## Chapter 4: Distribution and sharing

Skills complement MCP integrations by packaging workflow guidance alongside tool access.

### Where skills live

Where you store a skill determines who can use it:

| Location   | Path                                     | Applies to                     |
| ---------- | ---------------------------------------- | ------------------------------ |
| Enterprise | Managed settings                         | All users in your organization |
| Personal   | `~/.claude/skills/<skill-name>/SKILL.md` | All your projects              |
| Project    | `.claude/skills/<skill-name>/SKILL.md`   | This project only              |
| Plugin     | `<plugin>/skills/<skill-name>/SKILL.md`  | Where plugin is enabled        |

Higher-priority locations win: enterprise > personal > project. Plugin skills use a `plugin-name:skill-name` namespace,
so they cannot conflict with other levels.

**Commands merged into skills:** Files at `.claude/commands/deploy.md` and skills at `.claude/skills/deploy/SKILL.md`
both create `/deploy`. Existing `.claude/commands/` files keep working, but if a skill and a command share the same
name, the skill takes precedence. Skills are recommended since they support additional features like supporting files
and frontmatter.

**Skills via `--add-dir`:** Skills in `.claude/skills/` within directories added via `--add-dir` are loaded
automatically and picked up by live change detection -- you can edit them during a session without restarting.

### Current distribution model (January 2026)

Individuals either upload a zipped skill to Claude.ai or place it in a Claude Code skills directory. Organizations can
deploy skills workspace-wide with automatic updates and centralized management.

**`.skill` packaging:** The skill-creator includes a `package_skill.py` script that validates the skill structure and
frontmatter, excludes build artifacts (`__pycache__`, `node_modules`, `evals/`), and produces a distributable `.skill`
file (ZIP format) that users can upload to Claude.ai or share directly. Note: the packager's validator hard-requires
`name` and `description` and may reject extended Claude Code-only frontmatter fields (`disable-model-invocation`,
`context`, `agent`, `effort`, etc.). If packaging a Claude Code skill with extended fields, validate manually or update
the packager's allowlist.

### An open standard

[Agent Skills](https://agentskills.io/home) is an open standard intended to keep skills portable across tools and
platforms. Authors can use the `compatibility` field when a skill depends on platform-specific features. Claude Code
adds features like invocation control, subagent execution, and dynamic context injection (see Chapter 6).

### Using skills via API

For programmatic use cases -- building applications, agents, or automated workflows with skills -- the API provides
direct control over skill management and execution.

**Key capabilities:**

- `/v1/skills` endpoint for listing and managing skills
- Add skills to Messages API requests via the `container.skills` parameter
- Version control and management through the Claude Console
- Works with the Claude Agent SDK for building custom agents

**Note:** Skills in the API require the Code Execution Tool beta, which provides the secure environment skills need to
run.

References:

- [Skills API Quickstart](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/quickstart)
- [Create Custom skills](https://docs.claude.com/en/api/skills/create-skill)
- [Skills in the Agent SDK](https://docs.claude.com/en/docs/agent-sdk/skills)

**When to use skills via the API vs. Claude.ai:**

| Use Case                                        | Best Surface            |
| ----------------------------------------------- | ----------------------- |
| End users interacting with skills directly      | Claude.ai / Claude Code |
| Manual testing and iteration during development | Claude.ai / Claude Code |
| Individual, ad-hoc workflows                    | Claude.ai / Claude Code |
| Applications using skills programmatically      | API                     |
| Production deployments at scale                 | API                     |
| Automated pipelines and agent systems           | API                     |

### External publishing (optional)

If you're publishing a skill externally:

- Host it in a public GitHub repo with a human-facing README and screenshots
- Link it from MCP documentation and include concise installation steps
- Describe outcomes and workflows, not folder structure or frontmatter mechanics
- If both MCP and skills are involved, explain the split: MCP provides tool access; skills encode workflow

---

## Chapter 5: Patterns and troubleshooting

These patterns emerged from skills created by early adopters and internal teams. They represent common approaches we've
seen work well, not prescriptive templates.

### Choosing your approach: Problem-first vs. tool-first

Think of it like Home Depot. You might walk in with a problem - "I need to fix a kitchen cabinet" - and an employee
points you to the right tools. Or you might pick out a new drill and ask how to use it for your specific job.

Skills work the same way:

- **Problem-first:** "I need to set up a project workspace" -> Your skill orchestrates the right MCP calls in the right
  sequence. Users describe outcomes; the skill handles the tools.
- **Tool-first:** "I have Notion MCP connected" -> Your skill teaches Claude the optimal workflows and best practices.
  Users have access; the skill provides expertise.

Most skills lean one direction. Knowing which framing fits your use case helps you choose the right pattern below.

### Pattern 1: Sequential workflow orchestration

**Use when:** Your users need multi-step processes in a specific order.

**Example structure:**

```markdown
## Workflow: Onboard New Customer
### Step 1: Create Account
Call MCP tool: `create_customer`
Parameters: name, email, company

### Step 2: Setup Payment
Call MCP tool: `setup_payment_method`
Wait for: payment method verification

### Step 3: Create Subscription
Call MCP tool: `create_subscription`
Parameters: plan_id, customer_id (from Step 1)

### Step 4: Send Welcome Email
Call MCP tool: `send_email`
Template: welcome_email_template
```

**Key techniques:**

- Explicit step ordering
- Dependencies between steps
- Validation at each stage
- Rollback instructions for failures

### Pattern 2: Multi-MCP coordination

**Use when:** Workflows span multiple services.

**Example: Design-to-development handoff**

```markdown
### Phase 1: Design Export (Figma MCP)
1. Export design assets from Figma
2. Generate design specifications
3. Create asset manifest

### Phase 2: Asset Storage (Drive MCP)
1. Create project folder in Drive
2. Upload all assets
3. Generate shareable links

### Phase 3: Task Creation (Linear MCP)
1. Create development tasks
2. Attach asset links to tasks
3. Assign to engineering team

### Phase 4: Notification (Slack MCP)
1. Post handoff summary to #engineering
2. Include asset links and task references
```

**Key techniques:**

- Clear phase separation
- Data passing between MCPs
- Validation before moving to next phase
- Centralized error handling

### Pattern 3: Iterative refinement

**Use when:** Output quality improves with iteration.

**Example: Report generation**

```markdown
## Iterative Report Creation
### Initial Draft
1. Fetch data via MCP
2. Generate first draft report
3. Save to temporary file

### Quality Check
1. Run validation script: `scripts/check_report.py`
2. Identify issues:
    - Missing sections
    - Inconsistent formatting
    - Data validation errors

### Refinement Loop
1. Address each identified issue
2. Regenerate affected sections
3. Re-validate
4. Repeat until quality threshold met

### Finalization
1. Apply final formatting
2. Generate summary
3. Save final version
```

**Key techniques:**

- Explicit quality criteria
- Iterative improvement
- Validation scripts
- Know when to stop iterating

### Pattern 4: Context-aware tool selection

**Use when:** Same outcome, different tools depending on context.

**Example: File storage**

```markdown
## Smart File Storage
### Decision Tree
1. Check file type and size
2. Determine best storage location:
    - Large files (>10MB): Use cloud storage MCP
    - Collaborative docs: Use Notion/Docs MCP
    - Code files: Use GitHub MCP
    - Temporary files: Use local storage

### Execute Storage
Based on decision:
- Call appropriate MCP tool
- Apply service-specific metadata
- Generate access link

### Provide Context to User
Explain why that storage was chosen
```

**Key techniques:**

- Clear decision criteria
- Fallback options
- Transparency about choices

### Pattern 5: Domain-specific intelligence

**Use when:** Your skill adds specialized knowledge beyond tool access.

**Example: Financial compliance**

```markdown
## Payment Processing with Compliance
### Before Processing (Compliance Check)
1. Fetch transaction details via MCP
2. Apply compliance rules:
    - Check sanctions lists
    - Verify jurisdiction allowances
    - Assess risk level
3. Document compliance decision

### Processing
IF compliance passed:
    - Call payment processing MCP tool
    - Apply appropriate fraud checks
    - Process transaction
ELSE:
    - Flag for review
    - Create compliance case

### Audit Trail
- Log all compliance checks
- Record processing decisions
- Generate audit report
```

**Key techniques:**

- Domain expertise embedded in logic
- Compliance before action
- Full audit trail
- Clear governance

### Pattern 6: Subagent delegation

**Use when:** Your skill needs to delegate specialized evaluation, analysis, or comparison tasks to independent agents.

**Example structure:**

```
my-evaluator-skill/
  SKILL.md
  agents/
    grader.md        # Evaluates assertions against outputs
    comparator.md    # Blind A/B quality comparison
    analyzer.md      # Post-hoc analysis of why winner won
```

Each agent file is a self-contained prompt with role, inputs, process steps, and structured JSON output format. The main
skill reads the relevant agent file and spawns a subagent with it. In Claude Code, use `context: fork` with the `agent`
field to run skills in isolated subagent contexts (see Chapter 6).

**Key techniques:**

- Each agent file is a complete, self-contained prompt
- Blind comparison prevents bias (comparator judges without knowing which version produced which output)
- Structured JSON output schemas enable downstream aggregation and benchmarking
- Post-hoc analysis identifies actionable improvement suggestions with priority and category

### Troubleshooting

#### Skill won't upload

**Error: "Could not find SKILL.md in uploaded folder"**

Cause: File not named exactly SKILL.md

**Solution:**

- Rename to SKILL.md (case-sensitive)
- Verify with: `ls -la` should show SKILL.md

**Error: "Invalid frontmatter"**

Cause: YAML formatting issue

Common mistakes:

```yaml
# Wrong - missing delimiters
name: my-skill
description: Does things

# Wrong - unclosed quotes
name: my-skill
description: "Does things

# Correct
---
name: my-skill
description: Does things
---
```

**Error: "Invalid skill name"**

Cause: Name has spaces or capitals

```yaml
# Wrong
name: My Cool Skill

# Correct
name: my-cool-skill
```

#### Skill doesn't trigger

**Symptom:** Skill never loads automatically

**Fix:** Revise your description field. See The Description Field and Combating undertriggering for good/bad examples.

**Quick checklist:**

- Is it too generic? ("Helps with projects" won't work)
- Does it include trigger phrases users would actually say?
- Does it mention relevant file types if applicable?
- Have skill descriptions exceeded the character budget? In Claude Code, run `/context` to check for warnings about
  excluded skills. Override the limit with `SLASH_COMMAND_TOOL_CHAR_BUDGET`.

**Debugging approach:** Ask Claude: "When would you use the [skill name] skill?" Claude will quote the description back.
Adjust based on what's missing.

#### Skill triggers too often

**Symptom:** Skill loads for unrelated queries

**Solutions:**

1. **Add negative triggers**

```yaml
description: Advanced data analysis for CSV files. Use for
statistical modeling, regression, clustering. Do NOT use for
simple data exploration (use data-viz skill instead).
```

2. **Be more specific**

```yaml
# Too broad
description: Processes documents

# More specific
description: Processes PDF legal documents for contract review
```

3. **Clarify scope**

```yaml
description: PayFlow payment processing for e-commerce. Use
specifically for online payment workflows, not for general
financial queries.
```

#### Instructions not followed

**Symptom:** Skill loads but Claude doesn't follow instructions

**Common causes:**

1. **Instructions too verbose**

   - Keep instructions concise
   - Use bullet points and numbered lists
   - Move detailed reference to separate files

2. **Instructions buried**

   - Put critical instructions at the top
   - Use ## Important or ## Critical headers
   - Repeat key points if needed

3. **Ambiguous language**

```markdown
# Bad
Make sure to validate things properly

# Good
CRITICAL: Before calling create_project, verify:
- Project name is non-empty
- At least one team member assigned
- Start date is not in the past
```

**Advanced technique:** For critical validations, consider bundling a script that performs the checks programmatically
rather than relying on language instructions. Code is deterministic; language interpretation isn't. See the
[Office skills](https://github.com/anthropics/skills/tree/main/skills) for examples of this pattern.

4. **Blunt directives instead of reasoning:** Before adding more ALL CAPS imperatives, try explaining the reasoning
   behind the instruction. LLMs respond well to understanding *why* something matters, which often produces better
   compliance than MUST/NEVER directives. See "Explain the why" in Best Practices above.

5. **Model "laziness"** Add explicit encouragement:

```markdown
## Performance Notes
- Take your time to do this thoroughly
- Quality is more important than speed
- Do not skip validation steps
```

Note: Adding this to user prompts is more effective than in SKILL.md

#### MCP connection issues

**Symptom:** Skill loads but MCP calls fail

**Checklist:**

1. **Verify MCP server is connected**

   - Claude.ai: Settings > Extensions > [Your Service]
   - Should show "Connected" status

2. **Check authentication**

   - API keys valid and not expired
   - Proper permissions/scopes granted
   - OAuth tokens refreshed

3. **Test MCP independently**

   - Ask Claude to call MCP directly (without skill)
   - "Use [Service] MCP to fetch my projects"
   - If this fails, issue is MCP not skill

4. **Verify tool names**

   - Skill references correct MCP tool names
   - Check MCP server documentation
   - Tool names are case-sensitive

#### Large context issues

**Symptom:** Skill seems slow or responses degraded

**Causes:**

- Skill content too large
- Too many skills enabled simultaneously
- All content loaded instead of progressive disclosure

**Solutions:**

1. **Optimize SKILL.md size**

   - Move detailed docs to references/
   - Link to references instead of inline
   - Keep SKILL.md under 500 lines / 5,000 words

2. **Reduce enabled skills**

   - Evaluate if you have more than 20-50 skills enabled simultaneously
   - Recommend selective enablement
   - Consider skill "packs" for related capabilities

---

## Chapter 6: Claude Code specifics

Claude Code extends the Agent Skills open standard with platform-specific runtime features. Most of these (string
substitutions, `context: fork`, dynamic injection, permission control) are Claude Code-only. A few (`.skill` packaging,
skill format itself) work across surfaces. This chapter covers the Claude Code extensions and notes where features cross
platform boundaries.

### String substitutions

Skills support variable substitution for dynamic values:

| Variable               | Description                                                   |
| ---------------------- | ------------------------------------------------------------- |
| `$ARGUMENTS`           | All arguments passed when invoking the skill                  |
| `$ARGUMENTS[N]`        | Access a specific argument by 0-based index                   |
| `$N`                   | Shorthand for `$ARGUMENTS[N]` (e.g., `$0` for first argument) |
| `${CLAUDE_SESSION_ID}` | The current session ID                                        |
| `${CLAUDE_SKILL_DIR}`  | The directory containing the skill's SKILL.md file            |

**Example:**

```yaml
---
name: migrate-component
description: Migrate a component from one framework to another
---
Migrate the $0 component from $1 to $2.
Preserve all existing behavior and tests.
```

Running `/migrate-component SearchBar React Vue` replaces `$0` with `SearchBar`, `$1` with `React`, `$2` with `Vue`.

If `$ARGUMENTS` is not present in the skill content, arguments are appended as `ARGUMENTS: <value>`.

### Dynamic context injection

The `` !`<command>` `` syntax runs shell commands before the skill content is sent to Claude. The command output
replaces the placeholder -- this is preprocessing, not something Claude executes.

**Example: PR summary skill**

```yaml
---
name: pr-summary
description: Summarize changes in a pull request
context: fork
agent: Explore
allowed-tools: Bash(gh *)
---
## Pull request context
- PR diff: !`gh pr diff`
- PR comments: !`gh pr view --comments`
- Changed files: !`gh pr diff --name-only`

## Your task
Summarize this pull request...
```

When this skill runs, each `` !`<command>` `` executes immediately, the output replaces the placeholder, and Claude
receives the fully-rendered prompt with actual PR data.

### Running skills in a subagent

Add `context: fork` to your frontmatter when you want a skill to run in isolation. The skill content becomes the prompt
that drives the subagent -- it will not have access to your conversation history.

```yaml
---
name: deep-research
description: Research a topic thoroughly
context: fork
agent: Explore
---
Research $ARGUMENTS thoroughly:
1. Find relevant files using Glob and Grep
2. Read and analyze the code
3. Summarize findings with specific file references
```

The `agent` field specifies which subagent configuration to use: built-in agents (`Explore`, `Plan`, `general-purpose`)
or any custom subagent from `.claude/agents/`. If omitted, uses `general-purpose`.

**Skills with `context: fork` vs subagents with preloaded skills:**

| Approach                   | System prompt                             | Task               | Also loads         |
| -------------------------- | ----------------------------------------- | ------------------ | ------------------ |
| Skill with `context: fork` | From agent type (`Explore`, `Plan`, etc.) | SKILL.md content   | CLAUDE.md          |
| Subagent with `skills`     | Subagent's markdown body                  | Delegation message | Skills + CLAUDE.md |

**Note:** `context: fork` only makes sense for skills with explicit instructions (tasks). If your skill contains
guidelines without a task, the subagent receives guidelines but no actionable prompt and returns without output.

### Bundled skills

Claude Code ships with built-in skills available in every session:

| Skill                       | Purpose                                                               |
| --------------------------- | --------------------------------------------------------------------- |
| `/batch <instruction>`      | Orchestrate large-scale changes across a codebase in parallel         |
| `/claude-api`               | Load Claude API reference material for your project's language        |
| `/debug [description]`      | Troubleshoot your current session by reading the debug log            |
| `/loop [interval] <prompt>` | Run a prompt repeatedly on an interval while the session stays open   |
| `/simplify [focus]`         | Review recently changed files for code reuse, quality, and efficiency |

Unlike built-in commands (which execute fixed logic), bundled skills are prompt-based -- they give Claude a playbook and
let it orchestrate using its tools.

### Permission control

Three ways to control which skills Claude can invoke:

- **Disable all skills:** Deny the `Skill` tool in `/permissions`
- **Allow/deny specific skills:** `Skill(commit)` (exact match) or `Skill(review-pr *)` (prefix match)
- **Hide individual skills:** Add `disable-model-invocation: true` to their frontmatter

### Skill discovery in monorepos

When you work with files in subdirectories, Claude Code automatically discovers skills from nested `.claude/skills/`
directories. For example, editing a file in `packages/frontend/` makes Claude also look for skills in
`packages/frontend/.claude/skills/`. This supports monorepo setups where packages have their own skills.

### Claude.ai vs Claude Code differences

The core skill format is identical, but runtime features differ by platform:

| Feature                        | Claude.ai | Claude Code |
| ------------------------------ | --------- | ----------- |
| Subagents (parallel test runs) | No        | Yes         |
| `claude -p` trigger testing    | No        | Yes         |
| Browser-based eval viewer      | No        | Yes         |
| Description optimization loop  | No        | Yes         |
| `context: fork`                | No        | Yes         |
| Dynamic injection (`` !` `` )  | No        | Yes         |
| String substitutions           | No        | Yes         |
| `.skill` packaging             | Yes       | Yes         |
| Inline result review           | Yes       | Yes         |

**Claude.ai adaptations:** No subagents means no parallel execution -- run test cases one at a time. Skip baseline runs
and quantitative benchmarking. Present results directly in conversation and ask for feedback inline.

---

## Chapter 7: Resources and references

If you're building your first skill, start with the Best Practices Guide, then reference the API docs as needed.

### Official Documentation

**Anthropic Resources:**

- [Best Practices Guide](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [Skills Documentation](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
- [Claude Code Skills](https://code.claude.com/docs/en/skills) -- extended frontmatter, subagents, string substitutions,
  dynamic injection
- [API Reference](https://platform.claude.com/docs/en/api/overview)
- [MCP Documentation](https://modelcontextprotocol.io)

**Blog Posts:**

- [Introducing Agent Skills](https://claude.com/blog/skills)
- [Engineering Blog: Equipping Agents for the Real World](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Skills Explained](https://www.claude.com/blog/skills-explained)
- [How to Create Skills for Claude](https://www.claude.com/blog/how-to-create-skills-key-steps-limitations-and-examples)
- [Building Skills for Claude Code](https://www.claude.com/blog/building-skills-for-claude-code)
- [Improving Frontend Design through Skills](https://www.claude.com/blog/improving-frontend-design-through-skills)

### Example skills

**Public skills repository:**

- GitHub: [anthropics/skills](https://github.com/anthropics/skills)
- Contains Anthropic-created skills you can customize

### Tools and Utilities

**skill-creator skill:**

- Source:
  [anthropics/skills/tree/main/skills/skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)
- Built into Claude.ai and available for Claude Code
- Includes: eval infrastructure (agents/, eval-viewer, benchmarking), description optimization loop
  (`scripts/run_loop.py`), blind A/B comparison (`agents/comparator.md`), `.skill` packaging
  (`scripts/package_skill.py`)
- Use: "Help me build a skill using skill-creator"

**Validation:**

- skill-creator can assess your skills
- Ask: "Review this skill and suggest improvements"

### Getting Support

**For Technical Questions:**

- General questions: Community forums at the [Claude Developers Discord](https://discord.com/invite/6PPFFzqPDZ)

**For Bug Reports:**

- GitHub Issues: [anthropics/skills/issues](https://github.com/anthropics/skills/issues)
- Include: Skill name, error message, steps to reproduce

---

## Reference A: Quick checklist

Use this checklist to validate your skill before and after upload. If you want a faster start, use the skill-creator
skill to generate your first draft, then run through this list to make sure you haven't missed anything.

### Before you start

- [ ] Identified 2-3 concrete use cases
- [ ] Tools identified (built-in or MCP)
- [ ] Reviewed this guide and example skills
- [ ] Planned folder structure

### During development

- [ ] Folder named in kebab-case
- [ ] SKILL.md file exists (exact spelling)
- [ ] YAML frontmatter has `---` delimiters
- [ ] name field: kebab-case, no spaces, no capitals
- [ ] description includes WHAT and WHEN, under 1024 characters
- [ ] No XML tags (< >) anywhere
- [ ] Instructions are clear and actionable (explain the why)
- [ ] Error handling included
- [ ] Examples provided
- [ ] References clearly linked
- [ ] Considered `disable-model-invocation` for side-effect skills
- [ ] Considered `context: fork` for isolated execution (Claude Code)

### Before upload

- [ ] Tested triggering on obvious tasks
- [ ] Tested triggering on paraphrased requests
- [ ] Verified doesn't trigger on unrelated topics
- [ ] Functional tests pass
- [ ] Tool integration works (if applicable)
- [ ] Compressed as .zip file

### After upload

- [ ] Test in real conversations
- [ ] Monitor for under/over-triggering
- [ ] Collect user feedback
- [ ] Iterate on description and instructions
- [ ] Update version in metadata

---

## Reference B: YAML frontmatter

### Required fields

```yaml
---
name: skill-name-in-kebab-case
description: What it does and when to use it. Include specific
trigger phrases.
---
```

### All fields

```yaml
---
# Identity (required for cross-platform; Claude Code defaults name to directory name)
name: skill-name                # kebab-case, max 64 chars
description: [what + when]      # under 1024 chars, no XML tags

# Invocation control (Claude Code)
disable-model-invocation: true  # prevent Claude from auto-loading
user-invocable: false           # hide from / menu
argument-hint: "[issue-number]" # autocomplete hint

# Execution (Claude Code)
context: fork                   # run in isolated subagent
agent: Explore                  # subagent type (Explore, Plan, general-purpose, or custom)
model: claude-sonnet-4-6        # model override
effort: high                    # effort override (low, medium, high, max)
allowed-tools: "Read Grep Glob" # restrict tool access
hooks: {}                       # hooks scoped to skill lifecycle

# Distribution
license: MIT                    # open-source license
compatibility: "Claude Code"    # environment requirements (1-500 chars)
metadata:                       # custom key-value pairs
  author: Company Name
  version: 1.0.0
  mcp-server: server-name
  category: productivity
  tags: [project-management, automation]
  documentation: https://example.com/docs
  support: support@example.com
---
```

### Security notes

**Allowed:**

- Any standard YAML types (strings, numbers, booleans, lists, objects)
- Custom metadata fields
- Long descriptions (up to 1024 characters)

**Forbidden:**

- XML angle brackets (< >) - security restriction
- Code execution in YAML (uses safe YAML parsing)
- Skills named with "claude" or "anthropic" prefix (reserved)

---

## Reference C: Complete skill examples

For full, production-ready skills demonstrating the patterns in this guide:

- Document Skills - [PDF](https://github.com/anthropics/skills/tree/main/skills/pdf),
  [DOCX](https://github.com/anthropics/skills/tree/main/skills/docx),
  [PPTX](https://github.com/anthropics/skills/tree/main/skills/pptx),
  [XLSX](https://github.com/anthropics/skills/tree/main/skills/xlsx) creation
- [Example Skills](https://github.com/anthropics/skills/tree/main/skills) - Various workflow patterns
- [Partner Skills Directory](https://www.claude.com/connectors) - View skills from various partners such as Asana,
  Atlassian, Canva, Figma, Sentry, Zapier, and more

These repositories stay up-to-date and include additional examples beyond what's covered here. Clone them, modify them
for your use case, and use them as templates.

---

## Sources

This guide synthesizes content from three sources:

- **Anthropic's official skills guide** (PDF, January 2026) -- the foundation for chapters 1-5 and the reference
  appendices
- **skill-creator skill**
  ([anthropics/skills/tree/main/skills/skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator))
  -- eval infrastructure, blind A/B comparison, description optimization loop, improvement philosophy, practical
  skill-writing guidance
- **Claude Code skills documentation** ([code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills)) --
  extended frontmatter fields, string substitutions, subagent execution, dynamic context injection, bundled skills,
  permission control, monorepo discovery
