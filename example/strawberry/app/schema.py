"""Pure-Strawberry GraphQL schema wired with fastberry's ``fast_path``.

``fast_path`` + ``FastPathExtension`` are framework-agnostic: any Strawberry
type with a ``__strawberry_definition__`` can be registered. Here we apply them
to plain ``@strawberry.type`` classes to show the wiring end to end.

Honesty note: the *performance* win of ``fast_path`` comes specifically from
bypassing ``strawberry-django``'s ``django_resolver`` (which calls
``in_async_context()`` per field under sync Django). Plain Strawberry types have
no such wrapper, so here ``fast_path`` is a transparent no-cost passthrough —
the benchmark in ``benchmark.py`` confirms parity. For the real speedup, see the
``strawberry_django`` example.
"""

from __future__ import annotations

import strawberry

from fastberry import FastPathExtension, fast_path


@fast_path
@strawberry.type
class ProductType:
    id: int
    name: str
    ean: str


@fast_path
@strawberry.type
class StockType:
    id: int
    title: str
    amount: float
    price: float
    product: ProductType


@fast_path
@strawberry.type
class SpaceType:
    id: int
    name: str
    stocks: list[StockType]


@fast_path
@strawberry.type
class HouseType:
    id: int
    name: str
    address: str
    spaces: list[SpaceType]


def _houses() -> list[HouseType]:
    # Imported lazily to avoid a circular import (data builds these types).
    from app.data import HOUSES

    return HOUSES


@strawberry.type
class Query:
    @strawberry.field
    def houses(self) -> list[HouseType]:
        return _houses()


# Schema used by the server: FastPathExtension active.
schema = strawberry.Schema(query=Query, extensions=[FastPathExtension])

# Same schema without the extension — only used by the benchmark for comparison.
plain_schema = strawberry.Schema(query=Query)
