#!/usr/bin/env python3
"""Prepare one owned B3 round without copying login state or replacing enrollment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
from pathlib import Path


def prepare(root: Path) -> None:
    """Retain the installed package and create a clean, independently authenticated launcher."""
    root = root.absolute()
    if root.resolve() != root or root.exists():
        raise ValueError("Choose a new canonical round directory; preparation never resets existing state.")
    scripts = Path(__file__).resolve().parent
    checkout = scripts.parents[2]
    python = checkout / ".venv/bin/python"
    executable = shutil.which("codex")
    if executable is None:
        raise ValueError("Install Codex before preparing a round.")
    installed = Path(executable).resolve()
    # Homebrew keeps the complete native distribution one level above bin/.
    package = installed.parent.parent
    if installed.parent.name != "bin" or package.parent.name != "codex":
        raise ValueError(f"Inspect the package layout before retaining {installed}.")
    version = subprocess.check_output([str(installed), "--version"], text=True).strip()
    root.mkdir(mode=0o700, parents=True)
    (root / "B3_ROUND").write_text("independent-b3-round-v1\n")
    retained_package = root / "runtime" / package.name
    shutil.copytree(package, retained_package, symlinks=False)
    retained = retained_package / installed.relative_to(package)
    identity = {
        "installed_path": str(installed),
        "retained_path": str(retained),
        "version": version.removeprefix("codex-cli "),
        "sha256": hashlib.sha256(retained.read_bytes()).hexdigest(),
        "model": "gpt-6.1-sol",
        "effort": "low",
        "forge_revision": subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip(),
    }
    (root / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    for directory in ("home", "forge-home", "bin", "stub-bin", "captures", "project", "cache"):
        (root / directory).mkdir(mode=0o700)
    subprocess.run([str(python), str(scripts / "probe-home.py"), str(root / "codex-home")], check=True)
    (root / "control.json").write_text(json.dumps({"capture": str(root / "captures/preparation"), "reviewer": "fast"}))
    wrappers = {
        root
        / "bin/codex": [
            str(python),
            str(scripts / "probe-runtime.py"),
            "codex",
            "--identity",
            str(root / "identity.json"),
            "--",
        ],
        root / "stub-bin/claude": [str(python), str(scripts / "hooks/b3-reviewer.py")],
    }
    for path, command in wrappers.items():
        path.write_text("#!/bin/bash\nexec " + shlex.join(command) + ' "$@"\n')
        path.chmod(0o700)
    environment = {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex-home"),
        "FORGE_HOME": str(root / "forge-home"),
        "FORGE_DEV": str(checkout),
        "PATH": ":".join(
            [
                str(root / "stub-bin"),
                str(root / "bin"),
                str(checkout / ".venv/bin"),
                "/opt/homebrew/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        ),
        "LANG": "en_US.UTF-8",
        "TERM": "xterm-256color",
        "PYTHON_DOTENV_DISABLED": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "PROBE_ROUND_ROOT": str(root),
        "PROBE_LAUNCHER": str(root / "run"),
        "PROBE_CONTROL": str(root / "control.json"),
        "PROBE_RUNTIME_IDENTITY": str(root / "identity.json"),
        "PROBE_TURN_CEILING": "32",
        "XDG_CACHE_HOME": str(root / "cache"),
        "PYTHONPATH": str(scripts / "b3_instrumentation"),
    }
    launcher = root / "run"
    launcher.write_text(
        "#!/bin/bash\nexec /usr/bin/env -i "
        + shlex.join([f"{key}={value}" for key, value in environment.items()])
        + ' "$@"\n'
    )
    launcher.chmod(0o700)
    project = root / "project"
    for args in (["init", "-q"], ["config", "user.email", "b3@example.invalid"], ["config", "user.name", "B3 probe"]):
        subprocess.run(["git", *args], cwd=project, env=environment, check=True)
    (project / "README.md").write_text("# B3 delivery fixture\n")
    subprocess.run(["git", "add", "README.md"], cwd=project, env=environment, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, env=environment, check=True)
    (root / "host-config-hashes.json").write_text(
        json.dumps(
            {
                str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                for path in (Path.home() / ".codex/config.toml", Path.home() / ".codex/hooks.json")
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "root": str(root),
                "version": identity["version"],
                "sha256": identity["sha256"],
                "login": f"{launcher} codex login --device-auth",
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        prepare(args.root)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
