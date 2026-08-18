"""Shared preparation primitives for role- and stance-assigned review workers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from .models import ModelSpec

ReviewAssignmentKind = Literal["role", "stance"]


@dataclass(frozen=True)
class ReviewWorkerInput:
    """Domain-neutral input needed to specialize one review worker."""

    model: ModelSpec
    label: str
    prompt: str


@dataclass(frozen=True)
class PreparedReviewWorkers:
    """Specialized model specs and their stable worker-label mapping."""

    specs: list[ModelSpec]
    label_map: dict[str, str]


@dataclass(frozen=True)
class ParsedReviewWorkerAssignment:
    """Parsed ``model:assignment`` input before domain-specific wrapping."""

    model: ModelSpec
    assignment: str
    prompt: str
    display_label: str | None = None


def load_review_resource(
    resource_path: str,
    *,
    marker: str,
    assignment_kind: ReviewAssignmentKind,
) -> str:
    """Load a review resource and require its domain marker."""
    content = Path(resource_path).read_text()
    if marker not in content:
        raise ValueError(f"Resource {resource_path} must contain '{marker}' marker for {assignment_kind} injection.")
    return content


def prepare_review_workers(
    template: str,
    workers: Sequence[ReviewWorkerInput],
    *,
    marker: str,
    guardrail: str,
    assignment_kind: ReviewAssignmentKind,
) -> PreparedReviewWorkers:
    """Fill worker prompts and assign stable IDs and labels in input order."""
    specs: list[ModelSpec] = []
    label_map: dict[str, str] = {}
    seen: dict[str, int] = {}

    for worker in workers:
        base_id = f"{worker.model.name}-{worker.label}"
        count = seen.get(base_id, 0)
        seen[base_id] = count + 1
        worker_id = base_id if count == 0 else f"{base_id}-{count}"
        spec = replace(
            worker.model,
            description=f"{worker.label} {assignment_kind} via {worker.model.name}",
            prompt=template.replace(marker, worker.prompt + guardrail),
            prompt_mode="override",
            worker_id=worker_id,
        )
        specs.append(spec)
        label_map[worker_id] = worker.label

    return PreparedReviewWorkers(specs=specs, label_map=label_map)


def parse_review_worker_assignments(
    worker_args: Sequence[str],
    *,
    assignment_kind: ReviewAssignmentKind,
    named_prompts: Mapping[str, str],
    available_models: Mapping[str, ModelSpec],
) -> list[ParsedReviewWorkerAssignment]:
    """Parse common ``model:role`` or ``model:stance`` worker syntax."""
    assignments: list[ParsedReviewWorkerAssignment] = []
    for arg in worker_args:
        if ":" not in arg:
            raise ValueError(f"Invalid --worker '{arg}'. Expected model:{assignment_kind} or model:custom prompt.")

        model_name, value = arg.split(":", 1)
        model_name = model_name.strip()
        if model_name not in available_models:
            available = list(available_models.keys())
            raise ValueError(f"Unknown model '{model_name}'. Available: {available}")

        value = value.strip()
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if not value:
            raise ValueError(f"Empty {assignment_kind}/prompt for model '{model_name}'.")

        model = available_models[model_name]
        if value in named_prompts:
            assignments.append(
                ParsedReviewWorkerAssignment(
                    model=model,
                    assignment=value,
                    prompt=named_prompts[value],
                )
            )
            continue

        label = value[:30] + ("..." if len(value) > 30 else "")
        assignments.append(
            ParsedReviewWorkerAssignment(
                model=model,
                assignment="custom",
                prompt=value,
                display_label=label,
            )
        )

    return assignments
