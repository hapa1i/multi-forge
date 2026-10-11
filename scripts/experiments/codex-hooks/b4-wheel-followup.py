"""Verify follow-up wheel bytes and Codex hook lifecycle with a no-inference CLI stub."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import forge


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    args = parser.parse_args()
    package = Path(forge.__file__).resolve().parent
    assert not package.is_relative_to(args.checkout.resolve()), "Use a clean wheel interpreter outside the checkout"
    rows = []
    for source in sorted((args.checkout / "src/forge").rglob("*.py")):
        relative = source.relative_to(args.checkout / "src/forge")
        assert sha(source) == sha(package / relative), relative
        rows.append([str(relative), sha(source)])
    qa = package / "_extensions/skills/qa/resources/checklist/6-hook.md"
    assert sha(qa) == sha(args.checkout / "src/skills/qa/resources/checklist/6-hook.md")
    assert "all five Forge Codex hooks" in qa.read_text()
    expected = {"SessionStart", "PreToolUse", "UserPromptSubmit", "PostToolUse", "Stop"}
    commands = []
    with tempfile.TemporaryDirectory(prefix="forge-b4-wheel-followup-") as temporary:
        root = Path(temporary)
        home, bin_dir = root / "home", root / "bin"
        home.mkdir()
        bin_dir.mkdir()
        codex_home = home / ".codex"
        codex_home.mkdir()
        config = codex_home / "config.toml"
        config.write_text('model = "preserve-this-preference"\n')
        binary = bin_dir / "codex"
        binary.write_text("#!/bin/sh\nprintf 'codex-cli 0.162.1\\n'\n")
        binary.chmod(0o755)
        env = {
            "HOME": str(home),
            "PATH": str(bin_dir) + os.pathsep + os.defpath,
            "FORGE_HOME": str(home / ".forge"),
            "CODEX_HOME": str(codex_home),
            "PYTHON_DOTENV_DISABLED": "1",
        }
        launcher = Path(sys.executable).parent / "forge"
        for argv in (
            [
                "extension",
                "enable",
                "--scope",
                "user",
                "--runtime",
                "codex",
                "--profile",
                "minimal",
                "--with",
                "hooks",
                "--without",
                "commands",
                "--force",
            ],
            ["extension", "doctor", "--json"],
            ["extension", "sync", "--scope", "user"],
            ["codex", "status", "--scope", "user", "--json"],
            ["policy", "supervisor", "reset-review", "--help"],
            ["extension", "disable", "--scope", "user", "--runtime", "codex", "--yes"],
        ):
            result = subprocess.run(
                [str(launcher), *argv], cwd=root, env=env, capture_output=True, text=True, timeout=30
            )
            assert result.returncode == 0, (argv, result.stdout, result.stderr)
            commands.append({"argv": argv, "exit_code": result.returncode})
            parsed = tomllib.loads(config.read_text())
            assert parsed["model"] == "preserve-this-preference"
            if argv[1] in {"enable", "sync"}:
                assert set(parsed["hooks"]) == expected
                assert all(
                    len(parsed["hooks"][event]) == 1 and parsed["hooks"][event][0]["hooks"][0]["timeout"] == 60
                    for event in expected
                )
        assert not tomllib.loads(config.read_text()).get("hooks")
    print(
        json.dumps(
            {
                "inference": False,
                "runtime": "stub used for binary discovery only",
                "forge_dev": False,
                "wheel_sha256": sha(args.wheel),
                "python_files_matched": len(rows),
                "source_inventory_sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
                "qa_checklist_sha256": sha(qa),
                "commands": commands,
                "exact_hook_set": sorted(expected),
                "unrelated_config_preserved": True,
                "fixture_removed": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
