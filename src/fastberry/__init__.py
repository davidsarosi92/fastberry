"""fastberry — performance helpers for read-heavy Python web APIs.

A small, focused toolkit of drop-in performance utilities for stacks where
per-instance/per-field framework overhead dominates response time on large or
deeply-nested payloads.

Currently included:

- :func:`fast_path` / :class:`FastPathExtension` — skip ``django_resolver``
  overhead on hot ``strawberry-django`` types (GraphQL, sync Django). Needs the
  ``graphql`` extra.
- :mod:`fastberry.rest` — read-only nested REST serialization that assembles
  the tree from column-projected queries and encodes with ``orjson``. Works on
  **Django** and **SQLAlchemy** models (the backend is chosen from the model
  class), so the same ``FastRest`` runs under Django/DRF or FastAPI/SQLAlchemy.
  Declare a ``FastRest``, or decorate a model with ``@fast_rest``; on Django,
  ``fastberry.rest_renderers.FastJSONRenderer`` can serialize it automatically.
  Import these directly; they need the ``rest`` extra (or ``sqlalchemy`` extra
  for the SQLAlchemy backend).

Each helper lives in its own submodule. The GraphQL helpers are re-exported
here lazily (via module ``__getattr__``) so that importing the package — or
``fastberry.rest`` — does not pull in Django or strawberry when only the REST
helper is used.
"""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["FastPathExtension", "__version__", "fast_path"]

try:
    __version__ = version("fastberry")
except PackageNotFoundError:  # package is not installed (e.g. running from source)
    __version__ = "0.0.0+unknown"

_LAZY = {"FastPathExtension", "fast_path"}


def __getattr__(name):
    # Import the GraphQL helpers only on first access so REST/SQLAlchemy-only
    # users never trigger the strawberry + Django imports in fastberry.fastpath.
    if name in _LAZY:
        from fastberry import fastpath

        return getattr(fastpath, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
