"""Multi-Forge - Multi-runtime agent toolkit."""

import logging
from importlib.metadata import PackageNotFoundError, version

# Forge is both a library and a CLI. Keep library warnings from falling through
# Python's lastResort stderr handler when CLI file logging is disabled.
logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    # Single source of truth is pyproject.toml; reading installed metadata keeps
    # ``__version__`` from drifting (a hardcoded literal once shipped 0.5.0 while
    # the package was 0.6.0, poisoning forge_version in manifests and work items).
    __version__ = version("multi-forge")
except PackageNotFoundError:  # source tree without an installed dist
    __version__ = "0.0.0+unknown"
