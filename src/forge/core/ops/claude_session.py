"""Claude session command-core helpers.

This module is the first slice of moving Claude session launch/resume behavior
out of the CLI layer. Helpers here must stay UI-agnostic and let callers render
errors.
"""

from __future__ import annotations

from pathlib import Path


def resolve_and_validate_system_prompt(
    *,
    system_prompt: str | None,
    system_prompt_file: str | None,
    cwd: Path,
) -> Path | None:
    """Resolve launch-only system-prompt input to a prompt file path."""
    if system_prompt_file:
        prompt_path = Path(system_prompt_file)
        if not prompt_path.is_absolute():
            prompt_path = cwd / prompt_path
        return prompt_path.resolve()

    if system_prompt:
        claude_dir = cwd / ".claude"
        claude_dir.mkdir(exist_ok=True)
        prompt_file_path = claude_dir / "forge.system-prompt.generated.md"
        prompt_file_path.write_text(system_prompt)
        return prompt_file_path

    return None
