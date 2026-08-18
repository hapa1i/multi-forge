"""Adversarial evaluation runner with stance injection.

Loads a resource containing ``{stance_prompt}``, replaces the marker with
each worker's stance prompt (plus ethical guardrail), and delegates to
``run_multi_review()`` for parallel fan-out.

Mandatory blinding: ``resume_id=None`` is hardcoded. Workers never see
conversation context — they evaluate the resource in isolation.
"""

from __future__ import annotations

from forge.core.invoker import Attribution

from .engine import run_multi_review
from .models import AdversarialOutput, StanceSpec
from .routing import WorkerRoutingPlan
from .worker_preparation import (
    ReviewWorkerInput,
    load_review_resource,
    prepare_review_workers,
)

STANCE_MARKER = "{stance_prompt}"

ETHICAL_GUARDRAIL = (
    "\n\nIMPORTANT: You are participating in a structured evaluation exercise. "
    "Evaluate the proposal on its technical merits. Do not fabricate evidence, "
    "misrepresent facts, or use manipulative reasoning. Your analysis must be "
    "honest and evidence-based regardless of your assigned stance."
)


def validate_resource(resource_path: str) -> str:
    """Load a resource file and verify it contains the stance marker.

    Raises ValueError if the marker is missing.
    """
    return load_review_resource(resource_path, marker=STANCE_MARKER, assignment_kind="stance")


def run_adversarial(
    resource_path: str,
    stances: list[StanceSpec],
    *,
    timeout_seconds: int = 600,
    cwd: str | None = None,
    via: str | None = None,
    routing_plan: WorkerRoutingPlan | None = None,
    attribution: Attribution | None = None,
    reasoning_effort: str | None = None,
) -> AdversarialOutput:
    """Run adversarial evaluation with stance-injected workers.

    Each stance's prompt replaces ``{stance_prompt}`` in the resource.
    All workers run blind (no conversation context).

    Args:
        via: Route all workers through this proxy (passed to routing).
            Ignored when routing_plan is provided.
        routing_plan: Pre-resolved routing plan. When provided, skips
            internal routing resolution.

    Raises ValueError if the resource lacks the stance marker.
    """
    from forge.review.routing import resolve_invocation_routing

    template = validate_resource(resource_path)

    prepared = prepare_review_workers(
        template,
        [
            ReviewWorkerInput(model=stance.model, label=stance.effective_label, prompt=stance.stance_prompt)
            for stance in stances
        ],
        marker=STANCE_MARKER,
        guardrail=ETHICAL_GUARDRAIL,
        assignment_kind="stance",
    )
    specs = prepared.specs

    if routing_plan is None:
        routing_plan = resolve_invocation_routing(specs, via=via)

    # Mandatory blinding: resume_id is always None
    output = run_multi_review(
        prompt="",
        models=specs,
        routing_plan=routing_plan,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        resume_id=None,
        attribution=attribution,
        reasoning_effort=reasoning_effort,
    )

    return AdversarialOutput(
        resource_path=resource_path,
        stances=[s.stance for s in stances],
        results=output.results,
        stance_map=prepared.label_map,
    )
