"""ms: personal multi-repo + dual-remote sync manager."""

# Single source of truth: the version lives in pyproject.toml and is read back
# from the installed package metadata. (Previously hardcoded here, which drifted
# from pyproject the moment one was bumped without the other.)
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ms")
except PackageNotFoundError:  # running from source, not installed
    __version__ = "0.0.0+unknown"
