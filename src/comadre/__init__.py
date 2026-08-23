"""Comadre — Custom Multi-voice Audio Driver."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("comadre")
except PackageNotFoundError:  # running from a raw source tree without install
    __version__ = "0.0.0.dev0"
