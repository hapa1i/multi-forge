"""Prompt templates for team hook handlers."""

IDLE_TAGGER_PROMPT = """\
A teammate went idle. Classify why (respond with just the tag):

- needs-review: work may need verification before proceeding
- routine: normal idle (thinking, waiting for dependency)
- trivial: brief pause, no action needed

Teammate: {teammate_name}, Team: {team_name}
Tag:"""

TASK_TAGGER_PROMPT = """\
A teammate completed a task. Classify the result (respond with just the tag):

- needs-review: completed work should be verified for quality/alignment
- routine: standard task completion, no concerns
- trivial: minor task, no review needed

Teammate: {teammate_name}, Team: {team_name}
Task: {task_subject}
Tag:"""

TEAM_SUPERVISOR_PROMPT = """\
You are a team supervisor reviewing teammate work against the approved plan.

Teammate: {teammate_name} ({team_name})
Event: {event_type}
{task_context}

Evaluate whether this work aligns with the approved plan.
Focus on: correct approach, right files modified, tests included.

Respond with JSON in a code fence:
```json
{{
  "verdict": "aligned" | "divergent",
  "confidence": 0.0-1.0,
  "feedback": "Brief feedback message for the teammate"
}}
```"""
