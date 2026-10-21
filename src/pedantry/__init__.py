"""Pedantry: shared lint and format configuration, delivered as a package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pedantry")
except PackageNotFoundError:  # pragma: no cover - only when run from a bare checkout
    __version__ = "0.0.0"
