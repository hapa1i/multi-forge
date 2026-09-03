"""Executable contract for the packaged v1.0 walkthrough journey."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "src/skills/walkthrough"
CHECKLIST = SKILL_ROOT / "resources/checklist.md"
JOURNEY_MAP = SKILL_ROOT / "resources/journey-map.md"
SKILL_FILE = SKILL_ROOT / "SKILL.md"
STATE_SCRIPT = SKILL_ROOT / "scripts/walkthrough-state.py"
EXECUTION_CLASSES = {"auto", "human:confirm", "human:guided"}
KNOWN_REQUIREMENTS = {"docker", "openrouter-auth", "codex-ready"}
KNOWN_OPTIONS = {"codex", "sidecar"}


def _load_parser():
    spec = spec_from_file_location("forge_walkthrough_contract_parser", STATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARSER = _load_parser()


def _metadata(name: str) -> str:
    match = re.search(rf"^<!-- {re.escape(name)}:\s*(.+?)\s*-->$", CHECKLIST.read_text(), re.MULTILINE)
    assert match is not None, f"missing checklist metadata: {name}"
    return match.group(1)


def _numeric_id(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _modifier(step: dict, prefix: str) -> list[str]:
    return [annotation.split(":", 1)[1].strip() for annotation in step["annotations"] if annotation.startswith(prefix)]


def _paid_operations(step: dict) -> int:
    values = _modifier(step, "paid-operations:")
    assert len(values) <= 1, f"duplicate paid-operation annotation on {step['id']}"
    return int(values[0]) if values else 0


def test_metadata_matches_the_parsed_checklist() -> None:
    data = PARSER.parse_checklist(str(CHECKLIST))

    assert data["version"] == "2.0.0"
    assert _metadata("last-updated") == "2026-09-02"
    assert _metadata("aligned-with") == "v1.0.0"
    assert _metadata("test-count") == f"{data['total_assertions']} assertions"
    assert data["total_assertions"] == 145
    assert _metadata("default-human-checkpoints") == "7"
    assert _metadata("default-paid-operations") == "2"


def test_sections_steps_and_prerequisites_are_unique_ordered_and_closed() -> None:
    data = PARSER.parse_checklist(str(CHECKLIST))
    section_ids = [section["id"] for section in data["sections"]]
    steps = data["_all_subs"]
    step_ids = [step["id"] for step in steps]

    assert section_ids == [str(number) for number in range(14)]
    assert len(step_ids) == len(set(step_ids))
    assert [_numeric_id(step_id) for step_id in step_ids] == sorted(_numeric_id(step_id) for step_id in step_ids)

    positions = {step_id: index for index, step_id in enumerate(step_ids)}
    for step in steps:
        assert step["id"].startswith(f"{step['section_id']}.")
        for prereq in step["prereqs"]:
            assert prereq in positions, f"unknown prerequisite {prereq} on {step['id']}"
            assert positions[prereq] < positions[step["id"]], f"non-earlier prerequisite {prereq} on {step['id']}"
            prereq_step = steps[positions[prereq]]
            if not _modifier(step, "option:"):
                assert not _modifier(prereq_step, "option:"), f"default step {step['id']} depends on optional {prereq}"


def test_cleanup_mutations_require_explicit_approval() -> None:
    steps = {step["id"]: step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"]}

    assert steps["13.1"]["annotation"] == "human:confirm"
    assert steps["13.2"]["prereqs"] == ["13.1"]
    assert steps["13.3"]["prereqs"] == ["13.1"]
    assert steps["13.4"]["prereqs"] == ["13.2", "13.3"]


def test_cleanup_verification_allows_preserved_foreign_artifacts_and_search_state() -> None:
    steps = {step["id"]: step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"]}
    verification = "\n".join(block["code"] for block in steps["13.4"]["code_blocks"])

    assert "test ! -d .forge/artifacts" not in verification
    assert "test ! -d .forge/search-index" not in verification
    assert '".forge/artifacts/$session_name"' in verification
    assert '".forge/prev_sessions/$session_name"' in verification
    assert 'Path(".forge/search-index/documents.json")' in verification
    assert 'row.get("session_name") not in owned' in verification
    for name in (
        "walkthrough-codex",
        "walkthrough-sidecar",
        "walkthrough-continuation",
        "walkthrough-incognito",
        "walkthrough-demo",
    ):
        assert name in verification


def test_annotations_use_the_ratified_vocabulary() -> None:
    data = PARSER.parse_checklist(str(CHECKLIST))

    for step in data["_all_subs"]:
        execution = [annotation for annotation in step["annotations"] if annotation in EXECUTION_CLASSES]
        assert len(execution) == 1, f"{step['id']} needs exactly one explicit execution class"
        assert step["annotation"] == execution[0]

        for annotation in step["annotations"]:
            if annotation in EXECUTION_CLASSES:
                continue
            if annotation.startswith("requires:"):
                assert annotation.split(":", 1)[1].strip() in KNOWN_REQUIREMENTS
                continue
            if annotation.startswith("option:"):
                assert annotation.split(":", 1)[1].strip() in KNOWN_OPTIONS
                assert step["section_id"] == "12"
                continue
            if annotation.startswith("paid-operations:"):
                assert int(annotation.split(":", 1)[1].strip()) > 0
                continue
            raise AssertionError(f"unknown annotation on {step['id']}: {annotation}")


def test_default_and_optional_budgets_are_mechanical() -> None:
    steps = PARSER.parse_checklist(str(CHECKLIST))["_all_subs"]
    default = [step for step in steps if not _modifier(step, "option:")]
    codex = [step for step in steps if _modifier(step, "option:") == ["codex"]]
    sidecar = [step for step in steps if _modifier(step, "option:") == ["sidecar"]]

    default_human = sum(step["annotation"].startswith("human:") for step in default)
    default_paid = sum(_paid_operations(step) for step in default)
    assert (default_human, default_paid) == (7, 2)
    assert default_human <= 8
    assert default_paid <= 3
    assert (
        sum(step["annotation"].startswith("human:") for step in codex),
        sum(map(_paid_operations, codex)),
    ) == (0, 1)
    assert (
        sum(step["annotation"].startswith("human:") for step in sidecar),
        sum(map(_paid_operations, sidecar)),
    ) == (
        2,
        0,
    )
    assert {step["id"] for step in steps if _paid_operations(step)} == {
        "9.2",
        "11.2",
        "12.9",
    }


def test_journey_map_has_one_owner_row_for_every_step() -> None:
    step_ids = {step["id"] for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"]}
    mapped_ids = re.findall(r"^\| (\d+\.\d+)\s+\|", JOURNEY_MAP.read_text(), re.MULTILINE)

    assert len(mapped_ids) == len(set(mapped_ids))
    assert set(mapped_ids) == step_ids


def test_default_path_is_direct_managed_and_provider_neutral() -> None:
    data = PARSER.parse_checklist(str(CHECKLIST))
    steps = {step["id"]: step for step in data["_all_subs"]}
    default_text = "\n".join(
        block["code"]
        for step in data["_all_subs"]
        if not _modifier(step, "option:")
        for block in step["code_blocks"]
        if block["runnable"]
    )

    assert "session start walkthrough-demo --model claude-haiku-4-5 --no-proxy --no-launch" in default_text
    launch_text = (
        steps["7.1"]["instructions"] + "\n" + "\n".join(block["code"] for block in steps["7.1"]["code_blocks"])
    )
    assert "session resume walkthrough-demo" in launch_text
    assert "claude-haiku-4-5-20251001" in " ".join(steps["6.4"]["assertions"])
    assert all(not block["runnable"] for block in steps["6.1"]["code_blocks"])
    assert "OPENROUTER_API_KEY" not in CHECKLIST.read_text()
    assert "forge claude start --proxy" not in CHECKLIST.read_text()


def test_initial_doctor_accepts_current_or_requires_recovery_for_drift() -> None:
    steps = {step["id"]: step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"]}
    assertion = " ".join(steps["2.1"]["assertions"])

    assert "accept `current`" in assertion
    assert "require recovery advice for `missing` or `stale`" in assertion


def test_registry_summary_handles_the_current_keyed_installation_schema(
    tmp_path: Path,
) -> None:
    """Step 3.3 must summarize installation rows, not iterate their string keys."""
    forge_home = tmp_path / "forge-home"
    forge_home.mkdir()
    (forge_home / "installed.json").write_text(
        json.dumps(
            {
                "version": 3,
                "installations": {
                    "user": {"scope": "user", "unrelated": "do-not-print"},
                    "local:/sandbox": {"scope": "local", "root": "/sandbox"},
                },
            }
        ),
        encoding="utf-8",
    )
    step = next(step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"] if step["id"] == "3.3")
    command = next(block["code"] for block in step["code_blocks"] if block["runnable"])
    prefix = 'bash "$SCRIPTS/run-in-repo.sh" python3 -c \'\n'
    assert command.startswith(prefix) and command.endswith("\n'")
    script = command[len(prefix) : -2]

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "FORGE_HOME": str(forge_home)},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"rows": 2, "scopes": ["local", "user"]}
    assert "do-not-print" not in result.stdout


def test_continuation_delete_targets_claudes_native_transcript_store() -> None:
    """The sandbox install home must not redirect cleanup away from native transcripts."""
    step = next(step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"] if step["id"] == "11.4")
    command = "\n".join(block["code"] for block in step["code_blocks"] if block["runnable"])

    assert 'CLAUDE_HOME="$FORGE_WALKTHROUGH_CLAUDE_CONFIG_DIR"' in command
    assert "session delete walkthrough-continuation --yes --force" in command


def test_optional_codex_uses_initial_message_without_fake_readiness() -> None:
    text = CHECKLIST.read_text()
    codex_step = next(step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"] if step["id"] == "12.9")
    command = "\n".join(block["code"] for block in codex_step["code_blocks"] if block["runnable"])

    assert "--runtime codex" in command
    assert "--strategy structured" in command
    assert "--context-delivery initial-message" in command
    assert "--verify-enrollment" not in text
    assert "Forge walkthrough fixture" not in text


def test_optional_sidecar_uses_one_fixed_owned_proxy() -> None:
    data = PARSER.parse_checklist(str(CHECKLIST))
    steps = {step["id"]: step for step in data["_all_subs"]}
    preparation = "\n".join(block["code"] for block in steps["12.1"]["code_blocks"] if block["runnable"])
    launch = steps["12.4"]["instructions"] + "\n" + "\n".join(block["code"] for block in steps["12.4"]["code_blocks"])

    assert 'proxy create openrouter-anthropic --name "$proxy_id"' in preparation
    assert "proxy_id=walkthrough-sidecar-proxy" in preparation
    assert "--proxy walkthrough-sidecar-proxy" in launch
    assert subprocess.run(["bash", "-n", "-c", preparation], check=False).returncode == 0


def test_memory_is_orientation_not_a_schema_matrix() -> None:
    step = next(step for step in PARSER.parse_checklist(str(CHECKLIST))["_all_subs"] if step["id"] == "11.5")
    text = step["instructions"] + "\n" + "\n".join(block["code"] for block in step["code_blocks"])

    assert "forge memory --help" in text
    assert "forge session memory report --help" in text
    assert "frontmatter_facts" not in text
    assert "passport upgrade" not in text


def test_driver_declares_the_complete_argument_and_setup_only_contract() -> None:
    content = SKILL_FILE.read_text()
    frontmatter = content.split("---", 2)[1]
    for token in (
        "--setup-only",
        "--reset",
        "--report",
        "--from <id>",
        "--codex",
        "--codex-auth <path>",
        "--sidecar",
    ):
        assert token in frontmatter

    setup_only = content.split("If `--setup-only` was selected", 1)[1].split("For a normal fresh run", 1)[0]
    assert "Do not initialize checklist state" in setup_only
    assert "package-identity.json" in content
    assert "package_matches_answering_distribution: true" in content
    assert "answering_distribution_issue" in content
    assert "editable-install" in content
    assert "Never substitute checkout resources" in content
    assert 'bash "$SCRIPTS/run-in-repo.sh" true' in content
    assert "Do not call setup" in content
    assert "An unmarked existing target is never eligible for reset" in content


def test_driver_resume_refuses_stale_identity_without_initializing() -> None:
    content = SKILL_FILE.read_text()
    resume = content.split("### Resume with `--from`", 1)[1].split("## 4.", 1)[0]

    assert "Do not run setup" in resume
    assert "do not initialize with `--force`" in resume
    assert "RUN_OPTIONS" in resume
    assert "status: refused" in resume
    assert "/walkthrough --reset" in resume
    assert "byte-identical" in resume
    assert (
        'python3 "$SCRIPTS/package-identity.py" --skill-root "$CLAUDE_SKILL_DIR" '
        '> "$WT_RUN_DIR/package-identity.json"'
    ) in resume
    assert "before validation" in resume
    assert "both identity booleans" in resume
    assert (
        'bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/walkthrough-state.py" '
        '"$CHECKLIST" validate "$STATE_FILE" --from "$FROM_STEP"'
    ) in resume
    assert "Append `--report` to the validation command" in resume
    assert "persisted `RUN_OPTIONS`" in resume
    assert "recovery_kind: manual-state-inspection" in resume
    assert "recommend or invoke reset for this refusal" in resume
    assert "alternate_fresh_command" in resume


def test_driver_interruption_resumes_from_first_unrecorded_step() -> None:
    content = SKILL_FILE.read_text()
    interruption = content.split("## 6. Cleanup and Interruption", 1)[1].split("## 7.", 1)[0]

    assert "ordered checklist index and recorded state" in interruption
    assert "--from <first-unrecorded-step>" in interruption
    assert "active `--codex`, `--sidecar`, and `--report` selections" in interruption
    assert "--from 13" not in interruption


def test_driver_wraps_sandbox_state_mutation() -> None:
    content = SKILL_FILE.read_text()

    assert "initialize state with `--force` through `run-in-repo.sh`" in content
    assert (
        'bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/walkthrough-state.py" '
        '"$CHECKLIST" init "$STATE_FILE" --force'
    ) in content
    assert (
        'bash "$SCRIPTS/run-in-repo.sh" python3 "$SCRIPTS/walkthrough-state.py" '
        '"$CHECKLIST" record "$STATE_FILE" <id> <p,f,s,...>'
    ) in content
    assert "`SIDECAR_MAY_EXIST=false`" in content
    assert "Immediately before presenting selected step 12.4" in content
    assert 'WALKTHROUGH_SIDECAR_MAY_EXIST="$SIDECAR_MAY_EXIST"' in CHECKLIST.read_text()


def test_driver_keeps_options_reports_and_auth_separate() -> None:
    content = SKILL_FILE.read_text()

    assert "Adding `--report` does not change coverage identity" in content
    assert "Do not probe Docker or Codex in a default run" in content
    assert "Native stored Codex auth remains invisible" in CHECKLIST.read_text()
    assert "never auth facts" in content
    assert "option: codex" in content
    assert "option: sidecar" in content
