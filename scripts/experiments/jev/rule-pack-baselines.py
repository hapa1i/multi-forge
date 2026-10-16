"""Compare bounded marker and Python structural signals offline; no quality or runtime verdict."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from forge.cli.hooks import codex_patch
from forge.core.judgments.types import JudgmentError
from forge.policy.deterministic import coding_standards

BASELINE_VERSION = 1
Function = ast.FunctionDef | ast.AsyncFunctionDef


def _load_evaluator() -> Any:
    path = Path(__file__).with_name("rule-pack-eval.py")
    spec = importlib.util.spec_from_file_location("jev_rule_pack_eval_baselines", path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load the neighboring rule-pack evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


evaluator = _load_evaluator()


def marker_signal(action: Any) -> dict[str, Any]:
    """Apply the current policy's unchanged patterns to supplied proposed Python text."""
    raw = action.tool_input
    if action.tool_name == "apply_patch":
        operations = codex_patch.parse_apply_patch(raw["command"])
        assert operations is not None  # The shared preparation has validated the action envelope.
        inputs = [(op.path, op.added_content) for op in operations if op.kind != "delete"]
    else:
        inputs = [(raw["file_path"], raw["content"] if action.tool_name == "Write" else raw["new_string"])]
    python_inputs = [(path, text) for path, text in inputs if path.endswith(".py")]
    matches = [
        {
            "path": path,
            "patterns": [p for p in coding_standards.BACKWARD_COMPAT_PATTERNS if re.search(p, text, re.MULTILINE)],
        }
        for path, text in python_inputs
    ]
    supported = bool(inputs) and len(python_inputs) == len(inputs)
    return {
        "status": "assessed" if supported else "unavailable",
        "reason": None if supported else "unsupported_non_python_or_deletion_action",
        "flagged": any(row["patterns"] for row in matches) if supported else None,
        "raw_matches": matches,
    }


