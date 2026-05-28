"""Stage implementations for WorkflowPolicy branches.

Stages are plain classes (not policies). They produce PolicyDecision objects
but don't implement the Policy protocol — WorkflowPolicy owns that.

UX constraint: Non-blocking findings go in ``PolicyDecision.warnings`` (printed
by the hook), not ``violations`` (only shown on deny). Stages must return a
resolved allow/warn/deny decision rather than emitting ``needs_review``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from forge.core.reactive.structured_output import extract_json_from_response
from forge.policy.types import ActionContext, PolicyDecision, Severity, Violation
from forge.policy.workflow.config import CheckerConfig, FilterConfig, ReviewerConfig

_log = logging.getLogger(__name__)

# Confidence threshold for blocking (same as supervisor)
CONFIDENCE_THRESHOLD = 0.8

_VALID_SEVERITIES: set[str] = {"critical", "high", "medium", "low"}


def _normalize_severity(raw: str) -> Severity:
    """Coerce arbitrary severity string to a valid Severity literal."""
    normalized = raw.lower().strip()
    if normalized in _VALID_SEVERITIES:
        return normalized  # type: ignore[return-value]
    return "medium"


class FilterStage:
    """Deterministic gating. Free (no LLM calls).

    Compiles regexes in ``__init__`` so invalid patterns fail fast at engine
    build time rather than silently allowing everything at evaluation time.
    """

    def __init__(self, config: FilterConfig) -> None:
        self._path_patterns = [re.compile(p) for p in config.path_patterns]
        self._exclude_patterns = [re.compile(p) for p in config.exclude_patterns]
        self._max_content_length = config.max_content_length

    def passes(self, context: ActionContext) -> bool:
        """Return True if the action should proceed to later stages.

        Check order:
        1. exclude_patterns — any match → False (skip this branch)
        2. path_patterns — at least one must match → True (if list is non-empty)
        3. max_content_length — content exceeds limit → False
        """
        path = context.target_path or ""

        for pattern in self._exclude_patterns:
            if pattern.search(path):
                return False

        if self._path_patterns:
            if not any(p.search(path) for p in self._path_patterns):
                return False

        if self._max_content_length is not None:
            content_len = len(context.new_content or "")
            if content_len > self._max_content_length:
                return False

        return True


class CheckerStage:
    """Cheap LLM intermediate check via SyncAdapter.ask()."""

    def __init__(self, config: CheckerConfig) -> None:
        self._config = config

    def check(self, context: ActionContext, tags: list[str], policy_id: str) -> PolicyDecision | None:
        """Quick LLM check.

        Returns:
            PolicyDecision(allow) to short-circuit (no reviewer needed), or
            None to escalate to the reviewer stage.
        """
        try:
            from forge.core.llm import SyncAdapter, get_client

            prompt = self._config.prompt_template.format(
                tool_name=context.tool_name,
                target_path=context.target_path or "N/A",
                content=(context.raw_diff or context.new_content or "")[:2000],
                tags=", ".join(tags),
            )

            client = get_client(self._config.model)
            adapter = SyncAdapter(client)
            response = adapter.ask(prompt, system=self._config.system_prompt)

            data = extract_json_from_response(response)
            if data is None:
                _log.debug("Checker could not parse response, escalating to reviewer")
                return None

            if data.get("aligned") is True:
                return PolicyDecision(decision="allow", policy_id=policy_id)
            return None

        except Exception as e:
            _log.warning("CheckerStage failed: %s", e)
            return None


class ReviewerStage:
    """Deep LLM review via SyncAdapter.ask()."""

    def __init__(self, config: ReviewerConfig) -> None:
        self._config = config

    def review(self, context: ActionContext, tags: list[str], policy_id: str) -> PolicyDecision:
        """Deep review. Returns allow/deny/warn.

        Verdict mapping (mirrors supervisor, configurable policy_id):
        - aligned → allow
        - divergent + high confidence (≥0.8) + citations → deny
        - divergent + low confidence or no citations → warn
        - parse failure → warn (fail-open)
        """
        try:
            from forge.core.llm import SyncAdapter, get_client

            prompt = self._config.prompt_template.format(
                tool_name=context.tool_name,
                target_path=context.target_path or "N/A",
                content=(context.raw_diff or context.new_content or "")[:4000],
                tags=", ".join(tags),
            )

            client = get_client(self._config.model)
            adapter = SyncAdapter(client)
            response = adapter.ask(prompt, system=self._config.system_prompt)

            data = extract_json_from_response(response)
            if data is None:
                return PolicyDecision(
                    decision="warn",
                    policy_id=policy_id,
                    warnings=["Reviewer could not parse LLM response"],
                )

            return _map_verdict(data, policy_id)

        except Exception as e:
            _log.warning("ReviewerStage failed: %s", e)
            return PolicyDecision(
                decision="warn",
                policy_id=policy_id,
                warnings=[f"Reviewer error: {e}, failing open"],
            )


def _map_verdict(data: dict[str, Any], policy_id: str) -> PolicyDecision:
    """Map a JSON verdict dict to a PolicyDecision.

    Non-blocking findings go in ``warnings`` (visible in hook UX).
    Only high-confidence denials with citations use ``violations``.
    """
    verdict = data.get("verdict", "aligned")
    confidence = float(data.get("confidence", 0.0))
    raw_violations = data.get("violations", [])

    if verdict == "aligned":
        return PolicyDecision(decision="allow", policy_id=policy_id)

    has_citations = any(v.get("citations") for v in raw_violations if isinstance(v, dict))

    if confidence >= CONFIDENCE_THRESHOLD and has_citations:
        violations = [
            Violation(
                rule_id=f"{policy_id}.reviewer",
                severity=_normalize_severity(v.get("severity", "medium")),
                message=v.get("evidence", "Divergent change detected"),
                evidence=v.get("evidence"),
                suggested_fix=v.get("suggested_fix"),
                citations=v.get("citations", []),
            )
            for v in raw_violations
            if isinstance(v, dict)
        ]
        return PolicyDecision(
            decision="deny",
            policy_id=policy_id,
            violations=violations,
        )

    # Low confidence or no citations → warn (visible in hook UX)
    reasons = [v.get("evidence", str(v)) for v in raw_violations if isinstance(v, dict)]
    warnings = reasons if reasons else [f"Reviewer flagged as divergent (confidence={confidence:.2f})"]
    return PolicyDecision(
        decision="warn",
        policy_id=policy_id,
        warnings=warnings,
    )
