# Reviewed dependency inputs

Forge's source build, CI and test images use reviewed dependency inputs. A pin controls when code changes; it does not
establish that upstream code is safe. Review security advisories and update pins through a tested PR.

## Python environments and builds

`uv.lock` owns the resolved runtime, development and build graphs and their artifact hashes. `make deps` and the
standard CI commands reject a stale lock. Python pre-commit hooks run from that environment rather than resolving
separate hook environments. Run `make deps` before invoking pre-commit directly.

The Pyright hook runs the locked wheel's bundled JavaScript through `scripts/run-pyright.py`. Node.js on the host
remains operator-owned: install a reviewed release on `PATH`. The hook refuses to run when Node.js is missing and does
not invoke the Python wrapper's Node/npm installation fallback.

Two generated exports serve installers that do not consume `uv.lock`:

- `requirements/runtime.txt` constrains every resolved runtime package by version, including platform markers.
- `requirements/build.txt` pins and hashes the build backend and its dependencies. `make build` requires these hashes
  when building the wheel and source distribution.

Project builds during `uv sync` use matching `tool.uv.build-constraint-dependencies` pins. uv 0.9.18 does not apply the
`UV_BUILD_CONSTRAINT` environment variable to project sync, so the checker also verifies this project-level list.

`scripts/check-dependency-pins.py` checks both exports against the lock and requires the build group to match
`build-system.requires`. For a backend update, change `build-system.requires`, `dependency-groups.build` and the
matching backend entry in `tool.uv.build-constraint-dependencies` together before running `uv lock`. Review the complete
build graph with `uv export --locked --only-group build --no-hashes --no-emit-project`, reconcile the project-level
transitive build pins with its exact requirements, and refresh the lock if those pins changed. The checker's `--write`
mode regenerates the export files; it does not update this project-level list.

The checker exports with its own Python interpreter. `make build` uses one installed Python 3.11--3.13 for both the
checker and the build, so offline validation does not require the development version in `.python-version`.

After updating and reviewing the dependency declarations and build pins:

```bash
uv lock
"$(uv python find --no-project --no-config '>=3.11,<3.14')" -S scripts/check-dependency-pins.py --write
make deps
make build
./scripts/test-wheel-runtime.sh
make pre-commit
```

The default wheel smoke installs the lock's hash-checked runtime artifacts into a fresh environment, then installs the
built wheel without resolving dependencies and checks the resulting graph. `--unconstrained` explicitly tests the
ordinary consumer resolver path; it can download newer compatible dependencies. Neither mode calls a model provider.

Source/global editable installation through `scripts/setup.sh --local` applies both constraint files. With uv 0.9.18,
tool-install constraints enforce versions but do not enforce artifact hashes. Ordinary `uv tool install multi-forge` and
`pipx install multi-forge` use wheel metadata ranges and do not inherit the repository lock. For a selected release
wheel, use the constraints from the same reviewed source revision:

```bash
uv tool install --constraints requirements/runtime.txt \
  --build-constraints requirements/build.txt /absolute/path/to/multi_forge-X.Y.Z-py3-none-any.whl
```

The release workflow records both constraint files separately from the distributions. Do not combine a wheel with a
different release's constraints. Existing environments are not retroactively updated by merging new pins.

## Hash-verified wheel installation

