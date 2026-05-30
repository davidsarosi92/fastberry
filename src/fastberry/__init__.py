"""fastberry — performance helpers for strawberry-django.

A small, focused toolkit of drop-in performance utilities for
``strawberry-django`` GraphQL schemas running under sync Django.

Currently included:

- :func:`fast_path` / :class:`FastPathExtension` — skip ``django_resolver``
  overhead on hot types.

More helpers may be added over time; each lives in its own submodule and is
re-exported here.
"""

from importlib.metadata import PackageNotFoundError, version

from fastberry.fastpath import FastPathExtension, fast_path

__all__ = ["FastPathExtension", "fast_path", "__version__"]

try:
    __version__ = version("fastberry")
except PackageNotFoundError:  # package is not installed (e.g. running from source)
    __version__ = "0.0.0+unknown"