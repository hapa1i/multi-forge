from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

import pytest
import yaml

from forge.install.skill_compiler import (
    CompiledSkillPackage,
    SkillRuntime,
    SkillSource,
    SkillSourceFormat,
    compile_skill_for_runtime,
    load_skill_sources,
)

SKILLS_ROOT = Path(__file__).parents[3] / "src" / "skills"
PORTABLE_SKILLS = ("challenge", "smoke-test", "review", "review-docs", "understand")
ALL_RUNTIMES = frozenset({SkillRuntime.CLAUDE_CODE, SkillRuntime.CODEX})
SMOKE_SCRIPT = SKILLS_ROOT / "smoke-test" / "scripts" / "smoke-test.sh"

EXPECTED_CLAUDE_EXTRAS: dict[str, dict[str, object]] = {
    "challenge": {
        "argument-hint": "[claim or objection]",
        "effort": "high",
        "allowed-tools": "Read, Grep, Glob, Bash, Agent",
    },
    "smoke-test": {
        "disable-model-invocation": True,
        "allowed-tools": "Bash",
    },
    "review": {
        "disable-model-invocation": False,
        "argument-hint": "[target: path or instruction] [--output path]",
        "allowed-tools": "Read, Grep, Glob, Bash, Agent",
    },
    "review-docs": {
        "disable-model-invocation": False,
        "argument-hint": "[target: path or instruction] [--output path]",
        "allowed-tools": "Read, Grep, Glob, Bash, Agent",
    },
    "understand": {
        "disable-model-invocation": False,
        "argument-hint": (
            "[target: path or question or instruction] [--output path] "
            "[--mode code|docs] [--depth quick|detailed|deep]"
        ),
        "allowed-tools": "Read, Grep, Glob, Bash, Agent",
    },
}

EXPECTED_PACKAGE_PATHS: dict[tuple[str, SkillRuntime], set[PurePosixPath]] = {
    ("challenge", SkillRuntime.CLAUDE_CODE): {PurePosixPath("SKILL.md")},
    ("challenge", SkillRuntime.CODEX): {PurePosixPath("SKILL.md")},
    ("smoke-test", SkillRuntime.CLAUDE_CODE): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("scripts/smoke-test.sh"),
    },
    ("smoke-test", SkillRuntime.CODEX): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("agents/openai.yaml"),
        PurePosixPath("scripts/smoke-test.sh"),
    },
    ("review", SkillRuntime.CLAUDE_CODE): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("resources/code-anthropic.md"),
        PurePosixPath("resources/code-gemini.md"),
        PurePosixPath("resources/code-openai.md"),
        PurePosixPath("resources/code.md"),
        PurePosixPath("references/claude-4.6.md"),
        PurePosixPath("references/claude-4.8.md"),
        PurePosixPath("references/gemini-3.1.md"),
        PurePosixPath("references/gpt-5.5.md"),
        PurePosixPath("references/skills-writing-guide.md"),
    },
    ("review", SkillRuntime.CODEX): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("agents/openai.yaml"),
        PurePosixPath("resources/code-anthropic.md"),
        PurePosixPath("resources/code-gemini.md"),
        PurePosixPath("resources/code-openai.md"),
        PurePosixPath("resources/code.md"),
    },
    ("review-docs", SkillRuntime.CLAUDE_CODE): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("resources/docs-anthropic.md"),
        PurePosixPath("resources/docs-gemini.md"),
        PurePosixPath("resources/docs-openai.md"),
        PurePosixPath("resources/docs.md"),
    },
    ("review-docs", SkillRuntime.CODEX): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("agents/openai.yaml"),
        PurePosixPath("resources/docs-anthropic.md"),
        PurePosixPath("resources/docs-gemini.md"),
        PurePosixPath("resources/docs-openai.md"),
        PurePosixPath("resources/docs.md"),
    },
    ("understand", SkillRuntime.CLAUDE_CODE): {
        PurePosixPath("SKILL.md"),
        *(
            PurePosixPath(f"resources/{mode}{suffix}.md")
            for mode in ("code", "docs")
            for suffix in ("", "-anthropic", "-gemini", "-openai")
        ),
    },
    ("understand", SkillRuntime.CODEX): {
        PurePosixPath("SKILL.md"),
        PurePosixPath("agents/openai.yaml"),
        *(
            PurePosixPath(f"resources/{mode}{suffix}.md")
            for mode in ("code", "docs")
            for suffix in ("", "-anthropic", "-gemini", "-openai")
        ),
    },
}

