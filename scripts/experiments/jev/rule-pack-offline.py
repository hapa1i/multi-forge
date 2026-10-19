"""Compare the frozen constructed A2 inputs with existing local structural signals; no inference or runtime verdict."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "docs/board/retired/jev_rule_pack/evidence"
REVIEW = EVIDENCE / "diagnostic-review-2026-10-18-batch-6.json"
CORPUS = EVIDENCE / "wrapper-corpus.json"
MAX_REVIEW_BYTES = 2_000_000
MAX_REPORT_BYTES = 1_000_000


def _load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


baseline = _load("jev_offline_baselines", "rule-pack-baselines.py")
diagnostic = _load("jev_offline_diagnostic", "rule-pack-diagnostic.py")
evaluator = baseline.evaluator


def syntax_presence(action: Any, targets: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Locate declarations for supplied lookup names, without inferring completeness or semantic retention."""
    images: dict[str, tuple[dict[str, Any] | None, str | None]]
    if action.tool_name != "Edit" or not action.tool_input["file_path"].endswith(".py"):
        images = {name: (None, "unsupported_action_shape") for name in ("old_string", "new_string")}
    else:
        images = {name: _image_declarations(action.tool_input[name]) for name in ("old_string", "new_string")}
    result = []
    for target in targets:
        lookups = []
        for role, image, symbol in (
            ("prior", "old_string", target["prior_symbol"]),
            ("proposed", "new_string", target["retained_symbol"]),
            ("replacement", "new_string", target["replacement_symbol"]),
        ):
            declarations, reason = images[image]
            declaration = declarations.get(symbol) if declarations is not None else None
            lookups.append(
                {
                    "role": role,
                    "image": image,
                    "symbol": symbol,
                    "status": (
                        "unavailable"
                        if declarations is None
                        else "declaration_found" if declaration else "not_found_in_supplied_image"
                    ),
                    "reason": reason,
                    "declaration": declaration,
                }
            )
        result.append({"target_id": target["id"], "lookups": lookups})
    return result


