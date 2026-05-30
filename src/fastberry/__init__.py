"""fastberry — performance helpers for Django GraphQL and REST.

A small, focused toolkit of drop-in performance utilities for Django apps
running under sync Django, where per-instance/per-field framework overhead
dominates response time on large or deeply-nested payloads.

Currently included:

- :func:`fast_path` / :class:`FastPathExtension` — skip ``django_resolver``
  overhead on hot ``strawberry-django`` types (GraphQL).
- :mod:`fastberry.rest` — read-only nested REST serialization that assembles
  the tree from column-projected queries and encodes with ``orjson``. Works on
  **Django** and **SQLAlchemy** models (the backend is chosen from the model
  class), so the same ``FastRest`` runs under Django/DRF or FastAPI/SQLAlchemy.
  Declare a ``FastRest``, or decorate a model with ``@fast_rest``; on Django,
  ``fastberry.rest_renderers.FastJSONRenderer`` can serialize it automatically.
  Import these directly; they need the ``rest`` extra (or ``sqlalchemy`` extra
  for the SQLAlchemy backend).

Each helper lives in its own submodule. The GraphQL helpers are re-exported
here; ``fastberry.rest`` is imported explicitly to keep its ``orjson``
dependency optional.
"""

from importlib.metadata import PackageNotFoundError, version

from fastberry.fastpath import FastPathExtension, fast_path

__all__ = ["FastPathExtension", "fast_path", "__version__"]

try:
    __version__ = version("fastberry")
except PackageNotFoundError:  # package is not installed (e.g. running from source)
    __version__ = "0.0.0+unknown"