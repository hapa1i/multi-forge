"""Tests for deterministic walkthrough report selection and verdicts."""

from __future__ import annotations

import json
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL = REPO_ROOT / "src/skills/walkthrough"
CHECKLIST = SKILL / "resources/checklist.md"
STATE_SCRIPT = SKILL / "scripts/walkthrough-state.py"
REPORT_SCRIPT = SKILL / "scripts/walkthrough-report.py"


def _state_module():
    spec = spec_from_file_location("forge_walkthrough_report_test_state", STATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _complete_state(
    tmp_path: Path,
    *,
    failing_step: str | None = None,
    codex: bool = False,
    codex_unavailable: bool = False,
    sidecar: bool = False,
) -> tuple[Path, Path]:
    module = _state_module()
    data = module.parse_checklist(str(CHECKLIST))
    state = tmp_path / "progress.json"
    module.cmd_init(data, str(CHECKLIST), str(state), "walkthrough", force=False)
    for key, value in {
        "RUN_OPTIONS": f"codex={str(codex).lower()},sidecar={str(sidecar).lower()}",
        "RUN_STARTED_EPOCH": "1000",
        "CODEX_AUTH_MODE": "none",
        "DECLARED_HUMAN_CHECKPOINTS": "7",
        "HUMAN_CHECKPOINTS_OBSERVED": str(7 + (2 if sidecar else 0)),
        "DECLARED_PAID_OPERATIONS": "2",
        "PAID_OPERATIONS_OBSERVED": str(
            2 + (1 if codex and not codex_unavailable else 0)
        ),
    }.items():
        module.cmd_var(str(state), "set", key, value)

    for step in data["_all_subs"]:
        option_annotations = [
            annotation.split(":", 1)[1].strip()
            for annotation in step["annotations"]
            if annotation.startswith("option:")
        ]
        option = option_annotations[0] if option_annotations else None
        selected = (
            option is None
            or (option == "codex" and codex)
            or (option == "sidecar" and sidecar)
        )
        code = "p" if selected else "s"
        if codex_unavailable and step["id"] == "12.9":
            code = "s"
        results = [code] * step["assertion_count"]
        if step["id"] == failing_step:
            results[0] = "f"
        module.cmd_record(
            data, str(CHECKLIST), str(state), step["id"], ",".join(results), force=False
        )

    identity = tmp_path / "package-identity.json"
    identity.write_text(
        json.dumps(
            {
                "distribution": "multi-forge",
                "version": "1.0.0",
                "skill_root": "/isolated/walkthrough",
                "package_tree_matches_marker": True,
                "package_matches_answering_distribution": True,
                "package_marker_sha256": "sha256:abc",
            }
        )
        + "\n"
    )
    return state, identity


def _run(
    tmp_path: Path, state: Path, identity: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(REPORT_SCRIPT),
            "--checklist",
            str(CHECKLIST),
            "--parser",
            str(STATE_SCRIPT),
            "--state",
            str(state),
            "--package-identity",
            str(identity),
            "--output-dir",
            str(tmp_path / "report"),
            "--ended-epoch",
            "2901",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_default_report_excludes_unselected_optional_assertions(tmp_path: Path) -> None:
    state, identity = _complete_state(tmp_path)

    result = _run(tmp_path, state, identity)

    assert result.returncode == 0, result.stderr
    metrics = json.loads(result.stdout)
    assert metrics["verdict"] == "pass"
    assert metrics["assertions"] == {"pass": 124, "fail": 0, "skip": 0, "missing": 0}
    assert metrics["selection"]["not_selected_assertions"] == 21
    assert metrics["budgets"] == {
        "counts_valid": True,
        "human_declared": 7,
        "human_optional_selected": 0,
        "human_observed": 7,
        "paid_declared": 2,
        "paid_optional_selected": 0,
        "paid_observed": 2,
    }
    assert metrics["optional_results"]["codex"]["status"] == "not-selected"
    assert metrics["optional_results"]["sidecar"]["status"] == "not-selected"
    assert metrics["package_identity"]["version"] == "1.0.0"
    assert metrics["package_identity"]["skill_root"] == "/isolated/walkthrough"
    assert metrics["duration_review_required"] is True
    assert (tmp_path / "report/report.md").exists()
    assert json.loads((tmp_path / "report/selected-options.json").read_text()) == {
        "codex_auth_mode": "none",
        "options": {"codex": False, "sidecar": False},
    }


def test_selected_assertion_failure_produces_fail_verdict(tmp_path: Path) -> None:
    state, identity = _complete_state(tmp_path, failing_step="6.4")

    result = _run(tmp_path, state, identity)

    assert result.returncode == 0
    metrics = json.loads(result.stdout)
    assert metrics["verdict"] == "fail"
    assert metrics["assertions"]["fail"] == 1


def test_unavailable_optional_codex_is_reported_without_changing_default_verdict(
    tmp_path: Path,
) -> None:
    state, identity = _complete_state(tmp_path, codex=True, codex_unavailable=True)

    result = _run(tmp_path, state, identity)

    assert result.returncode == 0, result.stderr
    metrics = json.loads(result.stdout)
    assert metrics["verdict"] == "pass"
    assert metrics["assertions"] == {"pass": 124, "fail": 0, "skip": 0, "missing": 0}
    assert metrics["optional_results"]["codex"] == {
        "pass": 5,
        "fail": 0,
        "skip": 5,
        "missing": 0,
        "status": "unavailable",
    }
    assert metrics["budgets"]["paid_optional_selected"] == 1
    assert metrics["budgets"]["counts_valid"] is True


def test_report_refuses_stale_step_evidence(tmp_path: Path) -> None:
    state, identity = _complete_state(tmp_path)
    data = json.loads(state.read_text())
    data["steps"]["6.4"]["hash"] = "stale"
    state.write_text(json.dumps(data) + "\n")

    result = _run(tmp_path, state, identity)

    assert result.returncode == 2
    assert json.loads(result.stderr) == {
        "status": "error",
        "reason": "stale or unverified result for 6.4",
    }
    assert not (tmp_path / "report/run-metrics.json").exists()


def test_report_refuses_orphaned_step_evidence(tmp_path: Path) -> None:
    state, identity = _complete_state(tmp_path)
    data = json.loads(state.read_text())
    data["steps"]["99.1"] = data["steps"]["0.1"]
    state.write_text(json.dumps(data) + "\n")

    result = _run(tmp_path, state, identity)

    assert result.returncode == 2
    assert json.loads(result.stderr) == {
        "status": "error",
        "reason": "state has orphaned step records: 99.1",
    }