def build_report(review: dict[str, Any], corpus: Any) -> dict[str, Any]:
    """Report only the existing 12 diagnostic and 17 constructed cases, retaining all baseline refusals."""
    summary = diagnostic.validate_review(review)
    if (
        summary["contract_status"] != "reviewed"
        or summary["fully_answered_cases"] != 12
        or summary["answered_questions"] != 95
        or summary["unanswered_questions"]
        or summary["disputed_cases"]
    ):
        raise ValueError("The offline comparison requires the completed 12-case, 95-answer diagnostic review")
    # These inputs name one bounded audit, not an entry point for collecting another cohort or replacing labels.
    frozen_review = evaluator._read_json(REVIEW, MAX_REVIEW_BYTES)
    frozen_corpus = evaluator.Corpus.model_validate(evaluator._read_json(CORPUS, evaluator.MAX_CORPUS_BYTES))
    if evaluator._digest(review) != evaluator._digest(frozen_review) or evaluator._digest(
        corpus.model_dump()
    ) != evaluator._digest(frozen_corpus.model_dump()):
        raise ValueError("Inputs differ from the frozen completed diagnostic review or constructed corpus")
    if len(corpus.cases) != 17 or any(case.provenance.kind != "constructed" for case in corpus.cases):
        raise ValueError("The offline comparison admits only the 17 constructed corpus cases")
    compared = baseline.compare(corpus)
    rows = []
    for case in review["cases"]:
        action = evaluator.Action.model_validate(case["action"])
        # The diagnostic validator admits intentional missing-history controls that ordinary Edit admission rejects.
        scope = case["scope_facts"]
        host = evaluator.assess_applicability(
            surface=scope["surface"],
            compatibility_decision=scope["compatibility_decision"],
            tool_name=action.tool_name,
        )
        structure = baseline.structural_signal(action)
        selected = {(item["prior_symbol"], item["replacement_symbol"]): item["id"] for item in case["targets"]}
        candidates = {(item["interface"], item["target"]) for item in structure["candidates"]}
        rows.append(
            {
                "cohort": "diagnostic",
                "case_id": case["id"],
                "family": case["family"],
                "case_sha256": case["case_sha256"],
                "action_sha256": evaluator._digest(case["action"]),
                "host_applicability": _host_result(host),
                "marker_regex": baseline.marker_signal(action),
                "structural_ast": structure,
                "targets_origin": "reviewed_lookup_hints",
                "syntactic_presence": syntax_presence(action, case["targets"]),
                "candidate_membership": {
                    "matched_target_ids": [identifier for pair, identifier in selected.items() if pair in candidates],
                    "selected_without_recognized_candidate": [
                        identifier for pair, identifier in selected.items() if pair not in candidates
                    ],
                    "additional_candidates": [
                        item for item in structure["candidates"] if (item["interface"], item["target"]) not in selected
                    ],
                },
            }
        )
    by_id = {case.id: case for case in corpus.cases}
    for compared_case in compared["cases"]:
        case = by_id[compared_case["id"]]
        candidates = compared_case["structural_ast"]["candidates"]
        targets = [
            {
                "id": f"candidate-{index}",
                "prior_symbol": item["interface"],
                "retained_symbol": item["interface"],
                "replacement_symbol": item["target"],
            }
            for index, item in enumerate(candidates, 1)
        ]
        host = evaluator.host_decision(case)
        rows.append(
            {
                "cohort": "constructed",
                "case_id": case.id,
                "family": case.family,
                "case_sha256": compared_case["case_sha256"],
                "action_sha256": evaluator._digest(case.action.model_dump()),
                "host_applicability": (
                    {"status": "host_decision", "outcome": host[0], "reason": host[1]} if host else _host_result(None)
                ),
                "marker_regex": compared_case["marker_regex"],
                "structural_ast": compared_case["structural_ast"],
                "targets_origin": "baseline_candidates_only",
                "syntactic_presence": syntax_presence(case.action, targets),
                "candidate_membership": None,
            }
        )
    sources = dict(compared["sources"])
    for filename in (Path(__file__).name, "rule-pack-diagnostic.py", "diagnostic_review.py"):
        sources[filename] = hashlib.sha256(Path(__file__).with_name(filename).read_bytes()).hexdigest()
    report = {
        "schema_version": 1,
        "mode": "bounded_offline_structure_comparison",
        "max_physical_requests": 0,
        "quality_accepted": False,
        "runtime_admitted": False,
        "baseline_version": compared["baseline_version"],
        "rule_id": compared["rule_id"],
        "rule_version": compared["rule_version"],
        "evidence_contract_version": compared["evidence_contract_version"],
        "input_identity_encoding": "SHA-256 of complete canonical JSON: sorted keys, compact UTF-8, no nonfinite numbers",
        "inputs": {
            "completed_review_sha256": evaluator._digest(review),
            "diagnostic_packet_sha256": review["packet_sha256"],
            "constructed_corpus_sha256": evaluator._digest(corpus.model_dump()),
        },
        "sources": sources,
        "sources_sha256": evaluator._digest(sources),
        "limitations": [
            "Declaration spans identify supplied Python syntax, not complete interface evidence or semantic answers.",
            "Source spans are one-based lines and zero-based UTF-8 byte columns; end columns are exclusive.",
            "Lookup hints do not supply definitions; unsupported or ambiguous syntax remains unavailable.",
            "The declaration index covers module functions, classes, class methods and simple name aliases only.",
            "Candidate membership differences are not false positives, misses or selector quality measurements.",
            "No recognized shape does not establish coverage, no_warning or a safe deletion.",
            "Raw structural candidates do not assess consumer requirements, governance authority or warning usefulness.",
            "Constructed and diagnostic cases overlap; their counts are not independent evidence or runtime coverage.",
            "No labels, criteria, captured responses or active-rule settings are changed or scored.",
        ],
        "counts": {
            cohort: {
                "cases": sum(row["cohort"] == cohort for row in rows),
                "structural_ast": dict(
                    Counter(
                        f"{row['structural_ast']['status']}/{row['structural_ast']['flagged']}"
                        for row in rows
                        if row["cohort"] == cohort
                    )
                ),
            }
            for cohort in ("diagnostic", "constructed")
        },
        "cases": rows,
    }
    if len(_render(report).encode("utf-8")) > MAX_REPORT_BYTES:
        raise ValueError("Offline comparison exceeds its bounded report size")
    return report


def _host_result(assessment: Any) -> dict[str, Any]:
    if assessment is None:
        return {"status": "not_host_decided", "outcome": None, "reason": None}
    return {"status": "host_decision", "outcome": assessment.outcome, "reason": assessment.reason}


def _image_declarations(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        tree = ast.parse(text)
        baseline._definitions(tree)  # Reuse the baseline's conservative duplicate/wildcard-binding refusal.
    except (SyntaxError, ValueError, RecursionError) as exc:
        return None, str(exc) if str(exc).startswith("ambiguous_") else "unparseable_python_evidence"
    declarations = {}

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + node.name
                declarations[name] = {
                    "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "span": _span(node),
                }
                if isinstance(node, ast.ClassDef):
                    visit(node.body, name + ".")
            elif (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Name)
            ):
                declarations[prefix + node.targets[0].id] = {
                    "kind": "alias",
                    "target": prefix + node.value.id,
                    "span": _span(node),
                }

    visit(tree.body)
    return declarations, None


def _span(node: ast.stmt) -> dict[str, int | None]:
    return {
        "start_line": node.lineno,
        "start_utf8_column": node.col_offset,
        "end_line": node.end_lineno,
        "end_utf8_column": node.end_col_offset,
    }


def _render(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    args = parser.parse_args()
    try:
        review = evaluator._read_json(args.review, MAX_REVIEW_BYTES)
        corpus = evaluator.Corpus.model_validate(evaluator._read_json(args.corpus, evaluator.MAX_CORPUS_BYTES))
        report = build_report(review, corpus)
        print(_render(report), end="")
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
