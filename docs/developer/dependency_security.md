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

After updating and reviewing the dependency declarations and build pins:

```bash
uv lock
python3 scripts/check-dependency-pins.py --write
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

## Source selection

The source installer defaults to the moving `main` development branch. Pass `--version <tag-or-branch>` to select a
different ref. A missing requested ref fails; it never falls back to the default branch. Updating a source installation
requires a clean checkout and checks out the fetched commit without merging local commits. Revisions without the
required build constraints are refused.

For a reviewed installation, inspect a checkout at the chosen commit and run its local setup script. Fetching the
bootstrap script from `main` still trusts its current contents; a later `--version` argument cannot pin code that the
shell has already executed.

## CI and runtime images

GitHub Actions use full commit SHAs. uv bootstrap fixes both version and archive checksum; the release builder uses
hashed build constraints. Gitleaks uses a fixed source commit; its Go toolchain and module-fetch infrastructure remain
separate build inputs. GitHub-hosted runner images and the selected Python minor release still receive upstream updates.

Publishing runs PyPA's official container by digest. The upstream composite action selects a container tag even when its
source is pinned, so the workflow supplies the reviewed action's input defaults directly to its unchanged container
entrypoint. Trusted Publishing and PEP 740 attestations remain enabled. To update it, review the upstream action and
entrypoint together, verify the registry manifest and configuration digests, and update the image digest, input defaults
and provenance evidence together. Offline checks validate this configuration; the OIDC exchange and attestation upload
require an actual authorized release run.

Docker pins the Python base and uv image by digest. Default Claude/Codex versions match the pinned QA matrix;
integration scripts and direct Docker fixtures use the same selection. Explicit `CLAUDE_VERSION` / `CODEX_VERSION`
overrides, including `latest`, are compatibility choices. The QA `latest` track remains nonblocking.

The optional native Claude path downloads a versioned binary and verifies a repository-held SHA-256 before installation.
Only reviewed versions/platforms are accepted. Updating those hashes requires checking the vendor's signed manifest; the
download must never execute a remote installer script. npm client installs pin the requested package version but do not
have a repository-held transitive npm lock. Debian packages still come from signed, updating repositories; the base
digest does not freeze subsequent `apt-get` operations. Host-installed runtimes and custom Docker bases remain
operator-owned.

To update runtime pins, review the QA matrix, Docker defaults, native checksums and image digests together. Validate
startup in a network-disabled container, then run relevant integration coverage. Retaining an old pin indefinitely is
not a substitute for adopting security fixes.
