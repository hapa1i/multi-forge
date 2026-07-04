"""Multi-Forge - Multi-runtime agent toolkit."""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth is pyproject.toml; reading installed metadata keeps
    # ``__version__`` from drifting (a hardcoded literal once shipped 0.5.0 while
    # the package was 0.6.0, poisoning forge_version in manifests and work items).
    __version__ = version("multi-forge")
except PackageNotFoundError:  # source tree without an installed dist
    __version__ = "0.0.0+unknown"
