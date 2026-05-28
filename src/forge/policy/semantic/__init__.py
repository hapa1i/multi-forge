"""Semantic policies for the Policy Engine.

Semantic policies use LLM-based evaluation for nuanced judgment calls
that cannot be expressed as deterministic rules. The primary use case
is the Supervisor pattern:

1. Planning session creates and approves a plan (ExitPlanMode)
2. Session is forked and promoted to supervisor role
3. Executor actions are validated against the plan by the supervisor
4. Supervisor returns structured verdicts (aligned/divergent + confidence)

Throttling and caching prevent excessive LLM calls:
- Cache key: sha256(tool_name + file_path + content_hash)[:16]
- Cached verdicts reused within throttle_seconds window
- Fail-open on timeout/error (configurable)
"""

from forge.policy.semantic.supervisor import (
    SemanticSupervisorPolicy,
    invoke_supervisor,
)
from forge.policy.semantic.verdict import (
    SupervisorVerdict,
    parse_supervisor_verdict,
    verdict_to_decision,
)

__all__ = [
    "SemanticSupervisorPolicy",
    "SupervisorVerdict",
    "invoke_supervisor",
    "parse_supervisor_verdict",
    "verdict_to_decision",
]
