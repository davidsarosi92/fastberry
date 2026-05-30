"""Fast-path field resolution for strawberry-django types.

The problem: every field on a ``@strawberry_django.type`` goes through
``django_resolver``, which calls ``in_async_context()`` on every resolution. In
sync Django, ``in_async_context()`` raises a ``RuntimeError`` internally and
catches it (~0.15ms/call). For a list of N objects with M fields each, this adds
up to seconds of pure overhead with zero database queries.

The fix: for types marked with ``@fast_path``, bypass ``django_resolver``
entirely.

- Plain fields: direct ``getattr(root, python_attr_name)``
- Custom resolvers: direct call to the wrapped function

Usage::

    import strawberry_django
    from fastberry import fast_path, FastPathExtension

    @fast_path
    @strawberry_django.type(MyModel, disable_optimization=True)
    class MyType:
        ...

    schema = strawberry.Schema(query=Query, extensions=[FastPathExtension])

To disable globally, remove ``FastPathExtension`` from the schema extensions
list. To disable for a single type, remove the ``@fast_path`` decorator.

Implementation note: ``root`` in :meth:`resolve` is a Django model instance, so
``type(root)`` is the Django model class (e.g. ``MyModel``), NOT the Strawberry
type class (e.g. ``MyType``). We therefore use ``info.parent_type.name`` (the
GraphQL type name string) as the lookup key.
"""

import inspect
from typing import Any, Callable, Union

from django.db.models import Manager
from strawberry.extensions import SchemaExtension
from strawberry.types import Info
from strawberry.utils.str_converters import to_camel_case

__all__ = ["FastPathExtension", "fast_path"]


class FastPathExtension(SchemaExtension):
    """Bypasses ``strawberry_django``'s ``django_resolver`` overhead.

    Only applies to types marked with :func:`fast_path`; all other types fall
    through to the normal resolution path untouched.
    """

    # Set of GraphQL type names (str) that have fast-path enabled.
    _fast_path_type_names: set[str] = set()

    # Pre-built resolver cache:
    #   (graphql_type_name, graphql_field_name) -> attr_name (str)
    #                                            |  (resolver_fn, param_count) (tuple)
    # Built at decoration time by register(), never modified at request time.
    _registry: dict[tuple[str, str], Union[str, tuple[Callable, int]]] = {}

    @classmethod
    def register(cls, strawberry_cls: type) -> None:
        """Build the resolver cache for ``strawberry_cls``.

        Called by :func:`fast_path` at class-definition time.
        """
        defn = strawberry_cls.__strawberry_definition__
        type_name: str = defn.name  # GraphQL type name (e.g. 'MyType')
        cls._fast_path_type_names.add(type_name)
        for field in defn.fields:
            graphql_name = getattr(field, "graphql_name", None) or to_camel_case(field.name)
            key = (type_name, graphql_name)
            if field.base_resolver is not None:
                fn = field.base_resolver.wrapped_func
                param_count = len(inspect.signature(fn).parameters)
                cls._registry[key] = (fn, param_count)
            else:
                cls._registry[key] = field.name  # Python attribute name -> getattr

    def resolve(self, _next: Callable, root: Any, info: Info, *args: Any, **kwargs: Any) -> Any:
        type_name: str = info.parent_type.name
        if type_name not in self._fast_path_type_names:
            return _next(root, info, *args, **kwargs)

        key = (type_name, info.field_name)
        cached = self._registry.get(key)

        if cached is None:
            return _next(root, info, *args, **kwargs)

        if isinstance(cached, str):
            value = getattr(root, cached, None)
            if isinstance(value, Manager):
                return value.all()
            return value

        fn, param_count = cached
        if param_count <= 1:
            return fn(root)
        return fn(root, info, **kwargs)


def fast_path(cls: type) -> type:
    """Mark a ``@strawberry_django.type`` for fast-path field resolution.

    Apply *after* ``@strawberry_django.type`` (i.e. as the outermost
    decorator)::

        @fast_path
        @strawberry_django.type(MyModel)
        class MyType:
            ...
    """
    FastPathExtension.register(cls)
    return cls