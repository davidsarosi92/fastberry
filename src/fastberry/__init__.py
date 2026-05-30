"""fastberry — performance helpers for strawberry-django.

A small, focused toolkit of drop-in performance utilities for
``strawberry-django`` GraphQL schemas running under sync Django.

Currently included:

- :func:`fast_path` / :class:`FastPathExtension` — skip ``django_resolver``
  overhead on hot types.

More helpers may be added over time; each lives in its own submodule and is
re-exported here.
"""

from fastberry.fastpath import FastPathExtension, fast_path

__all__ = ["FastPathExtension", "fast_path"]

__version__ = "0.1.0"