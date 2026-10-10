"""Pure, bounded audience projection of already evaluated Codex policy results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from forge.policy.types import CompositeDecision, PolicyDecision, Violation

FIELD_CHARS = 600
FINDING_BYTES = 2400
FINDING_LIMIT = 12
MODEL_BYTES = 12000
OPERATOR_BYTES = 5000
WIRE_BYTES = 20000
_INSPECT = "Inspect: forge policy supervisor status --json; forge session show <session> --json."
_EVIDENCE_NOTICE = "Policy evidence could not be saved; the verdict is unchanged."
_NO_QUOTE = "No verified plan quotation is available."
_UNREVIEWED = "Policy review unavailable; this allowed action is unreviewed."
_RECOVERY = {
    "timeout": "Reviewer timed out. Check supervisor status and its timeout setting.",
    "subscription_exhausted": "Reviewer subscription exhausted. Restore quota before relying on review.",
    "auth_unavailable": "Reviewer authentication unavailable. Check the configured reviewer login.",
    "config": "Reviewer configuration is invalid. Check supervisor status.",
    "plan_missing": "Approved plan is unavailable. Restore the configured plan file.",
    "parse_failure": "Reviewer response was invalid. Check supervisor status and review evidence.",
}


@dataclass(frozen=True)
class _Finding:
    path: str | None
    policy: str
    violation: Violation | None = None
    intent: str | None = None
    warning: str | None = None
    diagnostic: str | None = None


def render_policy_feedback(
    file_results: list[tuple[str | None, CompositeDecision]],
    *,
    model_feedback: bool,
    source_only: bool,
    supported: bool,
    persistence_failed: bool = False,
) -> str | None:
    """Select audiences without altering verdicts, records, or policy state.

    New allow channels require measured executor identity. Blocking output keeps
    the existing wire on every version. All arbitrary text is quoted JSON data;
    quoting is attribution, not a claim of prompt-injection immunity.
    """
    denied = [(p, r) for p, r in file_results if r.final_decision == "deny"]
    review = [(p, r) for p, r in file_results if r.final_decision == "needs_review"]
    selected = denied or review or file_results
    blocked = bool(denied or review)
    findings, notices = _collect(selected, blocked=blocked)
    if persistence_failed:
        notices.append(_Finding(None, "forge.policy", diagnostic="evidence_unavailable"))
    title = (
        "Policy blocked this patch."
        if denied
        else (
            "Policy review required; this patch remains blocked."
            if review
            else "Policy warnings for an allowed action."
        )
    )
    model_title = title + " The following JSON entries are quoted policy evidence."
    if blocked:
        model_title += " Note: This policy was configured by the project owner."
        if source_only:
            model_title += " Stop and ask the operator before retrying when no verified quotation explains the block."
    wire: dict[str, Any] = {}
    if blocked or (supported and model_feedback and findings):
        context = _channel(findings, model_title, MODEL_BYTES, source_only=source_only)
        hook: dict[str, str] = {"hookEventName": "PreToolUse"}
        if blocked:
            hook.update(permissionDecision="deny", permissionDecisionReason=context)
        else:
            hook["additionalContext"] = context
        wire["hookSpecificOutput"] = hook
    if supported and (findings or notices):
        wire["systemMessage"] = _channel(findings + notices, title, OPERATOR_BYTES, source_only=False, operator=True)
    if not wire:
        return None
    serialized = _json(wire)
    # Field budgets count JSON-encoded strings, including escape expansion.
    assert len(serialized.encode("utf-8")) <= WIRE_BYTES
    return serialized


def _collect(
    results: list[tuple[str | None, CompositeDecision]], *, blocked: bool
) -> tuple[list[_Finding], list[_Finding]]:
    findings: list[_Finding] = []
    notices: list[_Finding] = []
    for path, result in results:
        for decision in result.decisions:
            codes = decision.diagnostic_codes
            if "evidence_unavailable" in codes or decision.failure_type == "evidence_unavailable":
                notices.append(_Finding(path, decision.policy_id, diagnostic="evidence_unavailable"))
            if blocked:
                if decision.decision != result.final_decision:
                    continue
                findings.extend(_violations(path, decision, decision.violations))
                if not decision.violations:
                    findings.append(_Finding(path, decision.policy_id, diagnostic="unresolved"))
            elif decision.failure_type in ("skipped", "evidence_unavailable") or "unconfigured" in codes:
                continue
            elif decision.fail_open or decision.failure_type:
                findings.append(_Finding(path, decision.policy_id, diagnostic=decision.failure_type or "unavailable"))
            elif decision.warning_findings:
                findings.extend(_violations(path, decision, decision.warning_findings))
            elif not codes:
                # Legacy/free-form warnings retain their owner; source-only never
                # treats a plain string as a verified quotation or authored policy.
                findings.extend(_Finding(path, decision.policy_id, warning=w) for w in decision.warnings)
        if blocked and not any(f.path == path for f in findings):
            findings.append(_Finding(path, "forge.policy", diagnostic="unresolved"))
    return findings, notices


def _violations(path: str | None, decision: PolicyDecision, violations: list[Violation]) -> list[_Finding]:
    return [_Finding(path, decision.policy_id, v, decision.intent) for v in violations]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _projection(finding: _Finding, *, source_only: bool, limit: int, operator: bool) -> tuple[dict[str, Any], bool]:
    truncated = False

    def clip(value: object) -> str:
        nonlocal truncated
        text = value if isinstance(value, str) else ""
        if len(text) > limit:
            truncated = True
        return text[:limit]

    v = finding.violation
    rule = v.rule_id if v else finding.policy
    data: dict[str, Any] = {"path": clip(finding.path), "policy": clip(finding.policy), "rule": clip(rule)}
    # A shortened path remains distinguishable from another path with the same prefix.
    if finding.path and len(finding.path) > limit:
        data["path_sha256"] = hashlib.sha256(finding.path.encode()).hexdigest()
    for key, value in (("rule", rule), ("policy", finding.policy)):
        if len(value) > limit:
            data[key + "_sha256"] = hashlib.sha256(value.encode()).hexdigest()
    data["label"] = clip(f"{finding.path or '?'}: [{rule}]")
    if finding.diagnostic:
        code = finding.diagnostic
        if code == "evidence_unavailable":
            data["status"] = _EVIDENCE_NOTICE
        elif code == "unresolved":
            data["status"] = "Review unresolved; this patch remains blocked. " + _NO_QUOTE
        else:
            data["status"] = _UNREVIEWED
            if operator:
                data["recovery"] = _RECOVERY.get(
                    code, "Reviewer unavailable. Check supervisor status and review evidence."
                )
    elif source_only and (v is None or v.provenance != "policy"):
        quotes = []
        if v is not None:
            for quote in v.verified_citations[:3]:
                text = clip(quote.text)
                quotes.append(
                    {
                        "source": clip(quote.source),
                        "sha256": quote.digest,
                        "start": quote.start,
                        "end": quote.start + len(text),
                        "text": text,
                    }
                )
            truncated |= len(v.verified_citations) > 3
        data["status"] = (
            "Policy finding; verified approved-plan quotations follow."
            if quotes
            else "Policy reported a finding. " + _NO_QUOTE
        )
        data["quotes"] = quotes
    elif v is not None:
        data.update(
            severity=clip(v.severity),
            message=clip(v.message),
            intent=clip(finding.intent),
            evidence=clip(v.evidence),
            suggested_fix=clip(v.suggested_fix),
        )
        data["citations"] = [clip(c) for c in v.citations[:3]]
        truncated |= len(v.citations) > 3
    else:
        data["message"] = clip(finding.warning)
    if truncated:
        data["truncated"] = True
    return data, truncated


def _channel(findings: list[_Finding], title: str, budget: int, *, source_only: bool, operator: bool = False) -> str:
    # Deduplicate the full attributed finding before truncation, within this response only.
    unique = {_json(asdict(f)): f for f in findings}
    ordered = sorted(
        unique.values(), key=lambda f: (f.path or "", f.policy, f.violation.rule_id if f.violation else "")
    )
    lines: list[str] = []
    omitted = 0
    truncated = 0
    footer = "\n" + _INSPECT if operator else ""

    def assemble(skipped: int, shortened: int) -> str:
        return (
            title
            + "\n"
            + "\n".join(lines)
            + f"\nOmitted findings: {skipped}. Truncated findings: {shortened}."
            + footer
        )

    for finding in ordered:
        if len(lines) >= FINDING_LIMIT:
            omitted += 1
            continue
        limit = FIELD_CHARS
        data, shortened = _projection(finding, source_only=source_only, limit=limit, operator=operator)
        while len(_json(data).encode()) > FINDING_BYTES and limit > 8:
            limit //= 2
            data, shortened = _projection(finding, source_only=source_only, limit=limit, operator=operator)
        line = _json(data)
        if len(line.encode()) > FINDING_BYTES:
            omitted += 1
            continue
        lines.append(line)
        # Reserve final counters at their maximum length before accepting a finding.
        if len(_json(assemble(len(ordered), len(ordered))).encode()) > budget:
            lines.pop()
            omitted += 1
        else:
            truncated += int(shortened)
    return assemble(omitted, truncated)
