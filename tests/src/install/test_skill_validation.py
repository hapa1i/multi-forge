from __future__ import annotations

from pathlib import PurePosixPath

import pytest
import yaml

from forge.install.skill_compiler import (
    CompiledSkillFile,
    CompiledSkillPackage,
    SkillRuntime,
    TokenAllowance,
)
from forge.install.skill_validation import validate_compiled_skill


def _skill_document(name: str = "demo-skill", **extra: object) -> bytes:
    frontmatter: dict[str, object] = {
        "name": name,
        "description": "Demonstrate validation. Use when testing skill packages.",
        **extra,
    }
    return f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n# Demo\n".encode()


def _package(
    *files: CompiledSkillFile,
    runtime: SkillRuntime = SkillRuntime.CODEX,
    name: str = "demo-skill",
    allowances: tuple[TokenAllowance, ...] = (),
) -> CompiledSkillPackage:
    package_files = files or (CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(name), 0o644),)
    return CompiledSkillPackage(
        runtime=runtime,
        name=name,
        files=package_files,
        token_allowances=allowances,
    )


def test_whole_tree_token_scan_reports_nested_path_runtime_rule_and_recovery() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(
            PurePosixPath("references/nested.md"),
            b'Run bash "${CLAUDE_SKILL_DIR}/scripts/check.sh".\n',
            0o644,
        ),
    )

    diagnostics = validate_compiled_skill(package)

    diagnostic = next(item for item in diagnostics if item.rule == "token.claude-skill-dir")
    assert diagnostic.runtime == SkillRuntime.CODEX
    assert diagnostic.skill == "demo-skill"
    assert diagnostic.path == PurePosixPath("references/nested.md")
    assert "packaged_script" in diagnostic.recovery


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("$HOME/.claude/settings.json\n", "token.claude-home-path"),
        ("Tool: Agent\n", "token.claude-agent-tool"),
        ("Call `Read` with one argument.\n", "token.claude-read-tool"),
        ("A PreToolUse hook strips parameters.\n", "token.claude-hook-contract"),
        ("Strip the Claude Code file reference syntax.\n", "token.claude-file-reference"),
        ("Use Claude Code default when the model is missing.\n", "token.claude-default-model"),
    ],
)
def test_whole_tree_scan_covers_operational_claude_couplings(text: str, rule: str) -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("nested/content.txt"), text.encode(), 0o644),
    )

    diagnostics = validate_compiled_skill(package)

    diagnostic = next(item for item in diagnostics if item.rule == rule)
    assert diagnostic.path == PurePosixPath("nested/content.txt")
    assert diagnostic.recovery


def test_exact_token_allowance_is_machine_readable_and_path_scoped() -> None:
    path = PurePosixPath("references/compatibility.md")
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(path, b"Literal compatibility example: $ARGUMENTS\n", 0o644),
        allowances=(TokenAllowance(SkillRuntime.CODEX, path, "token.claude-arguments"),),
    )

    diagnostics = validate_compiled_skill(package)

    assert not any(item.rule == "token.claude-arguments" for item in diagnostics)


def test_codex_frontmatter_uses_closed_agent_skills_contract() -> None:
    document = _skill_document(
        "Bad--Name",
        metadata={"version": 1},
        **{"allowed-tools": "Read, Bash", "argument-hint": "[target]"},
    )
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644),
        name="bad--name",
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "codex.frontmatter-fields",
        "codex.name-directory",
        "codex.name-format",
        "codex.metadata",
        "codex.allowed-tools",
    } <= rules


def test_codex_field_limits_and_types_are_validated() -> None:
    document = _skill_document(
        description="x" * 1025,
        compatibility="",
        license=3,
    )
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {"codex.description", "codex.compatibility", "codex.license"} <= rules


def test_non_string_unknown_frontmatter_key_is_reported_without_validator_crash() -> None:
    frontmatter: dict[object, object] = {
        "name": "demo-skill",
        "description": "Demo validation. Use for tests.",
        1: "invalid",
        "unknown": True,
    }
    document = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n# Demo\n".encode()
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert "codex.frontmatter-fields" in rules


def test_references_must_resolve_without_escaping_package() -> None:
    document = _skill_document() + b"[escape](../secret.md)\n[missing](references/missing.md)\n"
    package = _package(CompiledSkillFile(PurePosixPath("SKILL.md"), document, 0o644))

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert "reference.escape" in rules
    assert "reference.missing" in rules


def test_nested_relative_reference_resolves_from_containing_file() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("references/detail.md"), b"# Detail\n", 0o644),
        CompiledSkillFile(PurePosixPath("references/index.md"), b"[detail](detail.md)\n", 0o644),
    )

    diagnostics = validate_compiled_skill(package)

    assert not any(item.rule.startswith("reference.") for item in diagnostics)


def test_openai_yaml_policy_and_asset_paths_are_validated_separately() -> None:
    openai = yaml.safe_dump(
        {
            "interface": {"icon_small": "../outside.svg", "unknown": "value"},
            "policy": {"allow_implicit_invocation": "false", "other": True},
            "extra": {},
        }
    ).encode()
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("agents/openai.yaml"), openai, 0o644),
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "openai.fields",
        "openai.interface-fields",
        "openai.asset-reference",
        "openai.policy",
    } <= rules


def test_package_structure_requires_sorted_unique_safe_paths_and_portable_modes() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("z.txt"), b"z", 0o644),
        CompiledSkillFile(PurePosixPath("../escape.txt"), b"x", 0o1000),
        CompiledSkillFile(PurePosixPath("z.txt"), b"duplicate", 0o644),
    )

    rules = {item.rule for item in validate_compiled_skill(package)}

    assert {
        "package.order",
        "package.path",
        "package.duplicate-path",
        "package.mode",
        "package.skill-document",
    } <= rules


def test_binary_assets_are_retained_without_text_token_false_positives() -> None:
    package = _package(
        CompiledSkillFile(PurePosixPath("SKILL.md"), _skill_document(), 0o644),
        CompiledSkillFile(PurePosixPath("assets/image.bin"), b"\xff$ARGUMENTS\x00", 0o644),
    )

    diagnostics = validate_compiled_skill(package)

    assert not any(item.path == PurePosixPath("assets/image.bin") for item in diagnostics)
