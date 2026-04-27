"""WorkflowPolicy — composable tagger → branch → stage pipeline.

Provides a configurable policy that classifies actions via cheap LLM triage,
routes them through matching branches, and escalates through filter → checker →
reviewer stages. Plugs into the existing PolicyEngine via bundle registration.
"""

from .config import BranchConfig, WorkflowConfig
from .divergence import build_divergence_config
from .policy import WorkflowPolicy

__all__ = [
    "BranchConfig",
    "WorkflowConfig",
    "WorkflowPolicy",
    "build_divergence_config",
]