For a global launcher with verified dependency artifacts, use a dedicated environment and the hash export from the
wheel's reviewed source revision. Version constraints alone admit new files uploaded under an existing version;
`--require-hashes` admits only the recorded artifacts. `--no-build` refuses platforms without a matching reviewed wheel
instead of running a source build. See [PyPI's upload model](https://docs.pypi.org/api/upload/).

Start with a reviewed checkout and a wheel from that same revision. Obtain the wheel's expected SHA-256 from your
trusted build or verified release evidence, not by hashing an unverified download and treating that as approval. The
release workflow's `dependency-constraints` artifact also includes `runtime-hashed.txt`; the recipe below regenerates it
offline from the checkout's lock. It uses an existing Python 3.11--3.13 and uv, which remain operator-owned.

Set these paths and the expected wheel hash first:

```bash
FORGE_CHECKOUT=/absolute/path/to/reviewed-checkout
FORGE_WHEEL=/absolute/path/to/multi_forge-X.Y.Z-py3-none-any.whl
FORGE_WHEEL_SHA256='replace-with-trusted-64-character-sha256'
FORGE_INSTALL_DIR="$HOME/.local/share/forge/releases/X.Y.Z-reviewed"
FORGE_USER_BIN="$HOME/.local/bin"
```

Run this block in Bash. It requires a new installation directory and publishes the launcher only after verification:

<!-- verified-wheel-install:start -->

```bash
(
    set -euo pipefail
    test ! -e "$FORGE_INSTALL_DIR"
    test ! -L "$FORGE_INSTALL_DIR"
    printf '%s  %s\n' "$FORGE_WHEEL_SHA256" "$FORGE_WHEEL" | shasum --algorithm 256 --check -
    mkdir -p "$FORGE_INSTALL_DIR"
    uv venv --no-config --no-python-downloads --python '>=3.11,<3.14' "$FORGE_INSTALL_DIR/venv"
    uv export --python "$FORGE_INSTALL_DIR/venv/bin/python" \
        --project "$FORGE_CHECKOUT" --locked --offline --no-dev --no-emit-project \
        --output-file "$FORGE_INSTALL_DIR/runtime-hashed.txt" >/dev/null
    uv pip install --no-config --python "$FORGE_INSTALL_DIR/venv/bin/python" \
        --require-hashes --no-build -r "$FORGE_INSTALL_DIR/runtime-hashed.txt"
    uv pip install --no-config --python "$FORGE_INSTALL_DIR/venv/bin/python" --no-deps --no-build "$FORGE_WHEEL"
    uv pip check --no-config --python "$FORGE_INSTALL_DIR/venv/bin/python"
    mkdir -p "$FORGE_USER_BIN"
    test ! -e "$FORGE_USER_BIN/forge"
    test ! -L "$FORGE_USER_BIN/forge"
    ln -s "$FORGE_INSTALL_DIR/venv/bin/forge" "$FORGE_USER_BIN/forge"
)
```

<!-- verified-wheel-install:end -->

Add `FORGE_USER_BIN` to `PATH`, then run `forge extension doctor` and the
[Day 1 extension setup](../end-user/README.md#the-day-1-workflow). The persistent global symlink lets hooks find Forge
without activating the environment. This installation is managed by you, not `uv tool upgrade` or pipx. If the launcher
already exists, the final link step refuses to replace it. Inspect that launcher and choose which installation to keep
before changing it. For upgrades, prepare a fresh release directory and switch the launcher only after the new graph
passes verification. A failed preparation leaves the previous launcher untouched; inspect and remove only the new
directory before retrying. Do not move an installed environment: its console scripts contain absolute paths.

## Source selection

The source installer defaults to the moving `main` development branch. Pass `--version <tag-or-branch>` to select a
different ref. A missing requested ref fails; it never falls back to the default branch. Updating a source installation
requires a clean checkout and checks out the fetched commit without merging local commits. Revisions without the
required build constraints are refused. Updates validate an isolated copy of the candidate before changing the active
checkout, so a pin-check refusal preserves the installed source and environment. Once an admitted revision is checked
out, a dependency-sync failure can still require rerunning setup; this is not an atomic environment replacement.

For a reviewed installation, inspect a checkout at the chosen commit and run its local setup script. Fetching the
bootstrap script from `main` still trusts its current contents; a later `--version` argument cannot pin code that the
shell has already executed.

## CI and runtime images

GitHub Actions use full commit SHAs. uv bootstrap fixes both version and archive checksum; the release builder uses
hashed build constraints. Gitleaks uses a fixed source commit; its Go toolchain and module-fetch infrastructure remain
separate build inputs. GitHub-hosted runner images and the selected Python minor release still receive upstream updates.

The separate scheduled/manual consumer-compatibility workflow runs the wheel smoke with `--unconstrained`. It supplies
no provider or repository secrets, retains no checkout credentials, and does not run on pull requests or gate merges.
Failures report compatibility drift in the ordinary consumer graph; locked checks remain the release/merge gates.

Publishing runs PyPA's official container by digest. The upstream composite action selects a container tag even when its
source is pinned, so the workflow supplies the reviewed action's input defaults directly to its unchanged container
entrypoint. Trusted Publishing and PEP 740 attestations remain enabled. To update it, review the upstream action and
entrypoint together, verify the registry manifest and configuration digests, and update the image digest, input defaults
and provenance evidence together. Offline checks validate this configuration; the OIDC exchange and attestation upload
require an actual authorized release run.

Docker pins the Python base and uv image by digest. Default Claude/Codex versions match the pinned QA matrix;
integration scripts and direct Docker fixtures use the same selection. Explicit `CLAUDE_VERSION` / `CODEX_VERSION`
overrides, including `latest`, are compatibility choices. The QA `latest` track remains nonblocking. Invalid overrides
refuse when a Docker image is requested; importing test fixtures does not validate them. Forge build constraints apply
only to Forge's own build commands, not to projects run inside sidecar or QA images.

The optional native Claude path downloads a versioned binary and verifies a repository-held SHA-256 before installation.
Only reviewed versions/platforms are accepted. Updating those hashes requires checking the vendor's signed manifest; the
download must never execute a remote installer script. npm client installs pin the requested package version but do not
have a repository-held transitive npm lock. Debian packages still come from signed, updating repositories; the base
digest does not freeze subsequent `apt-get` operations. Host-installed runtimes and custom Docker bases remain
operator-owned.

To update runtime pins, review the QA matrix, Docker defaults, native checksums and image digests together. Validate
startup in a network-disabled container, then run relevant integration coverage. Retaining an old pin indefinitely is
not a substitute for adopting security fixes.
