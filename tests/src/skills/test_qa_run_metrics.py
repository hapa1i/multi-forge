from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "src" / "skills" / "qa" / "scripts" / "qa-run-metrics.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("forge_qa_run_metrics_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


METRICS = _load()


def _artifact(*, mode: str = "prebuilt", blocking: bool = True) -> dict:
    track = "pinned" if blocking else "latest"
    return {
        "schema_version": 1,
        "artifact": {"mode": mode},
        "driver": {"matches_artifact": True, "sha256": "a" * 64},
        "runtime": {
            "track": track,
            "blocking": blocking,
            "claude": {
                "pin": "2.1.245" if blocking else "latest",
                "observed": "start-claude",
            },
            "codex": {
                "pin": "0.149.1" if blocking else "latest",
                "observed": "start-codex",
            },
        },
    }


def _runtime_final(*, blocking: bool = True, preserved: bool = True) -> dict:
    return {
        "schema_version": 1,
        "track": "pinned" if blocking else "latest",
        "blocking": blocking,
        "identity_preserved": preserved,
        "claude": {
            "pin": "2.1.245" if blocking else "latest",
            "observed": "2.1.245" if preserved else "2.1.247",
            "available": True,
            "matches_pin": preserved if blocking else None,
        },
        "codex": {
            "pin": "0.149.1" if blocking else "latest",
            "observed": "0.149.1",
            "available": True,
            "matches_pin": True if blocking else None,
        },
    }


def _selection(*, partial: bool = False) -> dict:
    return {
        "schema_version": 1,
        "mode": "blocking",
        "evidence_lanes": ["clean-wheel-smoke", "human-acceptance"],
        "categories": ["session"] if partial else [],
        "from": None,
        "to": None,
        "steps": [
            {
                "id": "1.1",
                "section_id": "1",
                "assertion_count": 2,
                "execution_class": "auto",
                "evidence_lane": "clean-wheel-smoke",
                "paid_operations": 1,
                "step_hash": "hash-1",
            },
            {
                "id": "1.2",
                "section_id": "1",
                "assertion_count": 1,
                "execution_class": "human:guided",
                "evidence_lane": "human-acceptance",
                "paid_operations": 0,
                "step_hash": "hash-2",
            },
            {
                "id": "1.3",
                "section_id": "1",
                "assertion_count": 1,
                "execution_class": "auto",
                "evidence_lane": "extended-exploratory",
                "paid_operations": 1,
                "step_hash": "hash-3",
            },
        ],
        "selected_counts": {
            "steps": 3,
            "assertions": 4,
            "human_checkpoints": 1,
            "paid_operations": 2,
        },
        "blocking_counts": {
            "steps": 2,
            "assertions": 3,
            "human_checkpoints": 1,
            "paid_operations": 1,
        },
        "blocking_limits": {
            "max_human_checkpoints": 12,
            "max_paid_operations": 8,
            "duration_review_seconds": 2700,
        },
    }


def _state(*, second_result: str = "pass", include_second: bool = True) -> dict:
    steps = {"1.1": {"scope": "container:one", "results": ["pass", "pass"], "hash": "hash-1"}}
    if include_second:
        steps["1.2"] = {
            "scope": "container:one",
            "results": [second_result],
            "hash": "hash-2",
        }
    return {
        "vars": {"RUN_SCOPE": "container:one", "PAID_OPERATIONS_1_1": "1"},
        "steps": steps,
    }


def _compute(**kwargs):
    return METRICS.compute_metrics(
        artifact=kwargs.pop("artifact", _artifact()),
        runtime_final=kwargs.pop("runtime_final", _runtime_final()),
        selection=kwargs.pop("selection", _selection()),
        state=kwargs.pop("state", _state()),
        started_epoch=100,
        ended_epoch=kwargs.pop("ended_epoch", 200),
        **kwargs,
    )


def test_full_pinned_prebuilt_pass_ignores_unrecorded_exploratory_step() -> None:
    result = _compute()

    assert result["verdict"] == "pass"
    assert result["counts"]["blocking_results"] == {"pass": 3, "fail": 0, "skip": 0}
    assert result["counts"]["human_checkpoints_completed"] == 1
    assert result["counts"]["blocking_human_checkpoints_completed"] == 1
    assert result["counts"]["paid_operations_observed"] == 1
    assert result["counts"]["blocking_paid_operations_observed"] == 1
    assert result["gaps"]["missing_blocking_steps"] == []
    assert result["gaps"]["missing_selected_steps"] == ["1.3"]
    assert result["sections"] == [
        {
            "id": "1",
            "expected": 4,
            "pass": 3,
            "fail": 0,
            "skip": 0,
            "missing_steps": ["1.3"],
        }
    ]


