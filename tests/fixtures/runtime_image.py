"""Check installed runtimes before an integration image can enter the test suite."""

from __future__ import annotations

import argparse
import subprocess
import sys
import uuid

_VERSION_PROBE = """set -eu
printf 'Claude Code: '
timeout -k 2s 15s claude --version
printf 'Codex CLI: '
timeout -k 2s 15s codex --version
"""


def check_runtime_image(image: str) -> str:
    """Probe both executables without networking, credentials, or model calls.

    A cached build-time version check is not proof that the final image can
    still run its binaries. Bound startup and remove only this probe's container.
    """
    name = "forge-runtime-preflight-" + uuid.uuid4().hex
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--entrypoint",
                "/bin/sh",
                image,
                "-c",
                _VERSION_PROBE,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        reason = f"exit {result.returncode}:\n{result.stdout}{result.stderr}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        reason = str(exc)
    finally:
        # The Docker client timing out does not stop its container. The normal
        # --rm path may already have removed it; either outcome is harmless.
        try:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass
    raise RuntimeError(
        f"Runtime startup failed in integration image {image} ({reason}).\n"
        "Rebuild its toolchain with 'docker build --no-cache', keeping the selected runtime "
        "versions. See docs/developer/testing_guidelines.md#docker-runtime-startup-failures."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    args = parser.parse_args()
    try:
        print(check_runtime_image(args.image))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
