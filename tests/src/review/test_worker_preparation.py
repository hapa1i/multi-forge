"""Tests for shared review-worker preparation primitives."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from forge.review.models import ModelSpec, PromptMode
from forge.review.worker_preparation import (
    ReviewAssignmentKind,
    ReviewWorkerInput,
    load_review_resource,
    parse_review_worker_assignments,
    prepare_review_workers,
)


def _model(*, prompt_mode: PromptMode = "override") -> ModelSpec:
    return ModelSpec(
        name="reviewer",
        model_id="reviewer-id",
        family="openai",
        provider_refs=(("openrouter", "openai/reviewer"),),
        description="Catalog description",
        preferred_proxy="openrouter-openai",
        prompt="Catalog prompt",
        prompt_mode=prompt_mode,
    )


@pytest.mark.parametrize(
    ("assignment_kind", "marker"),
    [("role", "{role_prompt}"), ("stance", "{stance_prompt}")],
)
def test_load_review_resource_requires_domain_marker(
    tmp_path: Path,
    assignment_kind: ReviewAssignmentKind,
    marker: str,
) -> None:
    resource = tmp_path / "review.md"
    resource.write_text("No injection point")

    expected = f"Resource {resource} must contain '{marker}' marker for {assignment_kind} injection."
    with pytest.raises(ValueError, match=re.escape(expected)):
        load_review_resource(str(resource), marker=marker, assignment_kind=assignment_kind)

    resource.write_text(f"Evaluate: {marker}")
    assert load_review_resource(str(resource), marker=marker, assignment_kind=assignment_kind) == f"Evaluate: {marker}"


def test_prepare_review_workers_fills_prompts_and_deduplicates_worker_ids() -> None:
    model = _model(prompt_mode="prefix")
    prepared = prepare_review_workers(
        "Before {role_prompt}; after {role_prompt}",
        [
            ReviewWorkerInput(model=model, label="security", prompt="Inspect auth"),
            ReviewWorkerInput(model=model, label="security", prompt="Inspect access"),
        ],
        marker="{role_prompt}",
        guardrail=" [guardrail]",
        assignment_kind="role",
    )

    assert [spec.effective_worker_id for spec in prepared.specs] == ["reviewer-security", "reviewer-security-1"]
    assert prepared.label_map == {
        "reviewer-security": "security",
        "reviewer-security-1": "security",
    }
    assert prepared.specs[0].prompt == "Before Inspect auth [guardrail]; after Inspect auth [guardrail]"
    assert prepared.specs[1].description == "security role via reviewer"
    assert prepared.specs[0].provider_refs == model.provider_refs
    assert prepared.specs[0].preferred_proxy == model.preferred_proxy
    # Specialized prompts remain full overrides even when the catalog model carries a prefix hint.
    assert prepared.specs[0].prompt_mode == "override"


@pytest.mark.parametrize("assignment_kind", ["role", "stance"])
def test_parse_review_worker_assignments_preserves_common_syntax(
    assignment_kind: ReviewAssignmentKind,
) -> None:
    model = _model()
    parsed = parse_review_worker_assignments(
        [" reviewer : named ", 'reviewer:"A custom prompt longer than thirty characters"'],
        assignment_kind=assignment_kind,
        named_prompts={"named": "Named prompt"},
        available_models={"reviewer": model},
    )

    assert parsed[0].model is model
    assert (parsed[0].assignment, parsed[0].prompt, parsed[0].display_label) == ("named", "Named prompt", None)
    custom_prompt = "A custom prompt longer than thirty characters"
    assert parsed[1].assignment == "custom"
    assert parsed[1].prompt == custom_prompt
    assert parsed[1].display_label == custom_prompt[:30] + "..."


@pytest.mark.parametrize(
    ("assignment_kind", "arg", "message"),
    [
        ("role", "reviewer", "Invalid --worker 'reviewer'. Expected model:role or model:custom prompt."),
        ("stance", "reviewer:", "Empty stance/prompt for model 'reviewer'."),
        ("role", "missing:named", "Unknown model 'missing'. Available: ['reviewer']"),
    ],
)
def test_parse_review_worker_assignments_preserves_errors(
    assignment_kind: ReviewAssignmentKind,
    arg: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        parse_review_worker_assignments(
            [arg],
            assignment_kind=assignment_kind,
            named_prompts={"named": "Named prompt"},
            available_models={"reviewer": _model()},
        )