@pytest.mark.parametrize(
    ("artifact", "selection", "state", "expected"),
    [
        (
            _artifact(mode="development-build"),
            _selection(),
            _state(),
            "development-only",
        ),
        (_artifact(blocking=False), _selection(), _state(), "compatibility-only"),
        (_artifact(), _selection(partial=True), _state(), "partial"),
        (_artifact(), _selection(), _state(second_result="fail"), "fail"),
        (_artifact(), _selection(), _state(second_result="skip"), "incomplete"),
        (_artifact(), _selection(), _state(include_second=False), "incomplete"),
    ],
)
def test_verdict_cannot_overstate_saved_evidence(artifact: dict, selection: dict, state: dict, expected: str) -> None:
    final = _runtime_final(blocking=artifact["runtime"]["blocking"])
    assert _compute(artifact=artifact, runtime_final=final, selection=selection, state=state)["verdict"] == expected


def test_runtime_drift_forces_failure_and_revokes_release_capability() -> None:
    result = _compute(runtime_final=_runtime_final(preserved=False))

    assert result["verdict"] == "fail"
    assert result["artifact_release_capable"] is False
    assert result["runtime_identity"]["preserved"] is False


def test_runtime_unavailability_forces_failure() -> None:
    final = _runtime_final(preserved=False)
    final["claude"]["available"] = False
    final["claude"]["observed"] = "container not running"

    result = _compute(runtime_final=final)

    assert result["verdict"] == "fail"
    assert result["artifact_release_capable"] is False


def test_missing_or_mismatched_driver_identity_fails_closed() -> None:
    missing = _artifact()
    del missing["driver"]
    mismatched = _artifact()
    mismatched["driver"]["matches_artifact"] = False

    with pytest.raises(METRICS.MetricsError, match="QA driver identity"):
        _compute(artifact=missing)
    with pytest.raises(METRICS.MetricsError, match="QA driver identity"):
        _compute(artifact=mismatched)


def test_duration_requires_review_without_becoming_failure() -> None:
    pending = _compute(ended_epoch=2801)
    disposed = _compute(ended_epoch=2801, duration_disposition="accepted provider variance")

    assert pending["duration"]["budget_review_required"] is True
    assert pending["verdict"] == "pass-review-required"
    assert disposed["verdict"] == "pass"
    assert disposed["duration"]["maintainer_disposition"] == "accepted provider variance"


def test_skipped_human_and_stale_paid_values_are_not_counted_as_completed() -> None:
    state = _state(second_result="skip")
    state["vars"]["PAID_OPERATIONS_1_3"] = "1"

    result = _compute(state=state)

    assert result["counts"]["human_checkpoints_completed"] == 0
    assert result["counts"]["paid_operations_observed"] == 1


def test_failed_paid_step_may_record_zero_completed_operations() -> None:
    state = _state()
    state["steps"]["1.1"]["results"] = ["fail", "fail"]
    state["vars"]["PAID_OPERATIONS_1_1"] = "0"

    result = _compute(state=state)

    assert result["verdict"] == "fail"
    assert result["counts"]["blocking_paid_operations_observed"] == 0


def test_invalid_time_or_budget_state_fails_closed() -> None:
    with pytest.raises(METRICS.MetricsError, match="precedes"):
        METRICS.compute_metrics(
            artifact=_artifact(),
            runtime_final=_runtime_final(),
            selection=_selection(),
            state=_state(),
            started_epoch=200,
            ended_epoch=100,
        )

    state = _state()
    state["vars"]["PAID_OPERATIONS_1_1"] = "not-an-int"
    with pytest.raises(METRICS.MetricsError, match="not an integer"):
        _compute(state=state)

    state = _state()
    state["vars"]["PAID_OPERATIONS_1_1"] = "3"
    with pytest.raises(METRICS.MetricsError, match="between 0 and the step plan"):
        _compute(state=state)

    state = _state()
    del state["vars"]["PAID_OPERATIONS_1_1"]
    with pytest.raises(METRICS.MetricsError, match="is required for recorded paid step"):
        _compute(state=state)

    state = _state()
    state["vars"]["PAID_OPERATIONS_1_1"] = "0"
    with pytest.raises(METRICS.MetricsError, match="must equal the step plan"):
        _compute(state=state)


def test_stale_hash_or_incomplete_assertion_results_fail_closed() -> None:
    stale = _state()
    stale["steps"]["1.1"]["hash"] = "old-hash"
    with pytest.raises(METRICS.MetricsError, match="structural hash"):
        _compute(state=stale)

    incomplete = _state()
    incomplete["steps"]["1.1"]["results"] = ["pass"]
    with pytest.raises(METRICS.MetricsError, match="expects 2 assertion results"):
        _compute(state=incomplete)


def test_failure_precedes_non_release_scope_labels() -> None:
    failing = _state(second_result="fail")

    assert _compute(artifact=_artifact(mode="development-build"), state=failing)["verdict"] == "fail"
    assert _compute(selection=_selection(partial=True), state=failing)["verdict"] == "fail"
