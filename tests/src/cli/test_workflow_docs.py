"""Validate model names in executable workflow documentation examples."""

from __future__ import annotations

import shlex
from pathlib import Path

from forge.review.models import AVAILABLE_MODELS, resolve_model_specs

WORKFLOW_DOC = Path(__file__).parent.parent.parent.parent / "docs" / "end-user" / "workflow.md"


def test_workflow_doc_commands_reference_selectable_models():
    commands = (line for line in WORKFLOW_DOC.read_text().splitlines() if line.startswith("forge workflow "))

    for command in commands:
        tokens = shlex.split(command, comments=True)
        for index, token in enumerate(tokens[:-1]):
            value = tokens[index + 1]
            if token in {"-m", "--models"}:
                resolve_model_specs(value)
            elif token == "--worker":
                model_name = value.split(":", 1)[0]
                assert model_name in AVAILABLE_MODELS, f"Unknown workflow worker {model_name!r} in: {command}"
