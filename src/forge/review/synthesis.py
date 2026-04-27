"""Output formatting for multi-model review results.

Provides two output modes:
- Synthesis prompt: human-readable text for agent consumption
- JSON output: structured data for skill/script consumption
"""

from __future__ import annotations

import json
from typing import Any

from .models import MultiReviewOutput, ReviewResult


def format_synthesis_prompt(output: MultiReviewOutput) -> str:
    """Format review results into a synthesis prompt.

    Intended for the calling agent to read and synthesize.
    """
    sections: list[str] = []

    prompt_preview = output.prompt[:500]
    if len(output.prompt) > 500:
        prompt_preview += "..."
    sections.append(f"I asked {len(output.results)} models the same prompt:\n\n> {prompt_preview}")

    for result in output.results:
        sections.append(f"\n\n-----\n\n## {result.model_name}'s answer:\n")
        if result.success:
            sections.append(result.stdout)
        else:
            sections.append(f"**Error:** {result.error}")

    sections.append("""

-----

## Synthesis Request

Now that you've seen all responses:

1. **Points you missed**: Any points covered by other models that you did not cover?
2. **Accuracy check**: Can you verify if they are accurate? Anything you disagree with?
3. **Overall synthesis**: Provide a unified synthesis combining the best insights from all models.
""")

    return "".join(sections)


def format_json_output(output: MultiReviewOutput) -> str:
    """Format review results as structured JSON."""
    data = build_json_dict(output)
    return json.dumps(data, indent=2)


def build_json_dict(output: MultiReviewOutput) -> dict[str, Any]:
    """Build the JSON-serializable dict for output."""
    return {
        "prompt": output.prompt,
        "results": {r.model_name: _result_to_dict(r) for r in output.results},
        "successful": output.successful,
        "failed": output.failed,
    }


def _result_to_dict(result: ReviewResult) -> dict[str, Any]:
    return {
        "response": result.stdout if result.success else None,
        "error": result.error,
        "duration_seconds": round(result.duration_seconds, 2),
        "success": result.success,
    }
