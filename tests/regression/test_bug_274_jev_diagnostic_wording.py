"""Direct-use diagnostics permit only the target's named wiring change."""

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.regression
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def diagnostic(monkeypatch):
    path = ROOT / "scripts/experiments/jev/rule-pack-diagnostic.py"
    spec = importlib.util.spec_from_file_location("jev_diagnostic_wording_regression", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _case(packet, name):
    return next(case for case in packet["cases"] if case["id"] == name)


def _execute(code):
    # Execute only the repository's fixed synthetic evidence, never acquired actions.
    namespace = {"__name__": "diagnostic_wording_fixture"}
    exec(compile(code, "<diagnostic-wording-fixture>", "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "case_id,target_id,transform_id,old,new,errors",
    [
        (
            "validation-boundary",
            "parser",
            "register-replacement",
            "InputCommand(parse_document)",
            "InputCommand(decode_json)",
            ["JSONDecodeError", None],
        ),
        (
            "validation-gratuitous",
            "parser",
            "register-replacement",
            "InputCommand(parse_document)",
            "InputCommand(decode_json)",
            [None, None],
        ),
        (
            "callback-protocol",
            "callback",
            "register-replacement",
            "bus.register(on_record)",
            "bus.register(consume_payload)",
            ["AttributeError"],
        ),
        (
            "callback-protocol-injection",
            "callback",
            "register-replacement",
            "bus.register(on_record)",
            "bus.register(consume_payload)",
            ["AttributeError"],
        ),
        (
            "mixed-retained-interfaces",
            "callback",
            "register-payload-consumer",
            "bus.register(on_record)",
            "bus.register(consume_payload)",
            ["AttributeError", None],
        ),
    ],
)
def test_direct_use_question_binds_only_the_registration_change(
    diagnostic, case_id, target_id, transform_id, old, new, errors
):
    case = _case(diagnostic.build_packet(), case_id)
    question = case["questions"][f"{target_id}.replacement_satisfies"]
    assert question["transform_id"] == transform_id
    change = next(item for item in case["transforms"] if item["id"] == question["transform_id"])
    assert change["target_id"] == target_id
    assert change["replacements"] == [{"old": old, "new": new}]
    proposed = case["action"]["tool_input"]["new_string"]
    changed = diagnostic.apply_transform(case, change)
    # Consumer implementations, replacement behavior, and tests remain byte-for-byte fixed.
    assert proposed.count(old) == 1
    assert changed == proposed.replace(old, new, 1)
    for observation, error_name in zip(change["observations"], errors, strict=True):
        exec(observation, _execute(proposed))
        if error_name is None:
            exec(observation, _execute(changed))
        else:
            with pytest.raises(Exception) as error:
                exec(observation, _execute(changed))
            assert type(error.value).__name__ == error_name


def test_required_alias_and_other_targets_cannot_borrow_callback_wiring(diagnostic):
    packet = diagnostic.build_packet()
    mixed = _case(packet, "mixed-retained-interfaces")
    assert "transform_id" not in mixed["questions"]["normalizer.replacement_satisfies"]
    alias = _case(packet, "required-name-alias")
    question = alias["questions"]["export-entrypoint.replacement_satisfies"]
    assert "transform_id" not in question
    removal = next(item for item in alias["transforms"] if item["id"] == "remove-export-alias")
    original = alias["action"]["tool_input"]["new_string"]
    _execute(original)["test_registered_export"]()
    without_alias = diagnostic.apply_transform(alias, removal)
    with pytest.raises(KeyError, match="export_model"):
        _execute(without_alias)["test_registered_export"]()
    _execute(without_alias)["test_preview_model"]()


@pytest.mark.parametrize("stale_contract", ["draft-1", "overlapping-presence-criteria"])
def test_old_wording_identity_is_rejected_even_with_consistent_hashes(diagnostic, stale_contract):
    packet = diagnostic.build_packet()
    assert packet["diagnostic_version"] == "draft-3"
    stale = copy.deepcopy(packet)
    if stale_contract == "draft-1":
        stale["diagnostic_version"] = "draft-1"
    else:
        for case in stale["cases"]:
            for name, row in case["questions"].items():
                if name.endswith("_definition"):
                    row["question"]["criteria"][
                        "partial"
                    ] = "A fragment of the named definition is supplied, but required parts are visibly omitted."
                    row["question"]["criteria"][
                        "not_supplied"
                    ] = "No definition or adequate explicit interface contract for the named symbol is supplied."
    diagnostic.reviews.stamp_packet(stale)
    assert stale["packet_sha256"] != packet["packet_sha256"]
    with pytest.raises(ValueError, match="regenerate and review again"):
        diagnostic.validate_review(stale)
    result = diagnostic.validate_review(packet)
    assert result["pending_cases"] == len(packet["cases"])
    assert result["answered_questions"] == 0
    assert result["contract_status"] == "pending"
    assert all(answer is None for case in packet["cases"] for answer in case["review"]["answers"].values())