CODEX_FORBIDDEN_TEXT = (
    "$ARGUMENTS",
    "${CLAUDE_SKILL_DIR}",
    "$CLAUDE_SESSION_ID",
    "${CLAUDE_SESSION_ID}",
    "/forge:",
    "subagent_type",
    "Tool: Agent",
    "Explore agent",
    "AskUserQuestion",
    "Read tool",
    "PreToolUse",
    "Claude Code default",
    "Claude Code file reference syntax",
    "{{forge:",
)


@pytest.fixture(scope="module")
def portable_sources() -> dict[str, SkillSource]:
    sources = {source.manifest.name: source for source in load_skill_sources(SKILLS_ROOT)}
    return {name: sources[name] for name in PORTABLE_SKILLS}


@pytest.fixture(scope="module")
def compiled_packages(
    portable_sources: dict[str, SkillSource],
) -> dict[tuple[str, SkillRuntime], CompiledSkillPackage]:
    return {
        (name, runtime): compile_skill_for_runtime(source, runtime)
        for name, source in portable_sources.items()
        for runtime in SkillRuntime
    }


def _frontmatter(package: CompiledSkillPackage) -> dict[str, object]:
    text = package.file("SKILL.md").content.decode()
    return yaml.safe_load(text.split("---", 2)[1])


def test_all_portable_skills_use_neutral_mixed_source_contract(
    portable_sources: dict[str, SkillSource],
) -> None:
    assert set(portable_sources) == set(PORTABLE_SKILLS)
    for name, source in portable_sources.items():
        assert source.source_format == SkillSourceFormat.NEUTRAL, name
        assert source.manifest.runtime_eligibility == ALL_RUNTIMES, name
        assert not source.manifest.token_allowances, name
        assert (SKILLS_ROOT / name / "forge-skill.yaml").is_file()
        assert (SKILLS_ROOT / name / "content.md").is_file()
        assert not (SKILLS_ROOT / name / "SKILL.md").exists()


def test_compiled_packages_preserve_paths_and_modes(
    compiled_packages: dict[tuple[str, SkillRuntime], CompiledSkillPackage],
) -> None:
    for key, expected_paths in EXPECTED_PACKAGE_PATHS.items():
        package = compiled_packages[key]
        assert {package_file.path for package_file in package.files} == expected_paths, key
        for package_file in package.files:
            expected_mode = 0o755 if package_file.path == PurePosixPath("scripts/smoke-test.sh") else 0o644
            assert package_file.mode == expected_mode, (key, package_file.path)


def test_claude_frontmatter_preserves_existing_contract(
    portable_sources: dict[str, SkillSource],
    compiled_packages: dict[tuple[str, SkillRuntime], CompiledSkillPackage],
) -> None:
    for name, extras in EXPECTED_CLAUDE_EXTRAS.items():
        frontmatter = _frontmatter(compiled_packages[(name, SkillRuntime.CLAUDE_CODE)])
        assert frontmatter == {
            "name": f"forge:{name}",
            "description": portable_sources[name].manifest.description,
            **extras,
        }


def test_codex_frontmatter_policy_and_whole_tree_are_native(
    portable_sources: dict[str, SkillSource],
    compiled_packages: dict[tuple[str, SkillRuntime], CompiledSkillPackage],
) -> None:
    for name, source in portable_sources.items():
        package = compiled_packages[(name, SkillRuntime.CODEX)]
        assert _frontmatter(package) == {
            "name": name,
            "description": source.manifest.description,
        }
        for package_file in package.files:
            try:
                text = package_file.content.decode()
            except UnicodeDecodeError:
                continue
            assert all(token not in text for token in CODEX_FORBIDDEN_TEXT), (
                name,
                package_file.path,
            )

    challenge_paths = {package_file.path for package_file in compiled_packages[("challenge", SkillRuntime.CODEX)].files}
    assert PurePosixPath("agents/openai.yaml") not in challenge_paths
    expected_policy = {
        "smoke-test": False,
        "review": True,
        "review-docs": True,
        "understand": True,
    }
    for name, allow_implicit in expected_policy.items():
        package = compiled_packages[(name, SkillRuntime.CODEX)]
        openai = yaml.safe_load(package.file("agents/openai.yaml").content)
        assert openai["policy"] == {"allow_implicit_invocation": allow_implicit}