def _scope_nodes(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Walk one lexical scope without borrowing bindings from nested functions or classes."""
    for node in nodes:
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from _scope_nodes(ast.iter_child_nodes(node))


def _bindings(nodes: Iterable[ast.AST]) -> list[str]:
    """Collect supplied bindings conservatively; unresolved wildcard imports have no safe name set."""
    names = []
    for node in _scope_nodes(nodes):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.append(node.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    raise ValueError("ambiguous_target_binding")
                names.append(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.extend(node.names)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name is not None:
            names.append(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            names.append(node.rest)
    return names


def _definitions(tree: ast.Module) -> tuple[dict[str, Function], dict[str, str]]:
    functions: dict[str, Function] = {}
    aliases: dict[str, str] = {}
    names: set[str] = set()

    def visit(body: list[ast.stmt], prefix: str = "") -> None:
        for node in body:
            for binding in _bindings([node]):
                name = prefix + binding
                if name in names:
                    raise ValueError("ambiguous_repeated_binding")
                names.add(name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                visit(node.body, prefix + node.name + ".")
            elif (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Name)
            ):
                aliases[prefix + node.targets[0].id] = prefix + node.value.id

    visit(tree.body)
    return functions, aliases


def _has_shadowed_target(function: Function, targets: set[str]) -> bool:
    args = function.args
    parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    parameters.extend(arg for arg in (args.vararg, args.kwarg) if arg is not None)
    bindings = {arg.arg for arg in parameters} | set(_bindings(function.body))
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in bindings & targets
        for node in _scope_nodes(function.body)
    )


def _body(function: Function) -> list[ast.stmt]:
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    return body


def _adapter_call(function: Function) -> ast.Call | None:
    """Recognize direct forwarding or a local result's tuple/dict/subscript adaptation."""
    body = _body(function)
    while body and isinstance(body[0], ast.If):
        guard = body[0]
        if guard.orelse or not all(isinstance(node, ast.Raise) for node in guard.body):
            return None
        body = body[1:]
    if len(body) == 1 and isinstance(body[0], (ast.Return, ast.Expr)):
        return body[0].value if isinstance(body[0].value, ast.Call) else None
    if len(body) != 2 or not isinstance(body[0], ast.Assign) or not isinstance(body[1], ast.Return):
        return None
    assignment = body[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.targets[0], ast.Name):
        return None
    if not isinstance(assignment.value, ast.Call) or body[1].value is None:
        return None
    value = body[1].value
    allowed = (ast.Tuple, ast.List, ast.Dict, ast.Subscript, ast.Name, ast.Constant, ast.Load)
    if any(not isinstance(node, allowed) for node in ast.walk(value)):
        return None
    names = {node.id for node in ast.walk(value) if isinstance(node, ast.Name)}
    return assignment.value if names == {assignment.targets[0].id} else None


def _target(call: ast.Call, interface: str, function: Function) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    args = function.args.posonlyargs + function.args.args
    if (
        "." in interface
        and args
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == args[0].arg
    ):
        return interface.rsplit(".", 1)[0] + "." + call.func.attr
    return None


def structural_signal(action: Any) -> dict[str, Any]:
    """Flag supplied retention shapes, without interpreting consumer contracts or fetching missing context."""
    unavailable: dict[str, Any] = {"status": "unavailable", "flagged": None, "candidates": []}
    if action.tool_name != "Edit":
        return {**unavailable, "reason": "unsupported_tool_shape"}
    raw = action.tool_input
    if not raw["file_path"].endswith(".py"):
        return {**unavailable, "reason": "unsupported_non_python_action"}
    try:
        before_tree, after_tree = (ast.parse(raw[key]) for key in ("old_string", "new_string"))
        before, _ = _definitions(before_tree)
        after, aliases = _definitions(after_tree)
    except (SyntaxError, ValueError, RecursionError) as exc:
        reason = str(exc) if str(exc).startswith("ambiguous_") else "unparseable_python_evidence"
        return {**unavailable, "reason": reason}
    if not before or not after:
        return {**unavailable, "reason": "missing_complete_interface_definitions"}
    candidates = []
    missing_targets = []
    target: str | None
    for name, old in before.items():
        if name in aliases:
            target = aliases[name]
            if target in after and target not in before:
                candidates.append({"interface": name, "target": target, "shape": "alias"})
            elif target not in after:
                missing_targets.append(target)
        if name not in after or ast.dump(old) == ast.dump(after[name]):
            continue
        try:
            if _has_shadowed_target(after[name], set(after)) or _has_shadowed_target(old, set(before)):
                return {**unavailable, "reason": "ambiguous_target_binding"}
        except ValueError:
            return {**unavailable, "reason": "ambiguous_target_binding"}
        old_call = _adapter_call(old)
        if old_call is not None and _target(old_call, name, old) in before:
            # Retargeting an existing local caller is not evidence that its own implementation was replaced.
            continue
        call = _adapter_call(after[name])
        target = _target(call, name, after[name]) if call is not None else None
        if target is None:
            continue
        if target in after and target not in before:
            candidates.append({"interface": name, "target": target, "shape": "forward_or_adapter"})
        elif target not in after:
            missing_targets.append(target)
    if missing_targets:
        return {
            **unavailable,
            "reason": "replacement_definition_missing",
            "candidates": candidates,
            "missing_targets": sorted(set(missing_targets)),
        }
    return {"status": "assessed", "reason": None, "flagged": bool(candidates), "candidates": candidates}


def compare(corpus: Any) -> dict[str, Any]:
    """Share Jev's input admission while keeping labels and semantic verdicts out of both detectors."""
    prepared = evaluator.prepare(corpus)
    cases = []
    for case, admitted in zip(corpus.cases, prepared["cases"], strict=True):
        marker = marker_signal(case.action)
        host = admitted["preparation"] == "host_decision"
        if host:
            marker.update(status="host_decision", reason=admitted["host_reason"], flagged=None)
            structure = {
                "status": "host_decision",
                "reason": admitted["host_reason"],
                "flagged": None,
                "candidates": [],
            }
        else:
            structure = structural_signal(case.action)
        cases.append(
            {
                "id": case.id,
                "family": case.family,
                "split": case.split,
                "provenance": case.provenance.model_dump(),
                "case_sha256": admitted["case_sha256"],
                "payload_sha256": admitted.get("payload_sha256"),
                "request_bytes": admitted.get("request_bytes"),
                "admission": admitted["preparation"],
                "host_outcome": admitted.get("host_outcome"),
                "marker_regex": marker,
                "structural_ast": structure,
            }
        )
    sources = evaluator._evaluator_sources()
    sources["rule-pack-baselines.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for module in (coding_standards, codex_patch):
        assert module.__file__ is not None
        sources[module.__name__] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return {
        "mode": "offline_baselines",
        "baseline_version": BASELINE_VERSION,
        "rule_id": evaluator.RULE_ID,
        "rule_version": evaluator.RULE_VERSION,
        "evidence_contract_version": evaluator.CONTRACT_VERSION,
        "corpus_sha256": evaluator.corpus_digest(corpus),
        "prompt_sha256": prepared["prompt_sha256"],
        "sources": sources,
        "sources_sha256": evaluator._digest(sources),
        "max_physical_requests": 0,
        "quality_accepted": False,
        "claim": (
            "Raw marker and structural retention candidates; "
            "neither detector assesses independent boundary or quality."
        ),
        "limitations": [
            "No repository reads supplement the supplied action evidence.",
            "AST supports complete Python Edit declarations; apply_patch and partial snippets are unavailable.",
            "Supplied shadowing or repeated bindings are unavailable; AST name matching is not full name resolution.",
            "AST matches new supplied targets in direct forwarding, guarded forwarding, "
            "local return adapters or aliases.",
            "Retargeted calls to existing local definitions are excluded; this can miss some replacement shapes.",
            "Legitimate boundary adapters can be flagged; "
            "absent patterns do not establish no_warning or sufficient coverage.",
            "Marker patterns scan proposed Python text, including added patch lines, "
            "using the existing policy patterns.",
            "This comparison uses Jev host gates and input limits; "
            "it is not a replay of the full deterministic policy engine.",
        ],
        "counts": {
            baseline: dict(Counter(f"{row[baseline]['status']}/{row[baseline]['flagged']}" for row in cases))
            for baseline in ("marker_regex", "structural_ast")
        },
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args()
    try:
        corpus = evaluator.Corpus.model_validate(evaluator._read_json(args.corpus, evaluator.MAX_CORPUS_BYTES))
        print(json.dumps(compare(corpus), indent=2, allow_nan=False))
    except (OSError, ValueError, JudgmentError, RecursionError, OverflowError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
