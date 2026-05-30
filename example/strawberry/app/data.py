"""In-memory dataset for the pure-Strawberry example.

No database here on purpose: this example shows how ``fast_path`` /
``FastPathExtension`` are wired onto plain Strawberry types. The objects below
are just instances of the GraphQL types defined in :mod:`app.schema`, so a
resolver can hand them straight back.

The same House -> Space -> Stock -> Product shape is used across all three
examples so the schemas line up.
"""

from __future__ import annotations

import random

from app.schema import HouseType, ProductType, SpaceType, StockType


def build_dataset(
    houses: int = 50,
    spaces_per_house: int = 4,
    stocks_per_space: int = 8,
    products: int = 20,
    seed: int = 42,
) -> list[HouseType]:
    """Build a deterministic in-memory tree of ``HouseType`` instances."""
    rng = random.Random(seed)

    product_pool = [
        ProductType(id=i, name=f"Product {i}", ean=f"{4000000000000 + i}")
        for i in range(1, products + 1)
    ]

    result: list[HouseType] = []
    stock_id = 0
    space_id = 0
    for h in range(1, houses + 1):
        spaces: list[SpaceType] = []
        for _ in range(spaces_per_house):
            space_id += 1
            stocks: list[StockType] = []
            for _ in range(stocks_per_space):
                stock_id += 1
                stocks.append(
                    StockType(
                        id=stock_id,
                        title=f"Stock {stock_id}",
                        amount=round(rng.uniform(0, 100), 2),
                        price=round(rng.uniform(1, 999), 2),
                        product=rng.choice(product_pool),
                    )
                )
            spaces.append(SpaceType(id=space_id, name=f"Space {space_id}", stocks=stocks))
        result.append(
            HouseType(id=h, name=f"House {h}", address=f"Main St {h}", spaces=spaces)
        )
    return result


# Built once at import time and shared by the server and the benchmark.
HOUSES: list[HouseType] = build_dataset()
