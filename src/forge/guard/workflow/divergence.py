"""Divergence-from-mean workflow — first concrete WorkflowPolicy instance.

Cost model: tagger (~$0.001) filters 80% → checker (~$0.001) short-circuits 80%
→ only ~4% reach reviewer (~$0.05). Total: ~$0.32/100 changes vs $5.00 reviewing
everything.
"""

from __future__ import annotations

from typing import Any

from forge.guard.workflow.config import (
    BranchConfig,
    CheckerConfig,
    FilterConfig,
    ReviewerConfig,
    WorkflowConfig,
)

DIVERGENCE_TAGGER_PROMPT = """\
Classify this code change into exactly one category (respond with just the tag):

- architectural: changes to module structure, public APIs, cross-cutting patterns
- migration: database schema, data migration scripts
- config: configuration files, environment setup
- routine: standard implementation, bug fixes, test updates
- trivial: whitespace, comments, import reordering

Tool: {tool_name}
File: {target_path}
Content (truncated):
{content}

Tag:"""

DIVERGENCE_CHECKER_PROMPT = """\
Does this code change follow the project's established patterns?
Tool: {tool_name}, File: {target_path}, Tags: {tags}

Content:
{content}

Respond with JSON: {{"aligned": true/false, "reason": "one sentence"}}"""

DIVERGENCE_REVIEWER_PROMPT = """\
Review this code change for architectural consistency.
Tool: {tool_name}, File: {target_path}, Tags: {tags}

Content:
{content}

Evaluate whether this change aligns with the project's established patterns.
If divergent, cite specific evidence and suggest corrections.

Respond with JSON in a code fence:
```json
{{
  "verdict": "aligned" | "divergent",
  "confidence": 0.0-1.0,
  "violations": [
    {{
      "severity": "high" | "medium" | "low",
      "evidence": "what diverges from established patterns",
      "suggested_fix": "what should be done instead",
      "citations": ["specific pattern or convention being violated"]
    }}
  ]
}}
```"""


def build_divergence_config(**overrides: Any) -> WorkflowConfig:
    """Build the divergence-from-mean workflow config.

    The "needs-review" branch triggers on architectural/migration tags,
    filters out test files, runs a cheap checker, then a deep reviewer.
    Routine/trivial actions don't match any branch and are allowed.

    Args:
        **overrides: Override any WorkflowConfig field (e.g., tagger_model).

    Returns:
        WorkflowConfig ready for WorkflowPolicy instantiation.
    """
    defaults: dict[str, Any] = {
        "name": "divergence",
        "description": "Flag code changes that diverge from established project patterns",
        "intent": (
            "Catch architectural drift early. Code changes that deviate from established "
            "patterns need review to ensure they are intentional improvements, not accidental "
            "divergence from project conventions."
        ),
        "tagger_model": "gemini/gemini-2.0-flash",
        "tagger_prompt": DIVERGENCE_TAGGER_PROMPT,
        "branches": [
            BranchConfig(
                name="needs-review",
                match_tags=["architectural", "migration"],
                match_mode="any",
                filter=FilterConfig(
                    exclude_patterns=[r"^tests/", r"^test_"],
                ),
                checker=CheckerConfig(
                    prompt_template=DIVERGENCE_CHECKER_PROMPT,
                ),
                reviewer=ReviewerConfig(
                    prompt_template=DIVERGENCE_REVIEWER_PROMPT,
                ),
            ),
        ],
    }
    defaults.update(overrides)
    return WorkflowConfig(**defaults)
