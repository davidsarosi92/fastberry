"""Combine ``strawberry_django`` with ``fast_path`` in one step.

Two ways to use it.

**Wrap an existing type** — instead of stacking two decorators::

    @fast_path
    @strawberry_django.type(Stock, disable_optimization=True)
    class StockType: ...

use one that does both (every argument is forwarded verbatim)::

    from fastberry import strawberry_django as fast_strawberry_django

    @fast_strawberry_django.type(Stock, disable_optimization=True)
    class StockType: ...

**Generate the type from the model** — when you don't want to hand-write the
GraphQL type at all, decorate the *model* with :func:`fast_schema`. It builds a
``strawberry_django`` type for the model (all fields, or a subset), applies
``fast_path``, and stashes the result on the model::

    from fastberry.strawberry_django import fast_schema

    @fast_schema
    class Stock(models.Model): ...

    StockType = Stock.__fast_type__          # the generated, fast-pathed type

Needs the ``strawberry-graphql-django`` package (the ``graphql`` extra:
``pip install 'fastberry[graphql]'``).
"""

import builtins
from collections.abc import Callable, Sequence
from functools import wraps
from typing import Any

from fastberry.fastpath import fast_path

try:
    import strawberry_django as _strawberry_django
except ImportError as _exc:  # pragma: no cover - exercised via install extras
    raise ImportError(
        "fastberry.strawberry_django requires strawberry-graphql-django. "
        "Install it with: pip install 'fastberry[graphql]'"
    ) from _exc

__all__ = ["fast_schema", "interface", "type"]


def _wrap(sd_decorator_factory: Any) -> Callable[..., Any]:
    """Build a fast_path-applying passthrough for a strawberry_django decorator."""

    @wraps(sd_decorator_factory)
    def factory(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:
        sd_decorator = sd_decorator_factory(*args, **kwargs)

        def apply(cls: Any) -> Any:
            # Apply strawberry_django's decorator first (it builds
            # __strawberry_definition__), then fast_path on top.
            return fast_path(sd_decorator(cls))

        return apply

    return factory


# Mirror the strawberry_django decorators we want to fast-path.
type: Callable[..., Any] = _wrap(_strawberry_django.type)
interface: Callable[..., Any] = _wrap(_strawberry_django.interface)


def fast_schema(
    _model: Any = None,
    *,
    fields: Sequence[str] | None = None,
    name: str | None = None,
    **type_kwargs: Any,
) -> Any:
    """Generate a fast-pathed ``strawberry_django`` type from a Django model.

    Decorate the model itself. A GraphQL type is built from the model's fields
    (using ``strawberry.auto``), passed through ``strawberry_django.type`` and
    ``fast_path``, and stored on the model as ``__fast_type__`` so you can wire
    it into your schema::

        @fast_schema
        class Stock(models.Model): ...

        # later, in your schema module:
        StockType = Stock.__fast_type__

    Options:

    - ``fields`` — explicit list of model field names to expose. Defaults to all
      concrete fields (FKs included, as their related object via ``auto``).
    - ``name`` — GraphQL type name. Defaults to ``f"{Model.__name__}Type"``.
    - any extra keyword args are forwarded to ``strawberry_django.type``
      (e.g. ``disable_optimization=True``).

    Returns the model unchanged (only ``__fast_type__`` is attached), so it
    composes cleanly with other model decorators.
    """

    def wrap(model: Any) -> Any:
        # strawberry_django expands all model fields unless restricted via its
        # own ``fields`` argument, so the field set is controlled there (not via
        # the class annotations, which it does not treat as an allow-list).
        field_names = (
            list(fields) if fields is not None else [f.name for f in model._meta.concrete_fields]
        )
        type_name = name or f"{model.__name__}Type"

        # builtins.type: the module-level name ``type`` is the wrapper above.
        gql_cls = builtins.type(type_name, (), {})
        gql_cls = _strawberry_django.type(model, fields=field_names, **type_kwargs)(gql_cls)
        gql_cls = fast_path(gql_cls)

        model.__fast_type__ = gql_cls
        return model

    return wrap if _model is None else wrap(_model)
