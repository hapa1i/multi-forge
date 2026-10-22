"""Install a reviewed Claude binary without executing a remote bootstrap script."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

# https://downloads.claude.ai/claude-code-releases/2.1.245/manifest.json
# Verified against its detached signature and Anthropic's documented key fingerprint:
# 31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE (https://code.claude.com/docs/en/setup).
CHECKSUMS = {
    "2.1.245": {
        "amd64": (
            "linux-x64",
            "16ad2b94deaf7b29abed966d981c9991a47af0420f5be8ed4a3f83bea9f678bc",
        ),
        "arm64": (
            "linux-arm64",
            "d0da299303d710a7cc5cdece9629958f5128ce1a727e15463c651ed5cf385c7f",
        ),
    }
}


def install(version: str, architecture: str, destination: Path) -> None:
    """Download a pinned binary and publish it only after its checksum matches."""
    pin = CHECKSUMS.get(version, {}).get(architecture)
    if pin is None:
        raise ValueError(
            f"No reviewed native Claude checksum for version {version!r} on {architecture!r}. "
            "Add a verified checksum or use INSTALL_METHOD=npm with an explicit CLAUDE_VERSION."
        )
    platform, expected = pin
    url = f"https://downloads.claude.ai/claude-code-releases/{version}/{platform}/claude"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=120) as response:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"Claude {version} {platform} checksum mismatch; refusing to install the download.")
        temporary.chmod(0o755)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> int:
    """Install the version and platform selected by the Docker build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("architecture")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        install(args.version, args.architecture, args.destination)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