def test_review_references_are_claude_only_and_aliases_keep_content(
    compiled_packages: dict[tuple[str, SkillRuntime], CompiledSkillPackage],
) -> None:
    claude_review = compiled_packages[("review", SkillRuntime.CLAUDE_CODE)]
    codex_review = compiled_packages[("review", SkillRuntime.CODEX)]
    assert any(package_file.path.parts[0] == "references" for package_file in claude_review.files)
    assert not any(package_file.path.parts[0] == "references" for package_file in codex_review.files)
    assert claude_review.file("resources/code.md").content == claude_review.file("resources/code-anthropic.md").content

    for name, default_path, anthropic_path in (
        ("review-docs", "resources/docs.md", "resources/docs-anthropic.md"),
        ("understand", "resources/code.md", "resources/code-anthropic.md"),
        ("understand", "resources/docs.md", "resources/docs-anthropic.md"),
    ):
        package = compiled_packages[(name, SkillRuntime.CLAUDE_CODE)]
        assert package.file(default_path).content == package.file(anthropic_path).content


def _fake_forge(bin_dir: Path) -> Path:
    forge = bin_dir / "forge"
    forge.write_text("#!/bin/sh\necho 'forge test-version'\n", encoding="utf-8")
    forge.chmod(0o755)
    return forge


def _run_smoke_script(
    tmp_path: Path,
    *,
    runtime: str | None,
    tracking_exists: bool = True,
    relative_invocation: bool = False,
    trace: bool = False,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    forge_home = tmp_path / "forge-state"
    codex_home = tmp_path / "codex-home"
    runtime_root = tmp_path / "installed-runtime"
    skills_dir = runtime_root / "skills"
    installed_script = skills_dir / "smoke-test" / "scripts" / "smoke-test.sh"
    unrelated_cwd = tmp_path / "unrelated-cwd"
    bin_dir = tmp_path / "bin"
    for directory in (
        home,
        forge_home,
        codex_home,
        unrelated_cwd,
        bin_dir,
        installed_script.parent,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    installed_script.symlink_to(SMOKE_SCRIPT)
    _fake_forge(bin_dir)

    if runtime in {None, "claude_code"}:
        (runtime_root / "settings.json").write_text("{}\n", encoding="utf-8")
        (runtime_root / "settings.local.json").write_text("{}\n", encoding="utf-8")
        (runtime_root / "commands").mkdir()
        (runtime_root / "agents").mkdir()
    else:
        (codex_home / "config.toml").write_text("# test\n", encoding="utf-8")
    if tracking_exists:
        (forge_home / "installed.json").write_text('{"version": 1}\n', encoding="utf-8")

    env = {
        **os.environ,
        "HOME": str(home),
        "FORGE_HOME": str(forge_home),
        "CODEX_HOME": str(codex_home),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
    }
    if runtime is not None:
        env["FORGE_SKILL_RUNTIME"] = runtime
    else:
        env.pop("FORGE_SKILL_RUNTIME", None)
    command = ["bash"]
    if trace:
        command.append("-x")
    command.append("./scripts/smoke-test.sh" if relative_invocation else str(installed_script))
    return subprocess.run(
        command,
        cwd=installed_script.parent.parent if relative_invocation else unrelated_cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("runtime", "expected_runtime", "runtime_probe"),
    [
        (None, "claude_code", "settings.json intact"),
        ("claude_code", "claude_code", "settings.json intact"),
        ("codex", "codex", "Codex config intact"),
    ],
)
def test_smoke_script_is_runtime_aware_from_symlinked_install_path(
    tmp_path: Path,
    runtime: str | None,
    expected_runtime: str,
    runtime_probe: str,
) -> None:
    result = _run_smoke_script(tmp_path, runtime=runtime)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Forge Smoke Test ({expected_runtime})" in result.stdout
    assert runtime_probe in result.stdout
    assert "Forge state intact" in result.stdout


def test_smoke_script_recovery_names_selected_runtime(tmp_path: Path) -> None:
    result = _run_smoke_script(tmp_path, runtime="codex", tracking_exists=False)

    assert result.returncode == 1
    assert "Some checks failed for codex" in result.stdout
    assert "--runtime codex" in result.stdout


def test_smoke_script_resolves_relative_dot_invocation_from_package_root(tmp_path: Path) -> None:
    result = _run_smoke_script(
        tmp_path,
        runtime="claude_code",
        relative_invocation=True,
        trace=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    expected_settings = tmp_path / "installed-runtime" / "settings.json"
    assert f"snapshot_mtime {expected_settings}" in result.stderr


def test_smoke_skill_documents_unsupported_runtime_exit_code() -> None:
    content = (SKILLS_ROOT / "smoke-test" / "content.md").read_text()

    assert "0 = all pass, 1 = failed checks, 2 = unsupported runtime selection" in content


def test_smoke_script_rejects_unknown_runtime(tmp_path: Path) -> None:
    result = _run_smoke_script(tmp_path, runtime="unsupported")

    assert result.returncode == 2
    assert "unsupported FORGE_SKILL_RUNTIME" in result.stderr
