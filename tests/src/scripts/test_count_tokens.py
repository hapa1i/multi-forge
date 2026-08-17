"""Direct CLI contract tests for scripts/count-tokens.py."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "count-tokens.py"
_DEFAULT_MODEL = "claude-opus-5"
_MODEL = "gpt-4o"


@pytest.fixture
def run_count_tokens(tmp_path: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    input_path = tmp_path / "input.txt"
    input_path.write_text("one two three\n", encoding="utf-8")
    (tmp_path / "tiktoken.py").write_text(
        """\
class _Encoding:
    def encode(self, text: str) -> list[str]:
        return text.split()


def encoding_for_model(model: str) -> _Encoding:
    return _Encoding()


def get_encoding(name: str) -> _Encoding:
    return _Encoding()
""",
        encoding="utf-8",
    )

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        # Substitute only the encoder so CLI tests stay deterministic and offline.
        python_paths = [str(tmp_path)]
        if existing_python_path := env.get("PYTHONPATH"):
            python_paths.append(existing_python_path)
        env["PYTHONPATH"] = os.pathsep.join(python_paths)
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args, str(input_path)],
            cwd=_REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    return run


def test_default_model_is_current_opus(
    run_count_tokens: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run_count_tokens()

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == ("3 tokens | 14 chars | 2 lines\n" f"  method: tiktoken local ({_DEFAULT_MODEL})\n")


def test_omitted_mode_uses_local_counting(
    run_count_tokens: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run_count_tokens("--model", _MODEL)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == ("3 tokens | 14 chars | 2 lines\n" "  method: tiktoken local (gpt-4o)\n")


def test_explicit_local_matches_omitted_mode(
    run_count_tokens: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    omitted = run_count_tokens("--model", _MODEL)
    explicit = run_count_tokens("--local", "--model", _MODEL)

    assert explicit.returncode == 0
    assert explicit.stderr == ""
    assert explicit.stdout == omitted.stdout


def test_provider_mode_selects_provider_path_without_network(
    run_count_tokens: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run_count_tokens("--provider-api", "--model", _MODEL)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == ("3 tokens | 14 chars | 2 lines\n" "  method: tiktoken (gpt-4o)\n")


def test_conflicting_modes_remain_an_argparse_error(
    run_count_tokens: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run_count_tokens("--local", "--provider-api")

    assert result.returncode == 2
    assert result.stdout == ""
    assert "--local" in result.stderr
    assert "--provider-api" in result.stderr
    assert "not allowed with argument" in result.stderr


def test_help_retains_both_mode_choices(
    run_count_tokens: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = run_count_tokens("--help")

    assert result.returncode == 0
    assert result.stderr == ""
    assert "--local" in result.stdout
    assert "Use local tiktoken counting" in result.stdout
    assert "no provider API" in result.stdout
    assert "--provider-api" in result.stdout
    assert "Try provider count_tokens APIs before falling back to" in result.stdout
    assert f"default: {_DEFAULT_MODEL}" in result.stdout
