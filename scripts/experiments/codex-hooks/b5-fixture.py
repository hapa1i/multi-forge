#!/usr/bin/env python3
"""Prepare an independent B5 fixture and retain the installed Codex distribution."""

from __future__ import annotations

import argparse
import hashlib
import json
import runpy
import shlex
import shutil
import subprocess
from pathlib import Path


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(root: Path) -> None:
    """Create a new round without reading, copying, or replacing existing login state."""
    root = root.absolute()
    if root.resolve() != root or root.exists():
        raise ValueError("Choose a new canonical round directory; existing rounds are never reset.")
    scripts = Path(__file__).resolve().parent
    checkout = scripts.parents[2]
    python = checkout / ".venv/bin/python"
    launcher = shutil.which("codex")
    if launcher is None:
        raise ValueError("Install Codex before preparing a round.")
    installed = Path(launcher).resolve()
    package = installed.parent.parent
    if installed.parent.name != "bin" or package.parent.name != "codex":
        raise ValueError(f"Inspect the package layout before retaining {installed}.")
    root.mkdir(mode=0o700, parents=True)
    (root / "B5_ROUND").write_text("independent-b5-round-v1\n")
    retained_package = root / "runtime" / package.name
    shutil.copytree(package, retained_package, symlinks=False)
    retained = retained_package / installed.relative_to(package)
    for directory in (
        "home",
        "forge-home",
        "bin",
        "captures",
        "source",
        "action",
        "outside",
        "cache",
    ):
        (root / directory).mkdir(mode=0o700)
    runpy.run_path(str(scripts / "probe-home.py"))["prepare_home"](root / "codex-home")
    environment = {
        "HOME": str(root / "home"),
        "CODEX_HOME": str(root / "codex-home"),
        "FORGE_HOME": str(root / "forge-home"),
        "FORGE_DEV": str(checkout),
        "PATH": ":".join(
            [
                str(root / "bin"),
                str(python.parent),
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
        "XDG_CACHE_HOME": str(root / "cache"),
        "PROBE_ROUND_ROOT": str(root),
        "PROBE_LAUNCHER": str(root / "run"),
        "PROBE_RUNTIME_IDENTITY": str(root / "identity.json"),
    }
    identity = {
        "installed_path": str(installed),
        "selected_launcher": launcher,
        "retained_package": str(retained_package),
        "retained_path": str(retained),
        "version": subprocess.check_output([str(retained), "--version"], env=environment, text=True).strip(),
        "sha256": file_hash(retained),
        "forge_revision": subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip(),
    }
    (root / "identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    (root / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    (root / "authorization.json").write_text(
        json.dumps(
            {
                "subscription_extra_usage_off_confirmed": False,
                "api_starts_authorized": 0,
            },
            indent=2,
        )
        + "\n"
    )
    for path, command in (
        (root / "bin/codex", [str(python), str(scripts / "b5-runtime.py")]),
        (
            root / "run",
            [
                "/usr/bin/env",
                "-i",
                *[f"{key}={value}" for key, value in environment.items()],
            ],
        ),
    ):
        path.write_text("#!/bin/bash\nexec " + shlex.join(command) + ' "$@"\n')
        path.chmod(0o700)
    for name in ("source", "action"):
        project = root / name
        for args in (
            ["init", "-q"],
            ["config", "user.email", "b5@example.invalid"],
            ["config", "user.name", "B5 probe"],
        ):
            subprocess.run(["git", *args], cwd=project, env=environment, check=True)
        (project / "README.md").write_text(f"# B5 {name} checkout\n")
        subprocess.run(["git", "add", "README.md"], cwd=project, env=environment, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "fixture"],
            cwd=project,
            env=environment,
            check=True,
        )
    (root / "host-config-hashes.json").write_text(
        json.dumps(
            {
                str(path): file_hash(path) if path.is_file() else None
                for path in (
                    Path.home() / ".codex/config.toml",
                    Path.home() / ".codex/hooks.json",
                )
            },
            indent=2,
        )
        + "\n"
    )
    print(
        json.dumps(
            {
                "root": str(root),
                "identity": identity,
                "login": f"{root / 'run'} codex login --device-auth",
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
